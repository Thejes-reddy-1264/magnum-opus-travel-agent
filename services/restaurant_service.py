"""
services/restaurant_service.py
Uses Mistral AI to generate curated restaurant recommendations for a destination.

Returns structured restaurant data with name, cuisine, price range, rating,
highlights, and a "best for" meal tag (breakfast/lunch/dinner).
"""

import json
import logging
import re
import requests

from config import MISTRAL_API_KEY

logger = logging.getLogger(__name__)

MISTRAL_API_URL = "https://api.mistral.ai/v1/chat/completions"
MISTRAL_MODEL   = "mistral-small-latest"
MISTRAL_TIMEOUT = (5, 30)

_BUDGET_LABELS = {
    "budget":    "cheap local eateries under ₹200 per person",
    "low":       "affordable restaurants under ₹300 per person",
    "mid-range": "mid-range restaurants ₹300–₹800 per person",
    "medium":    "mid-range restaurants ₹300–₹800 per person",
    "high":      "premium restaurants ₹800–₹2000 per person",
    "luxury":    "fine dining restaurants above ₹2000 per person",
}


def get_restaurant_recommendations(
    destination: str,
    budget: str = "mid-range",
    cuisine_preference: str = "",
    number_of_persons: int = 1,
) -> dict:
    """
    Use Mistral AI to get restaurant recommendations for a destination.

    Returns:
        {
          "destination": str,
          "restaurants": [
            {
              "name":        str,
              "cuisine":     str,
              "price_range": str,
              "rating":      float,
              "highlights":  [str],
              "best_for":    str,   # "breakfast" | "lunch" | "dinner" | "all day"
              "address":     str,
              "distance_from_centre": str,
            }
          ]
        }
    """
    budget_label = _BUDGET_LABELS.get(budget, _BUDGET_LABELS["mid-range"])
    cuisine_hint = f"Prefer {cuisine_preference} cuisine." if cuisine_preference else "Mix of local and popular cuisines."

    prompt = f"""You are a knowledgeable travel food guide. Recommend exactly 6 real restaurants in {destination} for {number_of_persons} {"person" if number_of_persons == 1 else "people"}.

Budget level: {budget_label}
Cuisine preference: {cuisine_hint}

Return ONLY a valid JSON array (no markdown, no explanation) with this exact structure:
[
  {{
    "name": "Restaurant Name",
    "cuisine": "Cuisine Type",
    "price_range": "₹200–₹400 per person",
    "rating": 4.3,
    "highlights": ["Specialty dish 1", "Feature 2", "Feature 3"],
    "best_for": "lunch",
    "address": "Area / locality name",
    "distance_from_centre": "1.2 km from city centre"
  }}
]

Rules:
- Use real, well-known restaurants in {destination} if possible
- Mix breakfast, lunch, and dinner options across the 6 restaurants
- best_for must be one of: "breakfast", "lunch", "dinner", "all day"
- rating must be between 3.5 and 5.0
- Keep it concise and realistic"""

    try:
        response = requests.post(
            MISTRAL_API_URL,
            headers={
                "Authorization": f"Bearer {MISTRAL_API_KEY}",
                "Content-Type":  "application/json",
            },
            json={
                "model":       MISTRAL_MODEL,
                "messages":    [{"role": "user", "content": prompt}],
                "max_tokens":  1200,
                "temperature": 0.4,
            },
            timeout=MISTRAL_TIMEOUT,
        )
        response.raise_for_status()
        raw = response.json()["choices"][0]["message"]["content"].strip()

        # Strip markdown fences if present
        raw = re.sub(r"^```[a-z]*\n?", "", raw)
        raw = re.sub(r"\n?```$", "", raw)

        restaurants = json.loads(raw)
        if not isinstance(restaurants, list):
            raise ValueError("Expected a JSON array")

        restaurants = [_normalize_restaurant(r) for r in restaurants]
        logger.info("Mistral returned %d restaurants for %s", len(restaurants), destination)
        return {
            "destination": destination,
            "restaurants": restaurants,
        }

    except Exception as exc:
        logger.exception("Restaurant AI generation failed for %s: %s", destination, exc)
        return {
            "destination": destination,
            "restaurants": _fallback_restaurants(destination, budget),
            "note":        "AI unavailable — showing curated suggestions",
        }


