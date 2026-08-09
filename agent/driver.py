"""
Driver script to test the agent locally and log it to Databricks Unity Catalog / MLflow.
"""

import mlflow
from agent import WeatherAgent

def run_test():
    agent = WeatherAgent("agent_config.yaml")

    test_queries = [
        "Will it rain in Chicago tomorrow?",
        "Should I bring a jacket to Austin this weekend?",
        "Compare the weather between Miami and Seattle right now."
    ]

    print("--- Testing Weather Agent Locally ---")
    for query in test_queries:
        print(f"\nUser Query: {query}")
        result = agent.predict(query)
        print(f"Tools Used: {result['tool_calls']}")
        print(f"Agent Answer:\n{result['response']}")

def log_agent_to_mlflow():
    """Register the agent into Databricks MLflow for Agent Bricks deployment."""
    mlflow.set_experiment("/Shared/weather_agent_experiment")

    with mlflow.start_run():
        logged_model = mlflow.pyfunc.log_model(
            artifact_path="weather_agent",
            python_model="agent.py",
            pip_requirements="requirements.txt",
        )
        print(f"Agent logged successfully. Model URI: {logged_model.model_uri}")

if __name__ == "__main__":
    run_test()