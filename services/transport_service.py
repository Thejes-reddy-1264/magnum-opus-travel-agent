"""
services/transport_service.py
Uses Google Distance Matrix API to calculate real distances & travel times
between two cities, then derives cost estimates for 4 modes of transport.

Modes: Bus | Cab | Bike Rental | Flight
"""

import logging
import requests

from config import GOOGLE_MAPS_API_KEY, GOOGLE_DISTANCE_MATRIX_URL

logger = logging.getLogger(__name__)

# Cost-per-km & speed estimates for each mode
_MODES = {
    "bus": {
        "label":    "Bus",
        "emoji":    "🚌",
        "color":    "#2196F3",
        "cost_per_km": 1.5,    # ₹ per km
        "speed_kmh":   50,     # avg km/h
        "min_cost":    80,
        "max_dist_km": 2000,   # buses don't cross oceans
        "note":        "State/private bus service",
    },
    "cab": {
        "label":    "Cab",
        "emoji":    "🚕",
        "color":    "#FF9800",
        "cost_per_km": 14,
        "speed_kmh":   65,
        "min_cost":    200,
        "max_dist_km": 800,    # cabs impractical beyond ~800km
        "note":        "Ola / Uber / local taxi",
    },
    "bike": {
        "label":    "Bike Rental",
        "emoji":    "🏍️",
        "color":    "#4CAF50",
        "cost_per_km": 4,
        "speed_kmh":   55,
        "min_cost":    150,
        "max_dist_km": 500,
        "note":        "Self-drive bike rental per day",
    },
    "flight": {
        "label":    "Flight",
        "emoji":    "✈️",
        "color":    "#9C27B0",
        "cost_per_km": 0,      # flight uses tier pricing
        "speed_kmh":   800,
        "min_cost":    2500,
        "max_dist_km": 20000,
        "note":        "Economy class estimate",
    },
}

# Flight fare tiers (₹) by distance buckets
_FLIGHT_TIERS = [
    (500,   3500,  6000),
    (1000,  5000,  9000),
    (2000,  7000,  14000),
    (5000,  10000, 20000),
    (10000, 15000, 35000),
    (99999, 25000, 60000),
]


def _flight_cost(distance_km: float) -> float:
    for limit, low, high in _FLIGHT_TIERS:
        if distance_km <= limit:
            return (low + high) / 2
    return 40000


def get_transport_options(source: str, destination: str, number_of_persons: int = 1) -> dict:
    """
    Returns transport options from source → destination.

    Args:
        source:            e.g. "Mumbai"
        destination:       e.g. "Goa"
        number_of_persons: used to multiply costs

    Returns:
        {
          "source": str,
          "destination": str,
          "distance_km": float,
          "distance_text": str,
          "options": [ { mode, label, emoji, color, estimated_cost, duration_text, note, available } ]
        }
    """
    distance_km, distance_text, duration_text_road = _get_distance_from_google(source, destination)

    if distance_km is None:
        # Fallback: rough inline estimate (100km if unknown)
        distance_km   = 100.0
        distance_text = "~100 km (estimated)"
        duration_text_road = "~2 hours"

    options = []
    for mode_key, meta in _MODES.items():
        available = distance_km <= meta["max_dist_km"]

        if mode_key == "flight":
            base_cost = _flight_cost(distance_km)
            duration_h = distance_km / meta["speed_kmh"] + 2  # +2h airport overhead
        else:
            base_cost  = max(meta["min_cost"], distance_km * meta["cost_per_km"])
            duration_h = distance_km / meta["speed_kmh"]

        # Per-person cost
        total_cost = round(base_cost * number_of_persons)

        # Format duration
        h = int(duration_h)
        m = int((duration_h - h) * 60)
        if h == 0:
            duration_str = f"{m} min"
        elif m == 0:
            duration_str = f"{h} hr"
        else:
            duration_str = f"{h} hr {m} min"

        options.append({
            "mode":            meta["label"],       # e.g. "Bus", "Cab", "Flight"
            "mode_key":        mode_key,             # e.g. "bus", "cab"
            "label":           meta["label"],
            "emoji":           meta["emoji"],
            "color":           meta["color"],
            "estimated_cost":  total_cost,
            "total_cost":      total_cost,           # alias for frontend
            "cost_per_person": round(base_cost),
            "duration_text":   duration_str,
            "note":            meta["note"],
            "available":       available,
        })

    return {
        "source":        source,
        "destination":   destination,
        "distance_km":   distance_km,
        "distance_text": distance_text,
        "persons":       number_of_persons,
        "options":       [o for o in options if o["available"]],  # only show available modes
    }


def _get_distance_from_google(origin: str, destination: str):
    """Call Google Distance Matrix API. Returns (km_float, text, duration_text)."""
    if not GOOGLE_MAPS_API_KEY:
        logger.warning("GOOGLE_MAPS_API_KEY not set — transport will use estimates.")
        return None, None, None

    try:
        resp = requests.get(
            GOOGLE_DISTANCE_MATRIX_URL,
            params={
                "origins":      origin,
                "destinations": destination,
                "units":        "metric",
                "key":          GOOGLE_MAPS_API_KEY,
            },
            timeout=8,
        )
        resp.raise_for_status()
        data = resp.json()

        row = data.get("rows", [{}])[0]
        element = row.get("elements", [{}])[0]

        if element.get("status") != "OK":
            logger.warning("Distance Matrix element status: %s", element.get("status"))
            return None, None, None

        dist_m   = element["distance"]["value"]   # metres
        dist_txt = element["distance"]["text"]
        dur_txt  = element["duration"]["text"]

        return round(dist_m / 1000, 1), dist_txt, dur_txt

    except Exception as exc:
        logger.exception("Google Distance Matrix API error: %s", exc)
        return None, None, None
