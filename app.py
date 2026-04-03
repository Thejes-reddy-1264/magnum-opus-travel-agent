"""
app.py — Main Flask application entry point
AI Travel Recommendation Web App with JWT Authentication

Production features:
  - User authentication (register, login, JWT-protected routes)
  - SQLite user database via SQLAlchemy
  - Structured logging with per-request timing
  - Strict input validation (city length, budget whitelist, interest whitelist)
  - Global error handlers (404, 405, 500)
  - Enhanced /api/health endpoint with cache stats
  - Graceful degradation: travel plan/itinerary still generated even if hotels fail
"""

import logging
import time
from datetime import timedelta

from flask import Flask, render_template, request, jsonify, g
from flask_jwt_extended import jwt_required, get_jwt_identity, verify_jwt_in_request

from config import (
    FLASK_DEBUG, FLASK_PORT, SECRET_KEY,
    DB_URI, JWT_SECRET_KEY, JWT_ACCESS_TOKEN_EXPIRES,
    CITY_MAX_LEN, VALID_BUDGETS, VALID_INTERESTS, MAX_INTERESTS,
)
from database import db
from extensions import bcrypt, jwt
from auth.routes import auth_bp
from services.weather_service import get_weather
from services.hotel_service import get_hotels
from services.recommendation_service import get_recommendations, generate_weather_recommendation
from services.travel_plan_service import generate_travel_plan, generate_itinerary
from services.mistral_service import generate_itinerary_with_mistral, _fallback_itinerary
from services.cost_service import calculate_trip_cost, classify_group, get_group_activity_suggestions
from services.cache import api_cache

logger = logging.getLogger(__name__)

# ── App initialisation ────────────────────────────────────────────────────────
app = Flask(__name__)
app.secret_key = SECRET_KEY

# Database
app.config["SQLALCHEMY_DATABASE_URI"]        = DB_URI
app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False

# JWT
app.config["JWT_SECRET_KEY"]       = JWT_SECRET_KEY
app.config["JWT_ACCESS_TOKEN_EXPIRES"] = timedelta(seconds=JWT_ACCESS_TOKEN_EXPIRES)
app.config["JWT_TOKEN_LOCATION"]   = ["headers"]
app.config["JWT_HEADER_NAME"]      = "Authorization"
app.config["JWT_HEADER_TYPE"]      = "Bearer"

# Init extensions
db.init_app(app)
bcrypt.init_app(app)
jwt.init_app(app)

# Register blueprints
app.register_blueprint(auth_bp)

# Create tables on first run
with app.app_context():
    from models.user import User  # noqa: ensure model is registered
    db.create_all()
    logger.info("Database tables created/verified.")


# ── JWT error handlers ────────────────────────────────────────────────────────
@jwt.unauthorized_loader
def missing_token(_reason):
    return jsonify({"error": "Authentication required. Please log in."}), 401

@jwt.invalid_token_loader
def invalid_token(_reason):
    return jsonify({"error": "Invalid token. Please log in again."}), 401

@jwt.expired_token_loader
def expired_token(_header, _payload):
    return jsonify({"error": "Your session has expired. Please log in again."}), 401


# ── Request lifecycle hooks ───────────────────────────────────────────────────
@app.before_request
def _start_timer():
    g.start_time = time.monotonic()


@app.after_request
def _log_request(response):
    elapsed_ms = round((time.monotonic() - g.get("start_time", time.monotonic())) * 1000)
    logger.info(
        "%s %s → %d  (%dms)",
        request.method, request.path, response.status_code, elapsed_ms,
    )
    return response


# ── Routes ────────────────────────────────────────────────────────────────────

@app.route("/")
def index():
    """Serve the main single-page application."""
    return render_template("index.html")


