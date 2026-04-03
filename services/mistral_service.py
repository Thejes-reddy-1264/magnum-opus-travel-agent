"""
services/mistral_service.py
Integrates Mistral AI to generate a dynamic, personalised travel itinerary.

Now supports:
  - Configurable number of days (1–10)
  - Number of persons (affects group-type recommendations)
  - Dynamic prompt template that scales to N days

Architecture:
  generate_itinerary_with_mistral()  — PRIMARY: calls Mistral API
  _fallback_itinerary()              — FALLBACK: rule-based text if Mistral fails
  _parse_mistral_response()          — cleans and structures the raw AI text
  _build_prompt()                    — builds a dynamic N-day prompt
"""

import logging
import re
import requests

from config import MISTRAL_API_KEY
from services.cost_service import classify_group

logger = logging.getLogger(__name__)

# ── Mistral API constants ──────────────────────────────────────────────────────
MISTRAL_API_URL = "https://api.mistral.ai/v1/chat/completions"
MISTRAL_MODEL   = "mistral-small-latest"
MISTRAL_TIMEOUT = (5, 45)   # longer timeout for multi-day plans

# Tokens scale with number of days (≈ 300 per day)
_TOKENS_PER_DAY = 320
_TOKEN_BASE      = 200


# ══════════════════════════════════════════════════════════════════════════════
# PROMPT BUILDER
# ══════════════════════════════════════════════════════════════════════════════

def _build_prompt(
    city: str,
    budget: str,
    interests_str: str,
    weather_str: str,
    number_of_days: int,
    group_type: str,
    group_label: str,
) -> str:
    """Build a dynamic Mistral prompt that scales to any number of days."""

    # Group-specific tone modifier
    group_hints = {
        "solo":        "Focus on solo-friendly, safe, and social activities. Include tips for meeting locals.",
        "couple":      "Include romantic experiences, private tours, and intimate dining options.",
        "small_group": "Balance group activities with free time. Include options that work for small groups.",
        "large_group": "Prioritise group tours, shared experiences, and activities bookable for large parties.",
    }
    group_note = group_hints.get(group_type, "")

    # Build the day header template for the format spec
    day_template_lines = []
    for d in range(1, number_of_days + 1):
        day_template_lines.append(f"DAY {d} THEME: <one-line theme for day {d}>")
        day_template_lines.append(f"MORNING: <activity name> | <1-2 sentence description>")
        day_template_lines.append(f"AFTERNOON: <activity name> | <1-2 sentence description>")
        day_template_lines.append(f"EVENING: <activity name> | <1-2 sentence description>")
        day_template_lines.append("")
    day_format_spec = "\n".join(day_template_lines)

    return f"""Plan a {number_of_days}-day trip for {group_label} to {city}.

Traveller profile:
- Budget: {budget}
- Interests: {interests_str}
- Current weather: {weather_str}
- Group: {group_label}

Special instructions: {group_note}

Format your response EXACTLY like this (use these exact headers, one block per day):
{day_format_spec}
TIPS: <3 practical travel tips separated by | characters>

Rules:
- Be specific to {city} — use real place names.
- Adjust for the weather and budget tier.
- No repeated activities across days.
- Do NOT add any extra text or formatting outside the structure above.
- Give each day a unique, engaging theme."""


# ══════════════════════════════════════════════════════════════════════════════
# PUBLIC ENTRY POINT
# ══════════════════════════════════════════════════════════════════════════════

