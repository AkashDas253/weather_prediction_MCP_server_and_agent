# Weather-Prediction MCP Server & Agent Bricks Advisor

A production-ready Model Context Protocol (MCP) server and Databricks Agent Bricks agent setup for fetching weather metrics, running derived predictive logic, comparing conditions across locations, and securing context with end-user identity tracking.

---

## Overview & Architecture

This repository contains two core components deployed as **Databricks Apps**:

1. **Weather MCP Server (`weather_mcp_server.py`)**: A FastMCP HTTP server exposing tools for current weather, multi-day forecasts, umbrella recommendations, city comparisons, and user context verification.
2. **Databricks Agent Bricks Agent**: An agent configured with a structured system prompt that queries the MCP server as an external tool to answer natural language weather and travel inquiries.

```
[ Databricks User / Client ]
            │
            ▼
[ Agent Bricks Agent ] ──(HTTP/MCP)──► [ FastMCP Server (weather_mcp_server.py) ]
                                                   │
                                                   ▼
                                        [ Weather Broker Module ]
                                          (weather_broker.py)
                                                   │
                                                   ▼
                                        [ Open-Meteo REST API ]

```

---

## Exposed MCP Tools

| Tool Name | Parameters | Threshold & Logic | Description |
| --- | --- | --- | --- |
| `get_current_weather` | `location` *(str)* | N/A | Fetches real-time weather metrics (temperature in °C/°F, wind speed, weather codes) via Open-Meteo. |
| `get_forecast` | `location` *(str)*, `days` *(int, 1-7)* | Max 7 days | Retrieves daily forecast metrics, high/low temperatures, and maximum precipitation probabilities. |
| `predict_umbrella_needed` | `location` *(str)*, `days` *(int)* | **≥40%** = `YES`<br>

<br>**20%–39%** = `MAYBE`<br>

<br>**<20%** = `NO` | Evaluates maximum forecasted rain probability percentage across the requested window and provides actionable advice. |
| `compare_weather` | `location_a` *(str)*, `location_b` *(str)* | Absolute Delta Calculation | Compares current weather conditions between two cities, calculates temperature delta (°C), and identifies the warmer city. |
| `get_current_user` | None | Header / SDK Context | Identity tool retrieving user metadata from forwarded proxy headers (`x-forwarded-user`, `x-forwarded-email`) or Databricks SDK context. |

---

## Security & API Integration

### 1. Weather API Integration

