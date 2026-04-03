"""
app.py — Main Flask application entry point
AI Travel Recommendation Web App with JWT Authentication

Features:
  - User authentication (register, login, JWT-protected routes)
  - SQLite user database via SQLAlchemy
  - Multi-destination trip planning
  - Google Maps transport options
  - AI-powered restaurant recommendations
  - Razorpay payment integration
"""

import logging
import time
from datetime import timedelta

from flask import Flask, render_template, request, jsonify, g
from flask_jwt_extended import jwt_required, get_jwt_identity

from config import (
    FLASK_DEBUG, FLASK_PORT, SECRET_KEY,
    DB_URI, JWT_SECRET_KEY, JWT_ACCESS_TOKEN_EXPIRES,
    CITY_MAX_LEN, VALID_BUDGETS, VALID_INTERESTS, MAX_INTERESTS,
    MISTRAL_API_KEY, RAZORPAY_KEY_ID, RAZORPAY_KEY_SECRET
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
from services.transport_service import get_transport_options
from services.restaurant_service import get_restaurant_recommendations
from services.booking_service import create_payment_order, verify_payment_signature, save_booking
from services.cache import api_cache

logger = logging.getLogger(__name__)

# ── App initialisation ────────────────────────────────────────────────────────
app = Flask(__name__)
app.secret_key = SECRET_KEY

app.config["SQLALCHEMY_DATABASE_URI"]        = DB_URI
app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False
app.config["JWT_SECRET_KEY"]                 = JWT_SECRET_KEY
app.config["JWT_ACCESS_TOKEN_EXPIRES"]       = timedelta(seconds=JWT_ACCESS_TOKEN_EXPIRES)
app.config["JWT_TOKEN_LOCATION"]             = ["headers"]
app.config["JWT_HEADER_NAME"]                = "Authorization"
app.config["JWT_HEADER_TYPE"]                = "Bearer"

db.init_app(app)
bcrypt.init_app(app)
jwt.init_app(app)

app.register_blueprint(auth_bp)

with app.app_context():
    from models.user import User       # noqa
    from models.booking import Booking  # noqa
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


# ── Request lifecycle ─────────────────────────────────────────────────────────
@app.before_request
def _start_timer():
    g.start_time = time.monotonic()

@app.after_request
def _log_request(response):
    ms = round((time.monotonic() - g.get("start_time", time.monotonic())) * 1000)
    logger.info("%s %s → %d  (%dms)", request.method, request.path, response.status_code, ms)
    return response


# ── Pages ─────────────────────────────────────────────────────────────────────
@app.route("/")
def index():
    return render_template("index.html")


# ═════════════════════════════════════════════════════════════════════════════
# EXISTING: /api/recommend  (single-destination, unchanged)
# ═════════════════════════════════════════════════════════════════════════════
@app.route("/api/recommend", methods=["POST"])
@jwt_required()
def recommend():
    user_id = get_jwt_identity()
    body = request.get_json(silent=True)
    if not body:
        return jsonify({"error": "Request body must be valid JSON."}), 400

    city     = (body.get("city") or "").strip()
    budget   = (body.get("budget") or "mid-range").strip().lower()
    raw_ints = body.get("interests") or []

    try:
        number_of_days = max(1, min(int(body.get("number_of_days", 3)), 10))
    except (TypeError, ValueError):
        return jsonify({"error": "number_of_days must be 1–10."}), 400

    try:
        number_of_persons = max(1, min(int(body.get("number_of_persons", 1)), 50))
    except (TypeError, ValueError):
        return jsonify({"error": "number_of_persons must be 1–50."}), 400

    if not city:
        return jsonify({"error": "Please provide a city name."}), 400
    if len(city) > CITY_MAX_LEN:
        return jsonify({"error": f"City name must be {CITY_MAX_LEN} chars or fewer."}), 400
    if not city.replace(" ", "").replace(",", "").replace("-", "").isalpha():
        return jsonify({"error": "City name may only contain letters, spaces, commas, hyphens."}), 400
    if budget not in VALID_BUDGETS:
        return jsonify({"error": f"Invalid budget. Choose from: {', '.join(sorted(VALID_BUDGETS))}."}), 400
    if not isinstance(raw_ints, list):
        return jsonify({"error": "'interests' must be a list."}), 400
    if len(raw_ints) > MAX_INTERESTS:
        return jsonify({"error": f"Max {MAX_INTERESTS} interests allowed."}), 400

    interests = [i.strip().lower() for i in raw_ints if isinstance(i, str) and i.strip().lower() in VALID_INTERESTS]

    logger.info("recommend — user=%s city=%s days=%d persons=%d", user_id, city, number_of_days, number_of_persons)

    group_info       = classify_group(number_of_persons)
    cost_estimate    = calculate_trip_cost(budget, number_of_days, number_of_persons)
    group_activities = get_group_activity_suggestions(group_info["type"])

    weather_data = get_weather(city)
    hotel_data   = get_hotels(city, budget, interests)

    tips        = {}
    weather_rec = {}
    travel_plan = {}
    itinerary   = {}

    user_input = {
        "city": city, "budget": budget, "interests": interests,
        "number_of_days": number_of_days, "number_of_persons": number_of_persons,
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
            logger.exception("Recommendation engine error: %s", exc)
    else:
        logger.warning("Weather failed for '%s' — skipping AI outputs.", city)

    try:
        itinerary = generate_itinerary_with_mistral(user_input, weather_data)
    except Exception as exc:
        logger.exception("Itinerary generation failed: %s", exc)
        itinerary = _fallback_itinerary(city, budget, interests, _weather_str(), number_of_days)

    if not itinerary or not itinerary.get("days"):
        itinerary = _fallback_itinerary(city, budget, interests, _weather_str(), number_of_days)

    # Always fetch restaurants for the destination
    try:
        cuisine_pref = ""
        if "food" in interests:
            cuisine_pref = "local"
        restaurant_data = get_restaurant_recommendations(city, budget, cuisine_pref, number_of_persons)
        restaurants = restaurant_data.get("restaurants", [])
    except Exception as exc:
        logger.exception("Restaurant fetch failed: %s", exc)
        restaurants = []

    return jsonify({
        "city": city, "budget": budget, "interests": interests,
        "weather": weather_data, "hotels": hotel_data,
        "tips": tips, "weather_rec": weather_rec, "travel_plan": travel_plan,
        "itinerary": itinerary, "group_info": group_info,
        "cost_estimate": cost_estimate, "group_activities": group_activities,
        "restaurants": restaurants,
        "number_of_days": number_of_days, "number_of_persons": number_of_persons,
    })


# ═════════════════════════════════════════════════════════════════════════════
# NEW: /api/plan-trip  — multi-destination full plan
# ═════════════════════════════════════════════════════════════════════════════
@app.route("/api/plan-trip", methods=["POST"])
@jwt_required()
def plan_trip():
    """
    Multi-destination trip planner.
    Body: { source, destinations:[str], number_of_days, number_of_persons, budget, interests, cuisine }
    """
    user_id = get_jwt_identity()
    body    = request.get_json(silent=True) or {}

    source       = (body.get("source") or "").strip()
    destinations = body.get("destinations") or []
    budget       = (body.get("budget") or "mid-range").strip().lower()
    cuisine      = (body.get("cuisine") or "").strip()
    raw_ints     = body.get("interests") or []

    try:
        number_of_days = max(1, min(int(body.get("number_of_days", 3)), 14))
    except (TypeError, ValueError):
        return jsonify({"error": "number_of_days must be 1–14."}), 400
    try:
        number_of_persons = max(1, min(int(body.get("number_of_persons", 1)), 50))
    except (TypeError, ValueError):
        return jsonify({"error": "number_of_persons must be 1–50."}), 400

    if not isinstance(destinations, list) or not destinations:
        return jsonify({"error": "Please provide at least one destination."}), 400
    if len(destinations) > 3:
        return jsonify({"error": "Maximum 3 destinations supported."}), 400
    if budget not in VALID_BUDGETS:
        budget = "mid-range"

    interests = [i.strip().lower() for i in raw_ints if isinstance(i, str) and i.strip().lower() in VALID_INTERESTS]
    primary   = destinations[0]

    logger.info("plan-trip — user=%s  %s → %s  days=%d persons=%d",
                user_id, source or primary, "→".join(destinations), number_of_days, number_of_persons)

    # Transport legs — only compute if source provided or multiple destinations
    all_stops      = ([source] if source else []) + destinations
    transport_legs = []
    if len(all_stops) >= 2:
        for i in range(len(all_stops) - 1):
            try:
                leg = get_transport_options(all_stops[i], all_stops[i + 1], number_of_persons)
                transport_legs.append(leg)
            except Exception as exc:
                logger.exception("Transport leg %s→%s failed: %s", all_stops[i], all_stops[i+1], exc)
                transport_legs.append({"error": f"Could not fetch transport for {all_stops[i]} → {all_stops[i+1]}"})

    hotel_data   = get_hotels(primary, budget, interests)
    weather_data = get_weather(primary)

    user_input = {
        "city": primary, "source": source, "destinations": destinations,
        "budget": budget, "interests": interests,
        "number_of_days": number_of_days, "number_of_persons": number_of_persons,
    }

    def _weather_str():
        if "error" not in weather_data:
            return "{} — {}C".format(weather_data.get("description", "?"), weather_data.get("temperature", "?"))
        return "unknown conditions"

    try:
        itinerary = generate_itinerary_with_mistral(user_input, weather_data)
    except Exception as exc:
        logger.exception("plan-trip itinerary failed: %s", exc)
        itinerary = _fallback_itinerary(primary, budget, interests, _weather_str(), number_of_days)

    if not itinerary or not itinerary.get("days"):
        itinerary = _fallback_itinerary(primary, budget, interests, _weather_str(), number_of_days)

    restaurant_data = get_restaurant_recommendations(primary, budget, cuisine, number_of_persons)
    group_info      = classify_group(number_of_persons)
    cost_estimate   = calculate_trip_cost(budget, number_of_days, number_of_persons)

    return jsonify({
        "source": source, "destinations": destinations,
        "number_of_days": number_of_days, "number_of_persons": number_of_persons,
        "budget": budget, "weather": weather_data,
        "transport_legs": transport_legs, "hotels": hotel_data,
        "restaurants": restaurant_data.get("restaurants", []),
        "itinerary": itinerary, "group_info": group_info, "cost_estimate": cost_estimate,
    })


# ═════════════════════════════════════════════════════════════════════════════
# NEW: /api/get-transport-options
# ═════════════════════════════════════════════════════════════════════════════
@app.route("/api/get-transport-options", methods=["POST"])
@jwt_required()
def get_transport():
    body        = request.get_json(silent=True) or {}
    source      = (body.get("source") or "").strip()
    destination = (body.get("destination") or "").strip()

    try:
        persons = max(1, min(int(body.get("number_of_persons", 1)), 50))
    except (TypeError, ValueError):
        persons = 1

    if not source or not destination:
        return jsonify({"error": "Both 'source' and 'destination' are required."}), 400

    return jsonify(get_transport_options(source, destination, persons))


# ═════════════════════════════════════════════════════════════════════════════
# NEW: /api/get-restaurants
# ═════════════════════════════════════════════════════════════════════════════
@app.route("/api/get-restaurants", methods=["POST"])
@jwt_required()
def get_restaurants():
    body        = request.get_json(silent=True) or {}
    destination = (body.get("destination") or "").strip()
    budget      = (body.get("budget") or "mid-range").strip().lower()
    cuisine     = (body.get("cuisine") or "").strip()

    try:
        persons = max(1, min(int(body.get("number_of_persons", 1)), 50))
    except (TypeError, ValueError):
        persons = 1

    if not destination:
        return jsonify({"error": "'destination' is required."}), 400
    if budget not in VALID_BUDGETS:
        budget = "mid-range"

    return jsonify(get_restaurant_recommendations(destination, budget, cuisine, persons))



# ═════════════════════════════════════════════════════════════════════════════
# NEW: /api/simulate-payment  — saves booking without Razorpay (for demo/dev)
# ═════════════════════════════════════════════════════════════════════════════
@app.route("/api/simulate-payment", methods=["POST"])
@jwt_required()
def simulate_payment():
    """
    Simulates a successful payment and saves the booking record directly.
    Used when Razorpay live keys are not available / payment gateway is in demo mode.
    """
    user_id = get_jwt_identity()
    body    = request.get_json(silent=True) or {}

    try:
        amount_inr = float(body.get("amount_inr", 0))
        if amount_inr <= 0:
            raise ValueError("Amount must be positive")
    except (TypeError, ValueError) as exc:
        return jsonify({"error": f"Invalid amount: {exc}"}), 400

    booking_type = str(body.get("booking_type") or "general").strip()
    destination  = str(body.get("destination") or "").strip()
    details      = body.get("details") or {}

    import uuid
    simulated_payment_id = "sim_" + uuid.uuid4().hex[:16].upper()
    simulated_order_id   = "ord_" + uuid.uuid4().hex[:16].upper()

    from models.booking import Booking
    try:
        summary = save_booking(
            db_session   = db.session,
            BookingModel = Booking,
            user_id      = user_id,
            booking_type = booking_type,
            destination  = destination,
            amount_inr   = amount_inr,
            payment_id   = simulated_payment_id,
            order_id     = simulated_order_id,
            details      = details,
        )
    except Exception as exc:
        logger.exception("simulate_payment save failed: %s", exc)
        return jsonify({"error": "Could not save booking."}), 500

    return jsonify({"status": "confirmed", "booking": summary})


# ═════════════════════════════════════════════════════════════════════════════
# NEW: /api/create-payment-order  (Razorpay)
# ═════════════════════════════════════════════════════════════════════════════
@app.route("/api/create-payment-order", methods=["POST"])
@jwt_required()
def create_order():
    body = request.get_json(silent=True) or {}

    try:
        amount_inr = float(body.get("amount_inr", 0))
        if amount_inr <= 0:
            raise ValueError("Amount must be positive")
    except (TypeError, ValueError) as exc:
        return jsonify({"error": f"Invalid amount: {exc}"}), 400

    booking_type = str(body.get("booking_type") or "general").strip()
    description  = str(body.get("description") or "TripSense Booking").strip()

    try:
        result = create_payment_order(amount_inr, booking_type, description)
        # Ensure frontend-expected field 'razorpay_order_id' is present
        result["razorpay_order_id"] = result.get("order_id", "")
        return jsonify(result)
    except RuntimeError as exc:
        logger.warning("Razorpay order creation failed: %s", exc)
        return jsonify({"error": str(exc)}), 503
    except Exception as exc:
        logger.exception("Razorpay order creation error: %s", exc)
        return jsonify({"error": "Payment service unavailable."}), 503


# ═════════════════════════════════════════════════════════════════════════════
# NEW: /api/verify-payment  (Razorpay)
# ═════════════════════════════════════════════════════════════════════════════
@app.route("/api/verify-payment", methods=["POST"])
@jwt_required()
def verify_payment():
    user_id = get_jwt_identity()
    body    = request.get_json(silent=True) or {}

    order_id   = str(body.get("razorpay_order_id") or "")
    payment_id = str(body.get("razorpay_payment_id") or "")
    signature  = str(body.get("razorpay_signature") or "")

    if not order_id or not payment_id or not signature:
        return jsonify({"error": "Missing payment verification fields."}), 400

    if not verify_payment_signature(order_id, payment_id, signature):
        logger.warning("Invalid Razorpay signature — user=%s order=%s", user_id, order_id)
        return jsonify({"error": "Payment verification failed. Signature mismatch."}), 400

    from models.booking import Booking
    summary = save_booking(
        db_session   = db.session,
        BookingModel = Booking,
        user_id      = user_id,
        booking_type = str(body.get("booking_type") or "general"),
        destination  = str(body.get("destination") or ""),
        amount_inr   = float(body.get("amount_inr") or 0),
        payment_id   = payment_id,
        order_id     = order_id,
        details      = body.get("details") or {},
    )
    return jsonify({"status": "confirmed", "booking": summary})


# ═════════════════════════════════════════════════════════════════════════════
# NEW: /api/my-bookings
# ═════════════════════════════════════════════════════════════════════════════
@app.route("/api/my-bookings", methods=["GET"])
@jwt_required()
def my_bookings():
    user_id = get_jwt_identity()
    from models.booking import Booking
    bookings = Booking.query.filter_by(user_id=user_id).order_by(Booking.created_at.desc()).all()
    return jsonify({"bookings": [b.to_dict() for b in bookings]})


# ── Utility routes ────────────────────────────────────────────────────────────
@app.route("/api/health")
def health():
    return jsonify({"status": "ok", "service": "TripSense AI", "cache": api_cache.stats()})

@app.route("/api/cache/clear", methods=["POST"])
def clear_cache():
    api_cache.clear()
    return jsonify({"status": "ok", "message": "Cache cleared."})


# ── Error handlers ────────────────────────────────────────────────────────────
@app.errorhandler(404)
def not_found(_err):
    if request.path.startswith("/api/"):
        return jsonify({"error": "Endpoint not found."}), 404
    return render_template("index.html"), 404


# ═════════════════════════════════════════════════════════════════════════════
# /api/chat  — AI Travel Chatbot (Mistral)
# ═════════════════════════════════════════════════════════════════════════════
@app.route("/api/chat", methods=["POST"])
def chat():
    """
    Travel chatbot powered by Mistral AI.
    Accepts: { "message": str, "history": [ {"role": "user"|"assistant", "content": str} ] }
    Returns: { "reply": str }
    No JWT required — chatbot is publicly accessible.
    """
    body    = request.get_json(silent=True) or {}
    message = str(body.get("message") or "").strip()
    history = body.get("history") or []

    if not message:
        return jsonify({"error": "Message is required."}), 400

    # Clamp history to last 10 turns to keep prompt size reasonable
    history = history[-10:]

    SYSTEM_PROMPT = (
        "You are TripSense AI — a friendly, knowledgeable travel assistant. "
        "You help users plan trips, discover destinations, find hotels, "
        "understand visa requirements, suggest packing lists, estimate budgets, "
        "recommend restaurants, and give culture/weather tips. "
        "Keep answers concise, friendly and practical. "
        "Use emojis sparingly for personality. "
        "If a question is completely unrelated to travel, gently redirect to travel topics. "
        "Always respond in the same language the user writes in."
    )

    messages = [{"role": "system", "content": SYSTEM_PROMPT}]
    for turn in history:
        role = turn.get("role", "user")
        content = str(turn.get("content", "")).strip()
        if role in ("user", "assistant") and content:
            messages.append({"role": role, "content": content})
    messages.append({"role": "user", "content": message})

    import requests as _req
    try:
        resp = _req.post(
            "https://api.mistral.ai/v1/chat/completions",
            headers={
                "Authorization": f"Bearer {MISTRAL_API_KEY}",
                "Content-Type": "application/json",
            },
            json={
                "model":       "mistral-small-latest",
                "messages":    messages,
                "max_tokens":  600,
                "temperature": 0.7,
            },
            timeout=(4, 25),
        )
        resp.raise_for_status()
        reply = resp.json()["choices"][0]["message"]["content"].strip()
        return jsonify({"reply": reply})

    except Exception as exc:
        logger.warning("Chatbot Mistral error: %s", exc)
        # Friendly fallback
        return jsonify({
            "reply": (
                "I'm having a little trouble connecting right now 🛠️ "
                "Please try again in a moment, or ask me something else about your trip!"
            )
        })


@app.errorhandler(405)
def method_not_allowed(_err):
    return jsonify({"error": "Method not allowed."}), 405

@app.errorhandler(500)
def internal_error(err):
    logger.exception("Unhandled 500: %s", err)
    if request.path.startswith("/api/"):
        return jsonify({"error": "Internal server error."}), 500
    return render_template("index.html"), 500


# ── Entry point ───────────────────────────────────────────────────────────────
if __name__ == "__main__":
    print(f"\n🌍  TripSense running at http://127.0.0.1:{FLASK_PORT}\n")
    app.run(debug=FLASK_DEBUG, port=FLASK_PORT)
