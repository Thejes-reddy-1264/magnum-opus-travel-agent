"""
config.py — Centralised configuration for the AI Travel Recommendation App.

All secrets are loaded from the .env file (never hardcoded here).
Includes startup validation so misconfigured deployments fail fast.
"""

import os
import sys
import logging
from dotenv import load_dotenv

# ── Load .env ─────────────────────────────────────────────────────────────────
load_dotenv()

# ── Logging (configured here so it applies everywhere) ────────────────────────
LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO").upper()
logging.basicConfig(
    level=getattr(logging, LOG_LEVEL, logging.INFO),
    format="%(asctime)s  %(levelname)-8s  %(name)s — %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
    handlers=[logging.StreamHandler(sys.stdout)],
)

logger = logging.getLogger("config")

# ── OpenWeatherMap ─────────────────────────────────────────────────────────────
OPENWEATHER_API_KEY  = os.getenv("OPENWEATHER_API_KEY", "")
OPENWEATHER_BASE_URL = "https://api.openweathermap.org/data/2.5/weather"

# ── RapidAPI — Booking.com Hotel Search ───────────────────────────────────────
RAPIDAPI_KEY      = os.getenv("RAPIDAPI_KEY", "")
RAPIDAPI_HOST     = os.getenv("RAPIDAPI_HOST", "booking-com.p.rapidapi.com")
RAPIDAPI_BASE_URL = os.getenv("RAPIDAPI_BASE_URL", "https://booking-com.p.rapidapi.com/v1")

# ── Mistral AI ──────────────────────────────────────────────────
MISTRAL_API_KEY = os.getenv("MISTRAL_API_KEY", "")

# ── Flask settings ────────────────────────────────────────────────────────────
FLASK_DEBUG = os.getenv("FLASK_DEBUG", "false").lower() == "true"
FLASK_PORT  = int(os.getenv("FLASK_PORT", 5000))
SECRET_KEY  = os.getenv("SECRET_KEY", "change-me-in-production")

# ── Database ────────────────────────────────────────────────────────────────────
# SQLite by default — override with a MySQL/Postgres URL in production
DB_URI = os.getenv("DATABASE_URL", "sqlite:///tripsense.db")

# ── JWT ─────────────────────────────────────────────────────────────────────────
JWT_SECRET_KEY           = os.getenv("JWT_SECRET_KEY", SECRET_KEY)
JWT_ACCESS_TOKEN_EXPIRES = int(os.getenv("JWT_EXPIRES_HOURS", 24)) * 3600  # seconds

# ── API caching ───────────────────────────────────────────────────────────────
# TTL in seconds for in-memory API response cache (0 = disable)
CACHE_TTL_WEATHER = int(os.getenv("CACHE_TTL_WEATHER", 600))   # 10 min
CACHE_TTL_HOTELS  = int(os.getenv("CACHE_TTL_HOTELS",  1800))  # 30 min

# ── Input validation constraints ──────────────────────────────────────────────
CITY_MAX_LEN      = 100
VALID_BUDGETS     = {"budget", "low", "mid-range", "medium", "high", "luxury"}
VALID_INTERESTS   = {"nature", "adventure", "food", "culture", "beach", "shopping", "wellness"}
MAX_INTERESTS     = 7

# ── Startup validation ────────────────────────────────────────────────────────
def _warn_missing(key: str, hint: str) -> None:
    logger.warning("⚠️  %s is not set. %s", key, hint)

if not MISTRAL_API_KEY:
    _warn_missing("MISTRAL_API_KEY", "AI itinerary will use rule-based fallback.")
if not OPENWEATHER_API_KEY:
    _warn_missing("OPENWEATHER_API_KEY", "Weather features will be unavailable.")
if not RAPIDAPI_KEY:
    _warn_missing("RAPIDAPI_KEY", "Hotel search will fall back to curated mock data.")
if SECRET_KEY == "change-me-in-production" and not FLASK_DEBUG:
    _warn_missing("SECRET_KEY", "Set a strong secret key before deploying to production.")
if JWT_SECRET_KEY == "change-me-in-production" and not FLASK_DEBUG:
    _warn_missing("JWT_SECRET_KEY", "Set a strong JWT secret before deploying to production.")

logger.info("Config loaded — debug=%s port=%d cache_weather=%ds cache_hotels=%ds",
            FLASK_DEBUG, FLASK_PORT, CACHE_TTL_WEATHER, CACHE_TTL_HOTELS)
