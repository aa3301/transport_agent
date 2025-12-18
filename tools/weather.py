"""
Weather tool.

Provides:
- get_weather_by_coords(lat, lon): returns current weather at given coordinates.
- get_weather(city): fallback by city name.

Uses a real HTTP weather API (e.g. OpenWeatherMap) with API key from settings.WEATHER_API_KEY.
The returned dict is normalized so agents can rely on common keys:
    {
        "condition": str,          # main condition (e.g. "Clouds", "Haze")
        "description": str,        # longer description (e.g. "scattered clouds")
        "temp": float,             # temperature in Celsius
        "expected_delay_sec": int  # rough heuristic delay in seconds due to weather
    }
"""

import logging
from typing import Any, Dict, Optional

import httpx

from config.settings import settings

logger = logging.getLogger(__name__)

# You can customize this base URL to your actual provider.
# Example assumes OpenWeatherMap-like API.
WEATHER_API_URL = "https://api.openweathermap.org/data/2.5/weather"

def _get_api_key() -> Optional[str]:
    api_key = getattr(settings, "WEATHER_API_KEY", None)
    if not api_key or api_key == "change_me_to_secure_value":
        return None
    return api_key

def _normalize_weather_response(data: Dict[str, Any]) -> Dict[str, Any]:
    """
    Convert raw provider JSON into a compact, agent-friendly schema.
    """
    condition = None
    description = None
    temp = None

    # Try to read main weather description
    try:
        weather_arr = data.get("weather") or []
        if weather_arr and isinstance(weather_arr, list):
            w0 = weather_arr[0] or {}
            condition = w0.get("main")
            description = w0.get("description")
    except Exception:
        pass

    # Try to read temperature in °C
    try:
        main = data.get("main") or {}
        t = main.get("temp")
        if t is not None:
            temp = float(t)
    except Exception:
        temp = None

    # Very rough heuristic for delay based on condition
    expected_delay_sec = 0
    cond_lower = (condition or "").lower()
    if any(k in cond_lower for k in ["rain", "thunder", "storm", "snow", "haze", "fog"]):
        expected_delay_sec = 5 * 60  # 5 minutes
    if any(k in cond_lower for k in ["heavy", "thunderstorm"]):
        expected_delay_sec = 15 * 60  # 15 minutes in very bad weather

    return {
        "condition": condition or "unknown",
        "description": description or "",
        "temp": temp,
        "expected_delay_sec": expected_delay_sec,
    }

def get_weather_by_coords(lat: float, lon: float) -> Dict[str, Any]:
    """
    Synchronous helper used by DecisionEngine and ExecutorAgent.

    Returns normalized weather dict for given coordinates, or a safe fallback on error.
    """
    api_key = _get_api_key()
    if not api_key:
        logger.warning("WEATHER_API_KEY not configured; returning dummy weather.")
        return {"condition": "unknown", "description": "", "temp": None, "expected_delay_sec": 0}

    params = {
        "lat": float(lat),
        "lon": float(lon),
        "appid": api_key,
        "units": "metric",  # Celsius
    }
    try:
        with httpx.Client(timeout=5.0) as client:
            resp = client.get(WEATHER_API_URL, params=params)
            resp.raise_for_status()
            data = resp.json()
            return _normalize_weather_response(data)
    except Exception as e:
        logger.error(f"get_weather_by_coords failed for ({lat},{lon}): {e}")
        return {"condition": "unknown", "description": "", "temp": None, "expected_delay_sec": 0}

def get_weather(city: str) -> Dict[str, Any]:
    """
    Fallback by city name; only used when coords are not available.
    """
    api_key = _get_api_key()
    if not api_key:
        logger.warning("WEATHER_API_KEY not configured; returning dummy weather.")
        return {"condition": "unknown", "description": "", "temp": None, "expected_delay_sec": 0}

    params = {
        "q": city,
        "appid": api_key,
        "units": "metric",
    }
    try:
        with httpx.Client(timeout=5.0) as client:
            resp = client.get(WEATHER_API_URL, params=params)
            resp.raise_for_status()
            data = resp.json()
            return _normalize_weather_response(data)
    except Exception as e:
        logger.error(f"get_weather failed for city={city}: {e}")
        return {"condition": "unknown", "description": "", "temp": None, "expected_delay_sec": 0}
