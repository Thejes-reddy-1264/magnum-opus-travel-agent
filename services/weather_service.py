"""
services/weather_service.py
Handles all communication with the OpenWeatherMap API.

Changes for production:
  - Structured logging at every decision point
  - TTL-based in-memory caching (key = "weather:<city_lower>")
  - Explicit timeout + retry-on-timeout (one retry)
  - Detailed HTTP error codes mapped to user-friendly messages
"""

import logging
import requests

from config import (
    OPENWEATHER_API_KEY,
    OPENWEATHER_BASE_URL,
    CACHE_TTL_WEATHER,
)
from services.cache import api_cache

logger = logging.getLogger(__name__)

# Request timeout: (connect_timeout, read_timeout) in seconds
_TIMEOUT = (5, 10)


def get_weather(city: str) -> dict:
    """
    Fetch current weather data for a city from OpenWeatherMap.

    Results are cached for CACHE_TTL_WEATHER seconds (default 10 min).
    A single automatic retry is attempted on timeout.

    Args:
        city (str): City name (may include country code, e.g. "London,UK").

    Returns:
        dict: Structured weather payload, or {"error": "<message>"} on failure.
    """
    if not OPENWEATHER_API_KEY:
        logger.error("OPENWEATHER_API_KEY is not configured.")
        return {"error": "Weather service is not configured. Contact the administrator."}

    city_normalised = city.strip().lower()
    cache_key = f"weather:{city_normalised}"

    # ── Cache hit ─────────────────────────────────────────────────────────────
    cached = api_cache.get(cache_key)
    if cached is not None:
        logger.info("Weather cache HIT for '%s'", city)
        return cached

    params = {
        "q":     city,
        "appid": OPENWEATHER_API_KEY,
        "units": "metric",
    }

    logger.info("Fetching weather for '%s' from OpenWeatherMap…", city)

    # ── Request with one retry on timeout ─────────────────────────────────────
    for attempt in range(1, 3):
        try:
            response = requests.get(
                OPENWEATHER_BASE_URL,
                params=params,
                timeout=_TIMEOUT,
            )
            response.raise_for_status()
            break  # success

        except requests.exceptions.Timeout:
            if attempt == 1:
                logger.warning("Weather API timeout for '%s' — retrying (attempt %d)…", city, attempt + 1)
                continue
            logger.error("Weather API timeout after retry for '%s'.", city)
            return {"error": "Weather service timed out. Please try again."}

        except requests.exceptions.HTTPError:
            status = response.status_code
            logger.warning("Weather API HTTP %d for city='%s'", status, city)
            if status == 404:
                return {"error": f"City '{city}' not found. Please check the spelling."}
            if status == 401:
                return {"error": "Weather API key is invalid. Contact the administrator."}
            if status == 429:
                return {"error": "Weather API rate limit reached. Please try again shortly."}
            return {"error": f"Weather service error ({status}). Please try again."}

        except requests.exceptions.ConnectionError:
            logger.error("Cannot reach OpenWeatherMap API (connection error).")
            return {"error": "Cannot connect to the weather service. Check your network."}

        except Exception as exc:
            logger.exception("Unexpected error in get_weather for '%s': %s", city, exc)
            return {"error": "An unexpected error occurred fetching weather data."}

    # ── Parse response ─────────────────────────────────────────────────────────
    try:
        data = response.json()
        result = {
            "city":        data["name"],
            "country":     data["sys"]["country"],
            "temperature": round(data["main"]["temp"], 1),
            "feels_like":  round(data["main"]["feels_like"], 1),
            "humidity":    data["main"]["humidity"],
            "description": data["weather"][0]["description"].title(),
            "icon":        data["weather"][0]["icon"],
            "wind_speed":  round(data["wind"]["speed"], 1),
        }
    except (KeyError, IndexError, ValueError) as exc:
        logger.error("Failed to parse weather response for '%s': %s", city, exc)
        return {"error": "Received an unexpected response from the weather service."}

    # ── Cache and return ───────────────────────────────────────────────────────
    api_cache.set(cache_key, result, ttl=CACHE_TTL_WEATHER)
    logger.info(
        "Weather fetched: %s, %s — %.1f°C, %s",
        result["city"], result["country"], result["temperature"], result["description"],
    )
    return result
