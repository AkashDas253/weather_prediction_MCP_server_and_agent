"""
Weather-Prediction MCP server.

Exposes weather forecast and recommendation tools over MCP (Model Context Protocol) 
so a Databricks Agent Bricks agent can call them like any other tool:
    - get_current_weather(location)
    - get_forecast(location, days)
    - predict_umbrella_needed(location, days)
    - compare_weather(location_a, location_b)
    - get_current_user()

These tools are backed by Open-Meteo's REST API (via weather_broker.py), allowing 
students and developers to wire an Agent Bricks agent to deliver live weather 
insights, multi-day forecasts, and rain/gear predictions without needing paid 
API keys or credit cards.

Swap-in-a-real-broker note: to point this at a different weather provider (e.g. NOAA/NWS,
WeatherAPI, AccuWeather) or add secret resolution, keep the tool signatures below and 
update the weather_broker.* implementation - the MCP surface for the agent does not 
need to change.

Deploy this as its own Databricks App (same app.yaml + FastMCP entrypoint pattern 
documented at https://docs.databricks.com/aws/en/agents/mcp-tools/custom-mcp), 
separate from any dashboard app, so an Agent Bricks agent (or any MCP client) 
can register its URL as an external MCP server.

Run locally:
    python weather_mcp_server.py
"""

import os
import logging
from contextvars import ContextVar

from fastmcp import FastMCP
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request

import weather_broker

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("weather-mcp-server")

# Context variable to store request headers for accessing end-user identity
_request_context: ContextVar[dict] = ContextVar('request_context', default={})


def _get_end_user_email() -> str:
    """Get the actual end user's email from request headers, or fallback to service principal."""
    headers = _request_context.get()
    forwarded_user = headers.get('x-forwarded-user')
    if forwarded_user:
        return forwarded_user

    # Fallback: use service principal (local development or non-App contexts)
    try:
        from databricks.sdk import WorkspaceClient
        w = WorkspaceClient()
        return w.current_user.me().user_name or 'user@example.com'
    except Exception:
        return 'user@example.com'


mcp = FastMCP("weather-prediction")


class RequestContextMiddleware(BaseHTTPMiddleware):
    """Middleware to capture HTTP headers containing end-user identity."""
    async def dispatch(self, request: Request, call_next):
        # Capture headers that Databricks injects with user identity
        headers = {
            'x-forwarded-user': request.headers.get('x-forwarded-user'),
            'x-forwarded-email': request.headers.get('x-forwarded-email'),
        }
        _request_context.set(headers)
        response = await call_next(request)
        return response


@mcp.tool
def get_current_weather(location: str) -> dict:
    """
    Fetch real-time weather conditions for a specified location.

    Args:
        location: City name, address, or postal code (e.g., "Chicago", "Austin, TX", "London").

    Returns:
        A dict with location details, temperature (Celsius and Fahrenheit), wind speed, 
        wind direction, weather code, and timestamp.
    """
    try:
        return weather_broker.get_current_weather(location)
    except Exception as e:
        logger.exception(f"Failed to fetch current weather for {location}")
        return {
            "status": "error",
            "message": f"Failed to fetch current weather for '{location}': {str(e)}"
        }


@mcp.tool
def get_forecast(location: str, days: int = 3) -> dict:
    """
    Fetch a multi-day weather forecast for a specified location.

    Args:
        location: City name or address string, e.g. "Chicago, IL".
        days: Number of forecast days to return (1 to 7, default 3).

    Returns:
        A dict with formatted location, days requested, and daily forecast breakdowns 
        (max/min temperature, precipitation probability, weather code).
    """
    try:
        return weather_broker.get_forecast(location, days=days)
    except Exception as e:
        logger.exception(f"Failed to fetch forecast for {location}")
        return {
            "status": "error",
            "message": f"Failed to fetch forecast for '{location}': {str(e)}"
        }


@mcp.tool
def predict_umbrella_needed(location: str, days: int = 1) -> dict:
    """
    Evaluate rain likelihood and provide a derived umbrella recommendation.

    Applies threshold logic:
      - Max rain probability >= 40% -> YES (Bring umbrella)
      - Max rain probability >= 20% -> MAYBE (Consider compact coat/umbrella)
      - Max rain probability < 20%  -> NO (Dry conditions expected)

    Args:
        location: City name or location string, e.g. "Seattle".
        days: Number of upcoming days to evaluate (default 1).

    Returns:
        A dict with umbrella_needed status ('YES', 'MAYBE', 'NO'), max rain probability, 
        and actionable recommendation text.
    """
    try:
        return weather_broker.predict_umbrella_needed(location, days=days)
    except Exception as e:
        logger.exception(f"Failed to calculate umbrella recommendation for {location}")
        return {
            "status": "error",
            "message": f"Failed to calculate umbrella recommendation for '{location}': {str(e)}"
        }


@mcp.tool
def compare_weather(location_a: str, location_b: str) -> dict:
    """
    Compare current temperature and weather conditions between two cities.

    Args:
        location_a: First city name, e.g. "Austin, TX".
        location_b: Second city name, e.g. "Miami, FL".

    Returns:
        A dict with side-by-side weather snapshots, temperature delta (Celsius), 
        and identification of the warmer location.
    """
    try:
        return weather_broker.compare_weather(location_a, location_b)
    except Exception as e:
        logger.exception(f"Failed to compare weather between {location_a} and {location_b}")
        return {
            "status": "error",
            "message": f"Failed to compare weather between '{location_a}' and '{location_b}': {str(e)}"
        }


@mcp.tool
def get_current_user() -> dict:
    """
    Get information about the currently authenticated end user accessing the MCP server.

    When running as a Databricks App, this returns the actual end user making the
    request (from X-Forwarded-User header), not the service principal running the app.

    Returns:
        A dict with user_name (email from X-Forwarded-User header),
        forwarded_email, and source ("request_header" or "service_principal").
    """
    try:
        headers = _request_context.get()
        forwarded_user = headers.get('x-forwarded-user')
        forwarded_email = headers.get('x-forwarded-email')

        if forwarded_user:
            return {
                "status": "success",
                "user_name": forwarded_user,
                "forwarded_email": forwarded_email,
                "source": "request_header",
            }

        from databricks.sdk import WorkspaceClient
        w = WorkspaceClient()
        user = w.current_user.me()
        return {
            "status": "success",
            "user_name": user.user_name,
            "display_name": user.display_name,
            "active": user.active,
            "source": "service_principal",
        }
    except Exception as e:
        logger.exception("Failed to get current user")
        return {
            "status": "error",
            "message": f"Failed to get current user: {str(e)}",
        }


if __name__ == "__main__":
    # Add middleware to capture request headers for end-user identity
    if hasattr(mcp, 'app') and mcp.app is not None:
        mcp.app.add_middleware(RequestContextMiddleware)

    # Databricks Apps route external HTTP traffic to this port via app.yaml;
    # streamable-http is the transport Databricks' MCP client/gateway expects.
    port = int(os.getenv("DATABRICKS_APP_PORT", os.getenv("PORT", 8000)))
    mcp.run(transport="http", host="0.0.0.0", port=port)