def generate_itinerary_with_mistral(user_input: dict, weather: dict) -> dict:
    """
    Generate a dynamic travel itinerary using Mistral AI.

    Args:
        user_input (dict): {
            "city":             str,
            "budget":           str,
            "interests":        [str],
            "number_of_days":   int   (default 3),
            "number_of_persons": int  (default 1),
        }
        weather (dict): Parsed weather data from weather_service.get_weather()

    Returns:
        dict: {
            "source":         "mistral" | "fallback",
            "summary":        str,
            "days":           [{ day_number, theme, morning, afternoon, evening }],
            "tips":           [str],
            "number_of_days": int,
            "group_type":     str,
            "group_label":    str,
        }
    """
    city            = user_input.get("city", "Your Destination")
    budget          = user_input.get("budget", "mid-range")
    interests       = user_input.get("interests", [])
    number_of_days  = max(1, min(int(user_input.get("number_of_days", 3)), 10))
    number_of_persons = max(1, min(int(user_input.get("number_of_persons", 1)), 50))

    interests_str = ", ".join(interests) if interests else "general sightseeing"

    # Weather string
    weather_str = "unknown conditions"
    if weather and "error" not in weather:
        weather_str = (
            f"{weather.get('description', '')} — "
            f"{weather.get('temperature', '?')}°C, "
            f"humidity {weather.get('humidity', '?')}%"
        )

    # Group classification
    group_info  = classify_group(number_of_persons)
    group_type  = group_info["type"]
    group_label = group_info["label"]

    if not MISTRAL_API_KEY:
        logger.warning("MISTRAL_API_KEY not set — using fallback itinerary for '%s'.", city)
        return _fallback_itinerary(city, budget, interests, weather_str, number_of_days, group_info)

    # Build prompt
    prompt  = _build_prompt(city, budget, interests_str, weather_str, number_of_days, group_type, group_label)
    max_tok = _TOKEN_BASE + _TOKENS_PER_DAY * number_of_days

    payload = {
        "model": MISTRAL_MODEL,
        "messages": [
            {
                "role": "system",
                "content": (
                    "You are an expert travel planner who creates concise, practical, "
                    "personalised itineraries. Always follow the exact format requested. "
                    "Never deviate from the format structure — the output is parsed by code."
                ),
            },
            {"role": "user", "content": prompt},
        ],
        "temperature": 0.7,
        "max_tokens":  max_tok,
    }

    headers = {
        "Authorization": f"Bearer {MISTRAL_API_KEY}",
        "Content-Type":  "application/json",
    }

    try:
        logger.info(
            "Calling Mistral API (model=%s) for city='%s' days=%d persons=%d…",
            MISTRAL_MODEL, city, number_of_days, number_of_persons
        )
        response = requests.post(
            MISTRAL_API_URL,
            json=payload,
            headers=headers,
            timeout=MISTRAL_TIMEOUT,
        )
        response.raise_for_status()
        data = response.json()

        raw_text = data["choices"][0]["message"]["content"].strip()
        logger.info("Mistral itinerary received for '%s' (%d chars).", city, len(raw_text))

        days = _parse_mistral_response(raw_text, number_of_days)

        if not days:
            logger.warning("Mistral response could not be parsed — using fallback for '%s'.", city)
            return _fallback_itinerary(city, budget, interests, weather_str, number_of_days, group_info)

        # Extract TIPS line
        tips_line = ""
        for line in raw_text.splitlines():
            if line.strip().upper().startswith("TIPS:"):
                tips_line = line.split(":", 1)[1].strip()
                break

        return {
            "source":           "mistral",
            "summary":          f"AI-generated {number_of_days}-day plan for {city}",
            "raw_text":         raw_text,
            "tips":             [t.strip() for t in tips_line.split("|") if t.strip()],
            "days":             days,
            "number_of_days":   number_of_days,
            "group_type":       group_type,
            "group_label":      group_label,
        }

    except requests.exceptions.Timeout:
        logger.error("Mistral API timed out for '%s' — using fallback.", city)
    except requests.exceptions.HTTPError as e:
        status = getattr(e.response, "status_code", "?")
        logger.error("Mistral API HTTP %s for '%s' — using fallback.", status, city)
    except (KeyError, IndexError, ValueError) as e:
        logger.error("Failed to parse Mistral response for '%s': %s — using fallback.", city, e)
    except Exception as e:
        logger.exception("Unexpected Mistral error for '%s': %s — using fallback.", city, e)

    return _fallback_itinerary(city, budget, interests, weather_str, number_of_days, group_info)


# ══════════════════════════════════════════════════════════════════════════════
# RESPONSE PARSER  (supports N days)
# ══════════════════════════════════════════════════════════════════════════════

