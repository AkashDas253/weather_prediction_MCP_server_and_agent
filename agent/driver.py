"""
Driver script to test the agent locally/in-notebook and log it to Databricks Unity Catalog / MLflow.
"""

import os
import mlflow
from mlflow.models.resources import DatabricksServingEndpoint
from agent import WeatherAgent


def run_test():
    """Test the WeatherAgent locally across sample queries."""
    agent = WeatherAgent("agent_config.yaml")

    test_queries = [
        "Will it rain in Chicago tomorrow?",
        "Should I bring a jacket to Austin this weekend?",
        "Compare the weather between Miami and Seattle right now."
    ]

    print("==================================================")
    print("        Testing Weather Agent Locally             ")
    print("==================================================")

    for query in test_queries:
        print(f"\n[User Query]: {query}")
        result = agent.predict(query)

        print("[Tools Executed]:")
        tool_calls = result.get("tool_calls", [])
        if tool_calls:
            for tc in tool_calls:
                print(f"  - {tc.get('tool')}({tc.get('args')})")
        else:
            print("  - None")

        print(f"\n[Agent Answer]:\n{result['response']}\n")
        print("-" * 50)


def log_agent_to_mlflow():
    """Log and register the agent into Databricks MLflow / Unity Catalog for Agent Bricks deployment."""
    mlflow.set_experiment("/Shared/weather_agent_experiment")

    model_endpoint = os.getenv("MODEL_ENDPOINT", "databricks-meta-llama-3-3-70b-instruct")

    # Declare Databricks Serving Endpoint dependencies for governance & deployment validation
    resources = [
        DatabricksServingEndpoint(endpoint_name=model_endpoint)
    ]

    # Sample input for MLflow signature inference & endpoint testing
    input_example = {
        "user_query": "Will it rain in Chicago tomorrow?"
    }

    with mlflow.start_run():
        logged_model = mlflow.pyfunc.log_model(
            python_model="agent.py",
            artifact_path="weather_agent",
            code_paths=["agent_config.yaml"],
            resources=resources,
            pip_requirements="requirements.txt",
            input_example=input_example,
            # Uncomment to automatically register in Unity Catalog:
            # registered_model_name="main.default.weather_prediction_agent"
        )

        print("\n==================================================")
        print("   Agent Logged Successfully to MLflow!          ")
        print("==================================================")
        print(f"Model URI: {logged_model.model_uri}")


if __name__ == "__main__":
    run_test()