@app.route("/api/recommend", methods=["POST"])
@jwt_required()
def recommend():
    """
    POST /api/recommend
    Protected: requires a valid JWT Bearer token.
    Accepts JSON: {
      "city":              str,
      "budget":            str,
      "interests":         [str],
      "number_of_days":    int  (1-10, default 3),
      "number_of_persons": int  (1-50, default 1)
    }
    Returns combined weather + hotels + AI recommendations + cost breakdown.
    """
    user_id = get_jwt_identity()

    body = request.get_json(silent=True)
    if not body:
        logger.warning("POST /api/recommend — missing or non-JSON body.")
        return jsonify({"error": "Request body must be valid JSON."}), 400

    # ── Input extraction & sanitisation ───────────────────────────────────────────────
    city      = (body.get("city") or "").strip()
    budget    = (body.get("budget") or "mid-range").strip().lower()
    raw_ints  = body.get("interests") or []

    # New trip-customisation fields
    try:
        number_of_days    = max(1, min(int(body.get("number_of_days",    3)), 10))
    except (TypeError, ValueError):
        return jsonify({"error": "number_of_days must be an integer between 1 and 10."}), 400

    try:
        number_of_persons = max(1, min(int(body.get("number_of_persons", 1)), 50))
    except (TypeError, ValueError):
        return jsonify({"error": "number_of_persons must be an integer between 1 and 50."}), 400

    # ── Validation ────────────────────────────────────────────────────────────────────────
    if not city:
        return jsonify({"error": "Please provide a city name."}), 400

    if len(city) > CITY_MAX_LEN:
        return jsonify({"error": f"City name must be {CITY_MAX_LEN} characters or fewer."}), 400

    if not city.replace(" ", "").replace(",", "").replace("-", "").isalpha():
        return jsonify({"error": "City name may only contain letters, spaces, commas, and hyphens."}), 400

    if budget not in VALID_BUDGETS:
        return jsonify({
            "error": f"Invalid budget '{budget}'. Choose from: {', '.join(sorted(VALID_BUDGETS))}."
        }), 400

    if not isinstance(raw_ints, list):
        return jsonify({"error": "'interests' must be a list."}), 400

    if len(raw_ints) > MAX_INTERESTS:
        return jsonify({"error": f"You may select at most {MAX_INTERESTS} interests."}), 400

    interests = [i.strip().lower() for i in raw_ints if isinstance(i, str)]
    interests = [i for i in interests if i in VALID_INTERESTS]

    logger.info(
        "Recommendation request — user=%s city='%s' budget='%s' days=%d persons=%d interests=%s",
        user_id, city, budget, number_of_days, number_of_persons, interests
    )

    # ── Group classification & cost ───────────────────────────────────────────────────
    group_info     = classify_group(number_of_persons)
    cost_estimate  = calculate_trip_cost(budget, number_of_days, number_of_persons)
    group_activities = get_group_activity_suggestions(group_info["type"])

    # ── Fetch data ───────────────────────────────────────────────────────────────────────
    weather_data = get_weather(city)
    hotel_data   = get_hotels(city, budget, interests)

    tips        = {}
    weather_rec = {}
    travel_plan = {}
    itinerary   = {}

    user_input  = {
        "city":             city,
        "budget":           budget,
        "interests":        interests,
        "number_of_days":   number_of_days,
        "number_of_persons": number_of_persons,
    }

    def _weather_str():
        if "error" not in weather_data:
            return "{} — {}C, humidity {}%".format(
                weather_data.get("description", "unknown"),
                weather_data.get("temperature", "?"),
                weather_data.get("humidity", "?"),
            )
        return "unknown conditions"

    if "error" not in weather_data:
        try:
            tips        = get_recommendations(weather_data, interests, budget)
            weather_rec = generate_weather_recommendation(weather_data)
            hotel_list  = hotel_data.get("hotels", []) if "error" not in hotel_data else []
            travel_plan = generate_travel_plan(user_input, weather_data, hotel_list)
        except Exception as exc:
            logger.exception("AI recommendation engine error for city='%s': %s", city, exc)
    else:
        logger.warning("Skipping AI outputs — weather fetch failed for '%s'.", city)

    # Itinerary — always generated (Mistral with internal fallback)
    try:
        itinerary = generate_itinerary_with_mistral(user_input, weather_data)
    except Exception as itin_exc:
        logger.exception("Itinerary generation failed for '%s': %s", city, itin_exc)
        itinerary = _fallback_itinerary(city, budget, interests, _weather_str(), number_of_days)

    if not itinerary or not itinerary.get("days"):
        itinerary = _fallback_itinerary(city, budget, interests, _weather_str())

    return jsonify({
        "city":        city,
        "budget":      budget,
        "interests":   interests,
        "weather":     weather_data,
        "hotels":      hotel_data,
        "tips":        tips,
        "weather_rec": weather_rec,
        "travel_plan": travel_plan,
        "itinerary":   itinerary,
    })


@app.route("/api/health")
def health():
    """GET /api/health — service status and cache statistics."""
    return jsonify({
        "status":  "ok",
        "service": "TripSense AI Travel Recommender",
        "cache":   api_cache.stats(),
    })


@app.route("/api/cache/clear", methods=["POST"])
def clear_cache():
    """POST /api/cache/clear — flush in-memory cache."""
    api_cache.clear()
    logger.info("Cache cleared via /api/cache/clear endpoint.")
    return jsonify({"status": "ok", "message": "Cache cleared."})


# ── Global error handlers ─────────────────────────────────────────────────────
@app.errorhandler(404)
def not_found(_err):
    if request.path.startswith("/api/"):
        return jsonify({"error": "Endpoint not found."}), 404
    return render_template("index.html"), 404


@app.errorhandler(405)
def method_not_allowed(_err):
    return jsonify({"error": "Method not allowed."}), 405


@app.errorhandler(500)
def internal_error(err):
    logger.exception("Unhandled 500 error: %s", err)
    if request.path.startswith("/api/"):
        return jsonify({"error": "An internal server error occurred."}), 500
    return render_template("index.html"), 500


# ── Entry point ───────────────────────────────────────────────────────────────
if __name__ == "__main__":
    print(f"\n🌍  TripSense running at http://127.0.0.1:{FLASK_PORT}\n")
    app.run(debug=FLASK_DEBUG, port=FLASK_PORT)