def _normalize_restaurant(r: dict) -> dict:
    """Map AI response fields to the exact keys the frontend renders."""
    highlights = r.get("highlights") or []
    best_for   = r.get("best_for") or r.get("meal_type") or "all day"
    return {
        "name":        r.get("name", ""),
        "cuisine":     r.get("cuisine", ""),
        "price_range": r.get("price_range", ""),
        "rating":      r.get("rating", 4.0),
        "meal_type":   best_for,                         # frontend: rest-meal chip
        "specialty":   highlights[0] if highlights else r.get("specialty", ""),  # frontend: specialty line
        "description": r.get("description") or (", ".join(highlights[1:]) if len(highlights) > 1 else ""),
        "timing":      r.get("timing") or r.get("opening_hours") or ("Morning – Night" if best_for == "all day" else ""),
        "address":     r.get("address", ""),
        "distance_from_centre": r.get("distance_from_centre", ""),
    }


def _fallback_restaurants(destination: str, budget: str) -> list:
    """Minimal static fallback when Mistral is unavailable."""
    price = {
        "budget": "₹100–₹200", "low": "₹150–₹300",
        "mid-range": "₹350–₹700", "medium": "₹350–₹700",
        "high": "₹800–₹1500", "luxury": "₹2000+",
    }.get(budget, "₹350–₹700")

    return [
        {
            "name":    f"The Local Kitchen, {destination}",
            "cuisine": "Local / Regional",
            "price_range": price,
            "rating":  4.2,
            "highlights": ["Authentic local flavours", "Popular with locals", "Fresh ingredients"],
            "best_for": "lunch",
            "address": f"City centre, {destination}",
            "distance_from_centre": "0.5 km",
        },
        {
            "name":    f"Spice Garden, {destination}",
            "cuisine": "Indian",
            "price_range": price,
            "rating":  4.4,
            "highlights":  ["Wide vegetarian menu", "Traditional recipes", "Family-friendly"],
            "best_for": "dinner",
            "address": f"Market area, {destination}",
            "distance_from_centre": "1.2 km",
        },
        {
            "name":    f"Café Sunrise, {destination}",
            "cuisine": "Café / Continental",
            "price_range": price,
            "rating":  4.1,
            "highlights":  ["Great breakfast platters", "Fresh coffee", "Quick service"],
            "best_for": "breakfast",
            "address": f"Main road, {destination}",
            "distance_from_centre": "0.8 km",
        },
        {
            "name":    f"Coastal Bites, {destination}",
            "cuisine": "Seafood",
            "price_range": price,
            "rating":  4.5,
            "highlights":  ["Fresh catch daily", "Waterfront seating", "Chef's specials"],
            "best_for": "dinner",
            "address": f"Waterfront area, {destination}",
            "distance_from_centre": "2.0 km",
        },
        {
            "name":    f"Street Food Hub, {destination}",
            "cuisine": "Street Food / Chaat",
            "price_range": "₹50–₹150",
            "rating":  4.3,
            "highlights":  ["Iconic local snacks", "Evening crowds", "Affordable & tasty"],
            "best_for": "all day",
            "address": f"Old market, {destination}",
            "distance_from_centre": "0.3 km",
        },
        {
            "name":    f"Fusion Plate, {destination}",
            "cuisine": "Multi-cuisine",
            "price_range": price,
            "rating":  4.0,
            "highlights":  ["Pan-Asian options", "Great ambience", "Cocktail menu"],
            "best_for": "dinner",
            "address": f"Hotel district, {destination}",
            "distance_from_centre": "1.5 km",
        },
    ]
