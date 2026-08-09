import os
import logging
from contextvars import ContextVar

from fastmcp import FastMCP
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request

import weather_broker

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("weather-mcp-server")

_request_context: ContextVar[dict] = ContextVar('request_context', default={})

mcp = FastMCP("weather-prediction")


class RequestContextMiddleware(BaseHTTPMiddleware):
    """Middleware to capture HTTP headers containing end-user identity."""
    async def dispatch(self, request: Request, call_next):
        headers = {
            'x-forwarded-user': request.headers.get('x-forwarded-user'),
            'x-forwarded-email': request.headers.get('x-forwarded-email'),
        }
        _request_context.set(headers)
        response = await call_next(request)
        return response


@mcp.tool
def get_current_weather(location: str) -> dict:
    """Fetch real-time weather conditions for a specified location."""
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
    """Fetch a multi-day weather forecast for a specified location."""
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
    """Evaluate rain likelihood and provide a derived umbrella recommendation."""
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
    """Compare current temperature and weather conditions between two cities."""
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
    """Get information about the currently authenticated end user accessing the MCP server."""
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
    if hasattr(mcp, 'app') and mcp.app is not None:
        mcp.app.add_middleware(RequestContextMiddleware)

    port = int(os.getenv("DATABRICKS_APP_PORT", os.getenv("PORT", 8000)))
    mcp.run(transport="http", host="0.0.0.0", port=port)