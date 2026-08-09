"""
Databricks Agent Bricks / Agent Framework Implementation.

Connects to the deployed Weather MCP Server as an external tool source
and answers natural language queries using LLM tool calling.

Supports dynamic configuration via Environment Variables, Databricks Secrets,
and local YAML fallbacks with built-in tool execution retry logic.
"""

import base64
import logging
import os
import time
from typing import Any, Dict, List

from databricks.langchain import ChatDatabricks
from databricks_mcp import DatabricksMCPClient
from databricks.sdk import WorkspaceClient
from langchain_core.messages import HumanMessage, SystemMessage, ToolMessage
import yaml

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("weather-agent")


class WeatherAgent:
    def __init__(self, config_path: str = "agent_config.yaml"):
        # 1. Load local YAML configuration fallback
        self.config = {}
        if os.path.exists(config_path):
            with open(config_path, "r") as f:
                self.config = yaml.safe_load(f) or {}

        self.workspace_client = WorkspaceClient()

        # 2. Resolve Model Endpoint: Env Var -> YAML Config -> Default Fallback
        self.model_endpoint = os.getenv(
            "MODEL_ENDPOINT",
            self.config.get("model_endpoint", "databricks-meta-llama-3-3-70b-instruct")
        )

        # 3. Resolve MCP Server URL: Env Var -> Databricks Secret Scope -> YAML Config
        self.mcp_url = os.getenv("MCP_SERVER_URL")

        if not self.mcp_url:
            scope = os.getenv("MCP_SECRET_SCOPE", self.config.get("secret_scope", "database"))
            key = os.getenv("MCP_SECRET_KEY", self.config.get("mcp_url_secret_key", "mcp-server-url"))
            try:
                secret_obj = self.workspace_client.secrets.get_secret(scope=scope, key=key)
                self.mcp_url = base64.b64decode(secret_obj.value).decode("utf-8")
                logger.info(f"Loaded MCP_SERVER_URL from Databricks Secret Scope '{scope}/{key}'.")
            except Exception:
                self.mcp_url = self.config.get("mcp_server_url")

        if not self.mcp_url:
            raise ValueError(
                "MCP Server URL not found. Provide it via MCP_SERVER_URL environment variable, "
                "Databricks secret scope, or mcp_server_url in agent_config.yaml."
            )

        self.system_prompt = self.config.get("system_prompt", "")

        # 4. Initialize Databricks MCP Client & Chat Model
        logger.info(f"Initializing MCP Client connected to: {self.mcp_url}")
        self.mcp_client = DatabricksMCPClient(
            server_url=self.mcp_url,
            workspace_client=self.workspace_client,
        )
        self.llm = ChatDatabricks(endpoint=self.model_endpoint, temperature=0.1)

    def get_tools(self) -> List[Any]:
        """Fetch registered tools directly from the Weather MCP Server."""
        return self.mcp_client.list_tools()

    def _call_tool_with_retry(self, tool_name: str, tool_args: dict, max_retries: int = 3) -> Any:
        """Call MCP tool with exponential backoff to handle cold-starts and transient RST_STREAM resets."""
        delay = 1.0
        for attempt in range(1, max_retries + 1):
            try:
                logger.info(f"[Attempt {attempt}/{max_retries}] Executing MCP Tool: {tool_name}({tool_args})")
                return self.mcp_client.call_tool(tool_name, tool_args)
            except Exception as e:
                logger.warning(f"Tool execution attempt {attempt} failed: {e}")
                if attempt == max_retries:
                    return {"error": f"Tool execution failed after {max_retries} attempts: {str(e)}"}
                time.sleep(delay)
                delay *= 2.0

    def predict(self, user_query: str) -> Dict[str, Any]:
        """
        Execute agent reasoning loop:
        1. Query LLM with user question and available MCP tools.
        2. Execute tool calls on MCP server using retries if requested by LLM.
        3. Pass tool observations back to LLM for final response generation.
        """
        tools = self.get_tools()
        llm_with_tools = self.llm.bind_tools(tools)

        messages = [
            SystemMessage(content=self.system_prompt),
            HumanMessage(content=user_query)
        ]

        # Step 1: Initial LLM pass
        response = llm_with_tools.invoke(messages)
        messages.append(response)

        # Step 2: Process tool calls requested by LLM
        if hasattr(response, "tool_calls") and response.tool_calls:
            executed_tools = []
            for tool_call in response.tool_calls:
                t_name = tool_call["name"]
                t_args = tool_call["args"]

                tool_result = self._call_tool_with_retry(t_name, t_args)
                executed_tools.append({"tool": t_name, "args": t_args, "result": tool_result})

                # Append tool observation message
                messages.append(
                    ToolMessage(
                        content=str(tool_result),
                        tool_call_id=tool_call["id"]
                    )
                )

            # Step 3: Final LLM pass with tool results
            final_response = llm_with_tools.invoke(messages)
            return {
                "user_query": user_query,
                "response": final_response.content,
                "tool_calls": executed_tools
            }

        return {
            "user_query": user_query,
            "response": response.content,
            "tool_calls": []
        }