def _parse_mistral_response(text: str, expected_days: int = 3) -> list[dict]:
    """
    Parse the structured Mistral output into a list of day dicts.

    Expected format per day:
        DAY N THEME: <theme>
        MORNING: <name> | <description>
        AFTERNOON: <name> | <description>
        EVENING: <name> | <description>
    """
    days = []
    day_blocks = re.split(r"(?i)day\s+(\d+)\s+theme:", text)

    # day_blocks: [prefix, "1", content, "2", content, ...]
    i = 1
    while i < len(day_blocks) - 1:
        try:
            day_num = int(day_blocks[i])
        except ValueError:
            i += 2
            continue

        block = day_blocks[i + 1]
        i += 2

        lines = [ln.strip() for ln in block.splitlines() if ln.strip()]
        # Stop at the next DAY header or TIPS line
        content_lines = []
        for ln in lines:
            if re.match(r"(?i)^(tips:|day\s+\d+)", ln):
                break
            content_lines.append(ln)

        theme = content_lines[0] if content_lines else f"Day {day_num}"

        slots: dict = {"morning": None, "afternoon": None, "evening": None}
        for line in content_lines[1:]:
            for slot in slots:
                if line.upper().startswith(slot.upper() + ":"):
                    content = line.split(":", 1)[1].strip()
                    parts   = content.split("|", 1)
                    name    = parts[0].strip()
                    desc    = parts[1].strip() if len(parts) > 1 else ""
                    slots[slot] = {"name": name, "description": desc}
                    break

        # Fill any missing slots with a sensible default
        defaults = {
            "morning":   {"name": "Morning Exploration",  "description": "Explore the city at your own pace."},
            "afternoon": {"name": "Afternoon Sightseeing","description": "Visit the main attractions."},
            "evening":   {"name": "Evening Relaxation",   "description": "Dinner and leisure time."},
        }
        for slot, default in defaults.items():
            if slots[slot] is None:
                slots[slot] = default

        days.append({
            "day_number": day_num,
            "theme":      theme,
            "morning":    slots["morning"],
            "afternoon":  slots["afternoon"],
            "evening":    slots["evening"],
        })

    return days


# ══════════════════════════════════════════════════════════════════════════════
# RULE-BASED FALLBACK  (N-day capable)
# ══════════════════════════════════════════════════════════════════════════════

_INTEREST_ACTIVITIES = {
    "nature":    [
        ("Nature Walk",         "Explore local parks and natural reserves at a comfortable pace."),
        ("Botanical Garden",    "Visit the city's botanical gardens to see regional flora."),
        ("Sunrise Hike",        "A gentle morning hike to catch sunrise views."),
        ("Eco-Tour",            "Expert-led tour of local ecosystems and wildlife."),
        ("Lake / River Walk",   "A peaceful walk along the nearest waterway."),
    ],
    "adventure": [
        ("City Cycling Tour",   "Rent bikes and explore the city's key districts."),
        ("Rock Climbing",       "Try the nearest outdoor or indoor climbing spot."),
        ("River Kayaking",      "Navigate the local waterway for a scenic adrenaline rush."),
        ("Zip-Line Course",     "Fly through treetops on a thrilling zip-line course."),
        ("White-Water Rafting", "Adrenaline-packed river rapids with professional guides."),
    ],
    "food":      [
        ("Street Food Trail",   "Follow the city's most iconic street food route."),
        ("Local Market Visit",  "Browse the morning produce market and sample local snacks."),
        ("Cooking Class",       "Learn to cook two regional specialities with a local chef."),
        ("Food & Wine Tasting", "Guided tasting of local wines, beers, and cheeses."),
        ("Night Food Market",   "Evening food market with street food, crafts, and local vibe."),
    ],
    "culture":   [
        ("Museum Tour",         "Visit the main city museum to understand the region's history."),
        ("Heritage Walk",       "A guided walk through the old quarter and heritage monuments."),
        ("Live Music",          "Catch a local music or dance performance in the evening."),
        ("Art Gallery Visit",   "Browse contemporary and traditional art at a local gallery."),
        ("Cultural Workshop",   "Hands-on pottery, batik, or craft session with a local artisan."),
    ],
    "beach":     [
        ("Beach Morning Swim",  "Start the day with a refreshing swim on the main beach."),
        ("Boat Trip",           "Take a short coastal boat tour to see hidden coves."),
        ("Sunset Beach Walk",   "Golden-hour stroll along the shoreline."),
        ("Snorkelling Tour",    "Explore underwater reefs and marine life."),
        ("Surfing Lesson",      "Learn to surf with a qualified instructor."),
    ],
    "shopping":  [
        ("Local Bazaar",        "Explore the main market for handcrafted souvenirs."),
        ("Artisan Quarter",     "Visit workshops where craftspeople make and sell their work."),
        ("Night Market",        "Evening shopping for clothes, food, and handicrafts."),
        ("Boutique District",   "Browse independent boutiques and pop-up shops."),
    ],
    "wellness":  [
        ("Yoga Session",        "Join a morning yoga class at a local studio or retreat."),
        ("Spa Afternoon",       "Indulge in a traditional massage or wellness treatment."),
        ("Meditation Walk",     "A mindful walk through the city's quietest green space."),
        ("Hot Spring Soak",     "Soak in natural thermal pools — perfect for any weather."),
    ],
}