* **Provider**: [Open-Meteo REST API](https://open-meteo.com/)
* **Authentication**: Free tier, no API key required for non-commercial requests up to 10,000 calls/day.
* **Separation of Concerns**: All HTTP client requests and geocoding logic are isolated inside `weather_broker.py`, keeping FastMCP tool functions thin and decoupled.

### 2. Context-Aware Identity Tracking

* **Middleware Integration**: `RequestContextMiddleware` intercepts Starlette/FastAPI HTTP requests to capture `x-forwarded-user` and `x-forwarded-email` headers into Python's `ContextVar`.
* **User Audit Capabilities**: The `get_current_user` MCP tool provides audit visibility into whether a request originates from an end user via workspace headers or via a Service Principal SDK identity.

---

## Project Structure

```
.
├── mcp_server/
│   ├── weather_mcp_server.py # FastMCP server entrypoint, middleware, and tool definitions
│ ├── app.yaml              # Databricks App deployment specification
│ ├── requirements.txt      # Python dependencies
│   └── weather_broker.py     # HTTP adapter module handling Open-Meteo API calls & geocoding
├── system_prompt.md          # System prompt configuration for Agent Bricks 
├── readme.md               # System prompt configuration for Agent Bricks 
└── screenshots/              # Verification screenshots for submission
    ├── question1.png         # Check current weather
    ├── question2.png         # Umbrella recommendation
    └── question3.png         # Multi-day forecast

```

---

## Verification & Screenshots

Below are the visual execution results from the Databricks Agent Bricks workspace:

1. [Check Current Weather](screenshots/question1.png)
2. [Check If Umbrella Is Needed](https://www.google.com/search?q=screenshots/question2.png)
3. [Next Week / Multi-Day Forecast](https://www.google.com/search?q=screenshots/question3.png)

---

### Conversation Log & Execution Summary

Below are the tool executions and agent responses for the requested weather queries:

---

#### Prompt 1: Current Temperature in NYC

* **User Query**: `"temp today in nyc"`
* **Tool Call**: `get_current_weather(location="NYC")`
* **Tool Response**:
```json
{
  "status": "success",
  "location": "New York, New York, United States",
  "latitude": 40.71427,
  "longitude": -74.00597,
  "temperature_celsius": 24.7,
  "temperature_fahrenheit": 76.5,
  "windspeed_kmh": 11.8,
  "winddirection": 250,
  "weathercode": 1,
  "time": "2026-08-09T08:15"
}

```


* **Agent Final Answer**:
> The current temperature in **New York, New York** is **24.7°C / 76.5°F**.



---

#### Prompt 2: Detroit Rain Forecast

* **User Query**: `"will it rain tomorrow in detroit?"`
* **Tool Call**: `predict_umbrella_needed(location="Detroit", days=1)`
* **Tool Response**:
```json
{
  "status": "success",
  "location": "Detroit, Michigan, United States",
  "umbrella_needed": "MAYBE",
  "max_precipitation_probability_pct": 22,
  "recommendation": "Light chance of rain (22%). Consider carrying a compact umbrella or jacket.",
  "evaluated_days": 1
}

```


* **Agent Final Answer**:
> There is a **light chance of rain (22%)** in Detroit tomorrow.
> **Recommendation**: **MAYBE**. Consider bringing along a compact umbrella or light rain jacket just in case.



---

#### Prompt 3: Best Day for a Long Trip in NYC

* **User Query**: `"next best day to go for long trip in nyc"`
* **Tool Call**: `get_forecast(location="New York City", days=7)`
* **Tool Response**:
```json
{
  "status": "success",
  "location": "New York, New York, United States",
  "days_requested": 7,
  "forecast": [
    {"date": "2026-08-09", "temp_max_c": 33.9, "temp_min_c": 22.5, "precip_probability_pct": 1, "weathercode": 3},
    {"date": "2026-08-10", "temp_max_c": 34.4, "temp_min_c": 21.7, "precip_probability_pct": 50, "weathercode": 51},
    {"date": "2026-08-11", "temp_max_c": 32.1, "temp_min_c": 23.8, "precip_probability_pct": 16, "weathercode": 51},
    {"date": "2026-08-12", "temp_max_c": 27.8, "temp_min_c": 23.9, "precip_probability_pct": 34, "weathercode": 3},
    {"date": "2026-08-13", "temp_max_c": 30.7, "temp_min_c": 23.1, "precip_probability_pct": 34, "weathercode": 51},
    {"date": "2026-08-14", "temp_max_c": 26.8, "temp_min_c": 19.3, "precip_probability_pct": 9, "weathercode": 3},
    {"date": "2026-08-15", "temp_max_c": 26.5, "temp_min_c": 17.8, "precip_probability_pct": 8, "weathercode": 1}
  ]
}

```


* **Agent Final Answer**:
> Based on the 7-day forecast for New York City, the best overall days for a long outdoor trip are **August 14th** and **August 15th**:
> * **August 15th (Best Choice)**: Comfortable high of **26.5°C / 79.7°F**, low rain chance (**8%**), and clear/partly clear skies (Weathercode 1).
> * **August 14th (Great Alternative)**: Pleasant high of **26.8°C / 80.2°F** with a low rain chance (**9%**).
> 
> 
> *Note on August 9th*: While rain chance is very low (1%), the high temperature reaches **33.9°C / 93.0°F**, which may make extended outdoor travel uncomfortably hot.

---

## System Prompt (`system_prompt.md`)

```markdown
# Weather & Travel Advisor Agent System Prompt

You are an intelligent Weather & Travel Advisor agent powered by an external Weather MCP server.
Your goal is to answer natural-language weather questions, recommend clothing/gear, and assist with travel planning.

## Behavioral Rules:
1. ALWAYS call an MCP weather tool before providing a weather answer or recommendation. Never guess weather data.
2. Map user queries to tools:
   - Current conditions/temperature -> get_current_weather(location)
   - Multi-day forecasts or future dates -> get_forecast(location, days)
   - Rain, umbrella, or gear/clothing advice -> predict_umbrella_needed(location, days)
   - Weather comparison between cities -> compare_weather(location_a, location_b)
   - End-user identity verification -> get_current_user()
3. Tool Execution Order: Always fetch forecast or current weather metrics BEFORE executing secondary logic or offering recommendations.
4. When asked "Should I bring a jacket/umbrella?", call predict_umbrella_needed or get_forecast to check both temperature and precipitation chances before answering.
5. Present temperatures in both Celsius and Fahrenheit (°C / °F).
6. Guardrail: If an API call fails or a location is invalid, politely ask the user to clarify instead of fabricating data.

```

---

## Links
- [GitHub](https://github.com/AkashDas253/weather_prediction_MCP_server_and_agent/)