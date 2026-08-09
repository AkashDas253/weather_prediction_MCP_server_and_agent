"""
Weather API adapter/broker backing the Weather MCP Server.

This module acts as the broker adapter layer for weather market/forecast data.
It handles geocoding, HTTP requests to Open-Meteo APIs, data parsing, and
optional Databricks secret resolution.

Swap-in note: this module exposes clean functions (get_current_weather, 
get_forecast, predict_umbrella_needed, compare_weather) so weather_mcp_server.py 
only needs to import this module and wrap these calls inside @mcp.tool decorators.
"""

import base64
import os
import requests
from typing import Any, Dict, List, Optional
from databricks.sdk import WorkspaceClient

# Optional Databricks WorkspaceClient initialization for secrets (if using an API key)
_w: Optional[WorkspaceClient] = None

_SECRET_SCOPE = os.environ.get("WEATHER_SECRET_SCOPE", "database")
_API_KEY_SECRET_NAME = os.environ.get("WEATHER_API_KEY_SECRET_NAME", "weather-api-key")

GEOCODING_URL = "https://geocoding-api.open-meteo.com/v1/search"
WEATHER_URL = "https://api.open-meteo.com/v1/forecast"
HTTP_TIMEOUT = 10


def _get_workspace_client() -> WorkspaceClient:
    """Lazy initialization of the Databricks WorkspaceClient."""
    global _w
    if _w is None:
        _w = WorkspaceClient()
    return _w


def _secret(key: str) -> str:
    """Fetch and base64-decode a value from the Databricks secret scope."""
    w = _get_workspace_client()
    secret = w.secrets.get_secret(scope=_SECRET_SCOPE, key=key)
    return base64.b64decode(secret.value).decode("utf-8")


def _geocode(location: str) -> Dict[str, Any]:
    """
    Resolve a human-readable location string (city, state, zip) to 
    latitude, longitude, timezone, and normalized name metadata.
    """
    response = requests.get(
        GEOCODING_URL,
        params={"name": location, "count": 1, "language": "en", "format": "json"},
        timeout=HTTP_TIMEOUT,
    )
    response.raise_for_status()
    data = response.json()
    results = data.get("results")

    if not results:
        raise ValueError(f"Location '{location}' could not be resolved.")

    first = results[0]
    return {
        "name": first.get("name"),
        "country": first.get("country", ""),
        "admin1": first.get("admin1", ""),
        "latitude": first.get("latitude"),
        "longitude": first.get("longitude"),
        "timezone": first.get("timezone", "UTC"),
    }


def get_current_weather(location: str) -> Dict[str, Any]:
    """
    Get current weather metrics for a location string.
    Converts temperature to both Celsius and Fahrenheit.
    """
    geo = _geocode(location)
    params = {
        "latitude": geo["latitude"],
        "longitude": geo["longitude"],
        "current_weather": "true",
        "timezone": geo["timezone"],
    }

    response = requests.get(WEATHER_URL, params=params, timeout=HTTP_TIMEOUT)
    response.raise_for_status()
    current = response.json().get("current_weather", {})

    temp_c = current.get("temperature")
    temp_f = round((temp_c * 9 / 5) + 32, 1) if temp_c is not None else None

    formatted_location = f"{geo['name']}, {geo['admin1']}, {geo['country']}".strip(", ")
    return {
        "location": formatted_location,
        "latitude": geo["latitude"],
        "longitude": geo["longitude"],
        "temperature_celsius": temp_c,
        "temperature_fahrenheit": temp_f,
        "windspeed_kmh": current.get("windspeed"),
        "winddirection": current.get("winddirection"),
        "weathercode": current.get("weathercode"),
        "time": current.get("time"),
    }


def get_forecast(location: str, days: int = 3) -> Dict[str, Any]:
    """
    Fetch daily weather forecast metrics for up to 7 days for a given location.
    """
    days = max(1, min(int(days), 7))
    geo = _geocode(location)
    params = {
        "latitude": geo["latitude"],
        "longitude": geo["longitude"],
        "daily": [
            "temperature_2m_max",
            "temperature_2m_min",
            "precipitation_probability_max",
            "weathercode",
        ],
        "forecast_days": days,
        "timezone": geo["timezone"],
    }

    response = requests.get(WEATHER_URL, params=params, timeout=HTTP_TIMEOUT)
    response.raise_for_status()
    daily = response.json().get("daily", {})

    times = daily.get("time", [])
    temp_max = daily.get("temperature_2m_max", [])
    temp_min = daily.get("temperature_2m_min", [])
    precip_prob = daily.get("precipitation_probability_max", [])
    codes = daily.get("weathercode", [])

    forecast_list: List[Dict[str, Any]] = []
    for i in range(len(times)):
        forecast_list.append(
            {
                "date": times[i],
                "temp_max_c": temp_max[i] if i < len(temp_max) else None,
                "temp_min_c": temp_min[i] if i < len(temp_min) else None,
                "precip_probability_pct": precip_prob[i] if i < len(precip_prob) else 0,
                "weathercode": codes[i] if i < len(codes) else None,
            }
        )

    formatted_location = f"{geo['name']}, {geo['admin1']}, {geo['country']}".strip(", ")
    return {
        "location": formatted_location,
        "days_requested": days,
        "forecast": forecast_list,
    }


def predict_umbrella_needed(location: str, days: int = 1) -> Dict[str, Any]:
    """
    Evaluate precipitation likelihood for upcoming days and issue an umbrella recommendation.
    Threshold logic:
      - >= 40% precipitation probability -> YES
      - 20% to 39% precipitation probability -> MAYBE
      - < 20% precipitation probability -> NO
    """
    forecast_data = get_forecast(location, days=days)
    forecasts = forecast_data.get("forecast", [])
    max_precip = max([f.get("precip_probability_pct", 0) for f in forecasts], default=0)

    if max_precip >= 40:
        status = "YES"
        recommendation = f"Umbrella strongly recommended. Max rain probability is {max_precip}%."
    elif max_precip >= 20:
        status = "MAYBE"
        recommendation = f"Light chance of rain ({max_precip}%). Consider carrying a compact umbrella or jacket."
    else:
        status = "NO"
        recommendation = f"Dry conditions expected (only {max_precip}% rain chance). No umbrella needed."

    return {
        "location": forecast_data["location"],
        "umbrella_needed": status,
        "max_precipitation_probability_pct": max_precip,
        "recommendation": recommendation,
        "evaluated_days": len(forecasts),
    }


def compare_weather(location_a: str, location_b: str) -> Dict[str, Any]:
    """
    Fetch current conditions for two locations side-by-side and calculate the temperature difference.
    """
    data_a = get_current_weather(location_a)
    data_b = get_current_weather(location_b)

    temp_a = data_a.get("temperature_celsius", 0.0)
    temp_b = data_b.get("temperature_celsius", 0.0)
    diff = round(abs(temp_a - temp_b), 1)

    warmer = data_a["location"] if temp_a >= temp_b else data_b["location"]

    return {
        "location_a": data_a,
        "location_b": data_b,
        "temperature_delta_celsius": diff,
        "warmer_location": warmer,
    }