_DEFAULT_ACTIVITIES = [
    ("City Overview Walk",  "Explore the main landmarks and get acquainted with the city."),
    ("Local Café Morning",  "Start with a slow breakfast at a neighbourhood café."),
    ("Sunset Viewpoint",    "End the day at the best panoramic spot in the city."),
    ("Hidden Gems Tour",    "Venture off the tourist trail to discover local favourites."),
    ("Cultural Evening",    "Dinner followed by a local cultural show or market visit."),
    ("Day Trip Excursion",  "A short journey to a nearby attraction outside the city."),
    ("Museum Visit",        "Explore local art, history, and culture indoors."),
    ("River Walk",          "A peaceful evening stroll along the nearest waterway."),
    ("Night Market",        "Evening market with food, crafts, and local atmosphere."),
]

# Day theme templates: cycle through these for multi-day plans
_DAY_THEMES_TEMPLATES = [
    "Arrival & City Orientation",
    "Deep Dive — Culture & Local Life",
    "Relaxed Exploration & Hidden Gems",
    "Adventure & Nature Day",
    "Food, Markets & Local Flavours",
    "Shopping & Artisan Experiences",
    "Wellness & Slow Travel",
    "Day Trip & Surroundings",
    "Cultural Immersion",
    "Final Day — Last Impressions",
]


def _fallback_itinerary(
    city: str,
    budget: str,
    interests: list,
    weather_str: str,
    number_of_days: int = 3,
    group_info: dict | None = None,
) -> dict:
    """
    Deterministic rule-based itinerary for N days.
    Used when Mistral is unavailable or returns unparseable output.
    """
    if group_info is None:
        group_info = classify_group(1)

    group_type  = group_info["type"]
    group_label = group_info["label"]

    # Build activity pool from interests
    pool = []
    for interest in interests:
        pool.extend(_INTEREST_ACTIVITIES.get(interest, []))
    if not pool:
        pool = _DEFAULT_ACTIVITIES[:]

    # Ensure pool is large enough for N days × 3 slots
    needed = number_of_days * 3
    while len(pool) < needed:
        pool.extend(pool)

    def make_slot(activity: tuple) -> dict:
        return {"name": activity[0], "description": activity[1]}

    days = []
    for i in range(number_of_days):
        theme_idx = i % len(_DAY_THEMES_TEMPLATES)
        offset    = i * 3
        days.append({
            "day_number": i + 1,
            "theme":      _DAY_THEMES_TEMPLATES[theme_idx],
            "morning":    make_slot(pool[offset % len(pool)]),
            "afternoon":  make_slot(pool[(offset + 1) % len(pool)]),
            "evening":    make_slot(pool[(offset + 2) % len(pool)]),
        })

    tips = [
        f"Check local transport options in {city} — many cities offer day passes.",
        "Book restaurants and popular experiences in advance during peak season.",
        f"Weather note: {weather_str}.",
    ]

    return {
        "source":           "fallback",
        "summary":          f"{number_of_days}-day plan for {city} (AI offline — rule-based)",
        "raw_text":         "",
        "tips":             tips,
        "days":             days,
        "number_of_days":   number_of_days,
        "group_type":       group_type,
        "group_label":      group_label,
    }
