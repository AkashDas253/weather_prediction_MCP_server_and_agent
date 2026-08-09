"""
Databricks Agent Bricks / Agent Framework Implementation.

Connects to the deployed Weather MCP Server as an external tool source
and answers natural language queries using LLM tool calling.
"""

import os
import yaml
import logging
from typing import List, Dict, Any

from databricks.sdk import WorkspaceClient
from databricks_mcp import DatabricksMCPClient
from databricks_langchain import ChatDatabricks
from langchain_core.messages import HumanMessage, SystemMessage, AIMessage, ToolMessage

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("weather-agent")


class WeatherAgent:
    def __init__(self, config_path: str = "agent_config.yaml"):
        # Load agent configuration
        with open(config_path, "r") as f:
            self.config = yaml.safe_load(f)

        self.workspace_client = WorkspaceClient()
        self.system_prompt = self.config.get("system_prompt", "")
        self.model_endpoint = self.config.get("model_endpoint", "databricks-meta-llama-3-3-70b-instruct")
        self.mcp_url = self.config.get("mcp_server_url")

        # Initialize MCP Client connected to the Databricks App MCP server
        self.mcp_client = DatabricksMCPClient(
            server_url=self.mcp_url,
            workspace_client=self.workspace_client,
        )

        # Initialize Databricks LLM
        self.llm = ChatDatabricks(endpoint=self.model_endpoint, temperature=0.1)

    def get_tools(self) -> List[Any]:
        """Fetch registered tools directly from the Weather MCP Server."""
        return self.mcp_client.list_tools()

    def predict(self, user_query: str) -> Dict[str, Any]:
        """
        Execute agent reasoning loop:
        1. Query LLM with user question and available MCP tools.
        2. Execute tool call on MCP server if requested by LLM.
        3. Pass tool results back to LLM for final response generation.
        """
        tools = self.get_tools()
        llm_with_tools = self.llm.bind_tools(tools)

        messages = [
            SystemMessage(content=self.system_prompt),
            HumanMessage(content=user_query)
        ]

        # Step 1: First LLM pass
        response = llm_with_tools.invoke(messages)
        messages.append(response)

        # Step 2: Handle Tool Calls
        if hasattr(response, "tool_calls") and response.tool_calls:
            for tool_call in response.tool_calls:
                tool_name = tool_call["name"]
                tool_args = tool_call["args"]

                logger.info(f"Executing MCP Tool Call: {tool_name}({tool_args})")
                tool_result = self.mcp_client.call_tool(tool_name, tool_args)

                # Append tool response message
                messages.append(
                    ToolMessage(
                        content=str(tool_result),
                        tool_call_id=tool_call["id"]
                    )
                )

            # Step 3: Final LLM pass with tool observation
            final_response = llm_with_tools.invoke(messages)
            return {
                "user_query": user_query,
                "response": final_response.content,
                "tool_calls": [tc["name"] for tc in response.tool_calls]
            }

        return {
            "user_query": user_query,
            "response": response.content,
            "tool_calls": []
        }