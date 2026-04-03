"""
services/travel_plan_service.py
Hybrid AI Travel Recommendation Engine.

generate_travel_plan(user_input, weather, hotels)
  → Combines user preferences + live weather + hotel data
  → Returns a fully structured, explainable travel plan (no randomness)

Design principles:
  - Every recommendation has a traceable reason (see 'reasoning' fields)
  - Weather gates which activity categories are offered
  - Interests rank activities within weather-approved categories
  - Hotel recommendation picks the best match for the budget tier
  - Tips are assembled from relevant pools (never random)
"""

# ── Activity master catalogue ──────────────────────────────────────────────
# Keyed by interest tag. Each entry has a list of activities, each with:
#   name, description, indoor (bool), ideal_weather (set of moods)
#
# 'ideal_weather' = set of weather moods where this activity is recommended.
# An empty set means "works in any weather".
#
_ACTIVITY_CATALOGUE = {
    "nature": [
        {"name": "Botanical Garden Walk",     "description": "Explore curated flora and seasonal blooms.", "indoor": False, "ideal_weather": {"mild","clear_sunny","cloudy"}},
        {"name": "Sunrise Hike",              "description": "Reach a viewpoint at dawn — fewest crowds, best light.", "indoor": False, "ideal_weather": {"mild","clear_sunny"}},
        {"name": "Guided Eco-Tour",           "description": "Expert-led tour of local ecosystems and wildlife.", "indoor": False, "ideal_weather": {"mild","clear_sunny","cloudy"}},
        {"name": "Indoor Nature Museum",      "description": "Natural history exhibits — perfect for any weather.", "indoor": True,  "ideal_weather": set()},
    ],
    "adventure": [
        {"name": "White-Water Rafting",       "description": "Adrenaline-packed river rapids with guided safety.", "indoor": False, "ideal_weather": {"mild","hot_sunny","clear_sunny"}},
        {"name": "Zip-Line Canopy Tour",      "description": "Fly through treetops on a thrilling zip-line course.", "indoor": False, "ideal_weather": {"mild","clear_sunny","cloudy"}},
        {"name": "Bike Trail Exploration",    "description": "Rent a mountain bike and tackle local scenic trails.", "indoor": False, "ideal_weather": {"mild","clear_sunny","cloudy"}},
        {"name": "Indoor Rock Climbing",      "description": "Bouldering and lead climbing at a local climbing gym.", "indoor": True,  "ideal_weather": set()},
        {"name": "Kayaking or Paddleboarding","description": "Paddle calm coastal waters or a scenic lake.", "indoor": False, "ideal_weather": {"hot_sunny","mild","clear_sunny"}},
    ],
    "food": [
        {"name": "Street Food Market Tour",   "description": "Sample authentic local cuisine at the city's best stalls.", "indoor": False, "ideal_weather": {"mild","clear_sunny","cloudy"}},
        {"name": "Indoor Cooking Class",      "description": "Learn to cook signature local dishes with a chef.", "indoor": True,  "ideal_weather": set()},
        {"name": "Neighbourhood Food Walk",   "description": "Wander off the tourist trail to find hidden local eateries.", "indoor": False, "ideal_weather": {"mild","clear_sunny","cloudy"}},
        {"name": "Wine or Craft Beer Tasting","description": "Guided tasting session at a local winery or brewery.", "indoor": True,  "ideal_weather": set()},
    ],
    "culture": [
        {"name": "Museum & Gallery Day",      "description": "Deep dive into local art, history, and heritage.", "indoor": True,  "ideal_weather": set()},
        {"name": "Historic Walking Tour",     "description": "Free or guided tour of the old town's landmarks.", "indoor": False, "ideal_weather": {"mild","clear_sunny","cloudy","cold"}},
        {"name": "Live Theatre or Music Show","description": "Catch a performance at a local venue in the evening.", "indoor": True,  "ideal_weather": set()},
        {"name": "Cultural Festival Visit",   "description": "Join a local festival or street fair if one is on.", "indoor": False, "ideal_weather": {"mild","clear_sunny","cloudy"}},
    ],
    "beach": [
        {"name": "Beach Day",                 "description": "Sun, sand, and sea — ideal for hot clear days.", "indoor": False, "ideal_weather": {"hot_sunny","clear_sunny"}},
        {"name": "Snorkelling or Scuba Dive", "description": "Explore underwater reefs and marine life.", "indoor": False, "ideal_weather": {"hot_sunny","clear_sunny"}},
        {"name": "Surfing Lesson",            "description": "Learn to surf with a qualified instructor.", "indoor": False, "ideal_weather": {"hot_sunny","clear_sunny","mild"}},
        {"name": "Coastal Sunset Walk",       "description": "Golden-hour stroll along the shoreline.", "indoor": False, "ideal_weather": {"mild","clear_sunny","cloudy"}},
        {"name": "Aquarium Visit",            "description": "Explore marine life indoors — great for rainy beach days.", "indoor": True,  "ideal_weather": set()},
    ],
    "shopping": [
        {"name": "Local Bazaar & Market",     "description": "Unique souvenirs and artisan goods at authentic prices.", "indoor": False, "ideal_weather": {"mild","clear_sunny","cloudy"}},
        {"name": "Covered Market Hall",       "description": "Historic indoor market with food, crafts, and goods.", "indoor": True,  "ideal_weather": set()},
        {"name": "Artisan District Stroll",   "description": "Browse independent boutiques and craft studios.", "indoor": False, "ideal_weather": {"mild","clear_sunny","cloudy"}},
    ],
    "wellness": [
        {"name": "Spa or Hammam Session",     "description": "Traditional bathing ritual for deep relaxation.", "indoor": True,  "ideal_weather": set()},
        {"name": "Outdoor Yoga Class",        "description": "Join a free park yoga session at sunrise or sunset.", "indoor": False, "ideal_weather": {"mild","clear_sunny","cloudy"}},
        {"name": "Meditation Nature Walk",    "description": "Mindful walking through a scenic park or garden.", "indoor": False, "ideal_weather": {"mild","clear_sunny","cloudy"}},
        {"name": "Hot Spring or Thermal Bath","description": "Soak in natural hot springs — bliss in cold weather.", "indoor": True,  "ideal_weather": {"cold","rainy","snowy","foggy"}},
    ],
}

# ── Mood classifier (mirrors recommendation_service logic) ─────────────────
def _classify_weather_mood(weather: dict) -> str:
    """Convert weather dict to a single mood string used for matching."""
    temp = weather.get("temperature", 20)
    desc = weather.get("description", "").lower()

    if any(kw in desc for kw in ("rain", "drizzle", "shower", "thunderstorm", "storm")):
        return "rainy"
    if any(kw in desc for kw in ("snow", "sleet", "blizzard", "hail")):
        return "snowy"
    if any(kw in desc for kw in ("mist", "fog", "haze")):
        return "foggy"
    if any(kw in desc for kw in ("clear", "sunny", "fair")):
        return "hot_sunny" if temp >= 30 else "clear_sunny"
    if any(kw in desc for kw in ("cloud", "overcast", "broken")):
        return "cold" if temp <= 12 else "cloudy"
    if temp >= 30:
        return "hot_sunny"
    if temp <= 12:
        return "cold"
    return "mild"


# ── Activity selector ──────────────────────────────────────────────────────
def _select_activities(interests: list, weather_mood: str, max_activities: int = 6) -> list:
    """
    Select the best activities given interests and current weather mood.

    Priority rules (deterministic, explainable):
      1. Activities whose ideal_weather includes the current mood come first
      2. Universal activities (ideal_weather = empty set → works anywhere) come second
      3. Weather-incompatible outdoor activities are deprioritised (moved to end)
      4. Deduplicate by name across interest categories
      5. Return up to max_activities unique activities
    """
    seen_names = set()
    tier_1 = []  # perfect weather match
    tier_2 = []  # universal (any weather)
    tier_3 = []  # weather mismatch (outdoor activities on bad-weather days)

    for interest in interests:
        catalogue = _ACTIVITY_CATALOGUE.get(interest.lower(), [])
        for act in catalogue:
            if act["name"] in seen_names:
                continue
            seen_names.add(act["name"])

            ideal = act["ideal_weather"]
            if not ideal:                          # universal
                tier_2.append(act)
            elif weather_mood in ideal:            # perfect match
                tier_1.append(act)
            else:                                  # weather mismatch
                tier_3.append(act)

    # Combine tiers: best first, fallback if needed
    ordered = tier_1 + tier_2 + tier_3
    return ordered[:max_activities]


# ── Hotel selector ─────────────────────────────────────────────────────────
def _select_best_hotel(hotels: list, budget: str) -> dict | None:
    """
    Pick the best hotel from the filtered list.

    Selection strategy per budget tier:
      low    → lowest price (already sorted price_asc by filter_hotels)
      medium → highest relevance_score (already sorted by filter_hotels)
      high   → highest rating (already sorted rating_desc by filter_hotels)

    Because filter_hotels() has already sorted the list, we simply return
    the first element — the top of the sorted list.

    Returns None if no hotels are available.
    """
    if not hotels:
        return None
    return hotels[0]


# ── Tips assembler ─────────────────────────────────────────────────────────
_WEATHER_TIPS = {
    "hot_sunny":   ["🧴 Apply SPF 50+ sunscreen every 2 hours.", "🌴 Plan outdoor activities before 10am and after 4pm.", "💧 Stay hydrated — carry a reusable water bottle at all times."],
    "clear_sunny": ["🚶 Perfect weather for long walking tours.", "📸 Golden hour (just before sunset) is magic for photography.", "🧢 Light layers for cooler evenings after a warm day."],
    "cloudy":      ["🌥️ Soft light is ideal for photography — no harsh shadows.", "🚲 Comfortable cycling weather — consider a bike day.", "🧥 A light jacket is enough — clouds keep temps stable."],
    "cold":        ["🧣 Layer up — thermal base layers make a huge difference.", "☕ Warm up between sights at local coffee shops.", "🌆 Fewer tourists in winter — shorter queues at every landmark."],
    "rainy":       ["☔ Pack a compact travel umbrella.", "🏛️ Museum days are most rewarding on rainy afternoons.", "👟 Waterproof shoes or ankle boots are essential."],
    "snowy":       ["🧤 Gloves, beanie, and a windproof layer are non-negotiable.", "📸 Snow transforms cities — early morning shots are stunning.", "⛷️ If there are slopes nearby, today is the perfect day to use them."],
    "foggy":       ["📸 Fog creates incredible atmospheric photography opportunities.", "🚢 A river cruise in the mist is an unforgettable experience.", "☕ Fog days are ideal for cosy café culture and slow mornings."],
    "mild":        ["🌤️ Ideal sightseeing weather — make the most of outdoors.", "🗺️ A free walking tour is the best way to start any city visit.", "🌳 Evenings are cool — bring a light jacket for after sunset."],
}

_BUDGET_TIPS = {
    "low":       "💰 Look for free museum days, city walking tours, and local food stalls — great experiences at zero cost.",
    "budget":    "💰 Look for free museum days, city walking tours, and local food stalls — great experiences at zero cost.",
    "medium":    "💳 Combo tickets (museum + transport) typically save 20–30%. Book online to skip queues.",
    "mid-range": "💳 Combo tickets (museum + transport) typically save 20–30%. Book online to skip queues.",
    "high":      "✨ A hotel concierge can unlock private tours and restaurant reservations not available online.",
    "luxury":    "✨ A hotel concierge can unlock private tours and restaurant reservations not available online.",
}

_GENERAL_TIPS = [
    "📱 Download offline maps before you go — saves data and works underground.",
    "💱 Withdraw local currency at airport ATMs — exchange rates are typically better than bureaux.",
    "🗓️ Book popular attractions at least 24 hours ahead — many sell out.",
]


# ══════════════════════════════════════════════════════════════════════════════
# PUBLIC: generate_travel_plan
# ══════════════════════════════════════════════════════════════════════════════

def generate_travel_plan(user_input: dict, weather: dict, hotels: list) -> dict:
    """
    Generate a fully structured, explainable travel plan.

    This is the core hybrid recommendation engine. It combines:
      - User preferences (budget, interests, city)
      - Live weather data (temperature, description → mood)
      - Filtered hotel list (pre-sorted by filter_hotels())

    Every output element has a traceable reason. Nothing is chosen randomly.

    Args:
        user_input (dict): Must contain:
                           { "city": str, "budget": str, "interests": [str] }
        weather    (dict): Parsed weather from weather_service.get_weather().
                           Keys: temperature, description, city, country, etc.
                           Pass {} or {"error": "..."} if unavailable.
        hotels     (list): Pre-filtered hotel list from filter_hotels().
                           Pass [] if unavailable.

    Returns:
        dict: Structured travel plan:
        {
          "destination_plan": str,        # one-sentence plan summary
          "weather_mood":     str,        # classified weather mood
          "activities": [                 # up to 6 recommended activities
            {
              "name":        str,
              "description": str,
              "indoor":      bool,
              "reason":      str          # why this was selected
            }
          ],
          "hotel_recommendation": {       # best hotel or null
            "name":          str,
            "price":         float,
            "currency":      str,
            "rating":        float | str,
            "stars":         int,
            "url":           str,
            "reason":        str          # why this hotel was chosen
          } | null,
          "tips": [str],                  # 5–7 actionable travel tips
          "plan_reasoning": str           # plain-English explanation of the logic
        }
    """
    city      = user_input.get("city", "your destination")
    budget    = user_input.get("budget", "mid-range").lower()
    interests = [i.lower() for i in (user_input.get("interests") or [])]

    # ── 1. Classify weather mood ───────────────────────────────────────────
    has_weather  = weather and "error" not in weather
    weather_mood = _classify_weather_mood(weather) if has_weather else "mild"
    temp_str     = f"{weather.get('temperature', '?')}°C" if has_weather else "unknown temperature"
    weather_desc = weather.get("description", "conditions unknown") if has_weather else "conditions unknown"

    # ── 2. Select activities ───────────────────────────────────────────────
    raw_activities = _select_activities(interests, weather_mood)

    # Add reasoning label to each activity
    activities_with_reasons = []
    for act in raw_activities:
        if not act["ideal_weather"]:
            reason = "Works in any weather — selected based on your interests."
        elif weather_mood in act["ideal_weather"]:
            reason = f"Ideal for {weather_desc} conditions ({temp_str})."
        else:
            reason = "Included as a fallback — weather is not ideal but still enjoyable."

        activities_with_reasons.append({
            "name":        act["name"],
            "description": act["description"],
            "indoor":      act["indoor"],
            "reason":      reason,
        })

    # If no interests given, add a default activity set
    if not activities_with_reasons:
        activities_with_reasons = [
            {"name": "City Walking Tour",   "description": "Explore the city's highlights on foot with a local guide.", "indoor": False, "reason": "Great starting activity for any destination."},
            {"name": "Local Food Market",   "description": "Sample authentic street food and local specialties.",        "indoor": False, "reason": "Universal cultural experience."},
            {"name": "Museum Visit",        "description": "Explore local history, art, and culture indoors.",           "indoor": True,  "reason": "Works in any weather conditions."},
        ]

    # ── 3. Pick best hotel ─────────────────────────────────────────────────
    best_hotel_raw = _select_best_hotel(hotels, budget)

    if best_hotel_raw:
        # Reason is derived from the sort mode (mirrors filter_hotels logic)
        budget_sort_reasons = {
            "low":       "lowest price in the budget tier — best value for money.",
            "budget":    "lowest price in the budget tier — best value for money.",
            "medium":    "highest composite match score (rating × stars × price).",
            "mid-range": "highest composite match score (rating × stars × price).",
            "high":      "highest guest rating among 4–5 star properties.",
            "luxury":    "highest guest rating among 4–5 star properties.",
        }
        hotel_reason = f"Ranked #1 by {budget_sort_reasons.get(budget, 'relevance score')} ({len(hotels)} properties filtered)"

        hotel_recommendation = {
            "name":     best_hotel_raw.get("name", "Unknown Hotel"),
            "price":    best_hotel_raw.get("price", 0),
            "currency": best_hotel_raw.get("currency", "USD"),
            "rating":   best_hotel_raw.get("rating", "N/A"),
            "stars":    best_hotel_raw.get("stars", 0),
            "url":      best_hotel_raw.get("url", "#"),
            "budget_tag":       best_hotel_raw.get("budget_tag", ""),
            "relevance_score":  best_hotel_raw.get("relevance_score", 0),
            "reason":   hotel_reason,
        }
    else:
        hotel_recommendation = None

    # ── 4. Assemble tips ───────────────────────────────────────────────────
    weather_tips = _WEATHER_TIPS.get(weather_mood, _WEATHER_TIPS["mild"])
    budget_tip   = _BUDGET_TIPS.get(budget, _BUDGET_TIPS["mid-range"])
    tips = weather_tips[:2] + [budget_tip] + _GENERAL_TIPS[:2]

    # ── 5. Build destination plan summary ─────────────────────────────────
    interest_str = " & ".join(interests[:3]).title() if interests else "General Sightseeing"
    budget_labels = {"low":"budget","budget":"budget","medium":"mid-range","mid-range":"mid-range","high":"luxury","luxury":"luxury"}
    budget_label  = budget_labels.get(budget, budget)

    destination_plan = (
        f"{interest_str} trip to {city.title()} — "
        f"{weather_desc} ({temp_str}), {budget_label} budget, "
        f"{len(activities_with_reasons)} curated activities."
    )

    # ── 6. Plain-English reasoning ────────────────────────────────────────
    outdoor_count  = sum(1 for a in activities_with_reasons if not a["indoor"])
    indoor_count   = sum(1 for a in activities_with_reasons if a["indoor"])
    plan_reasoning = (
        f"Weather classified as '{weather_mood}' ({weather_desc}, {temp_str}). "
        f"Activities selected: {outdoor_count} outdoor, {indoor_count} indoor — "
        f"{'prioritising indoor options due to weather' if weather_mood in ('rainy','snowy','cold') else 'prioritising outdoor options'}. "
        f"Hotel chosen by {'price (cheapest)' if budget in ('low','budget') else 'rating (top-rated)' if budget in ('high','luxury') else 'relevance score'}. "
        f"Tips drawn from weather ({weather_mood}) + budget ({budget_label}) profiles."
    )

    return {
        "destination_plan":    destination_plan,
        "weather_mood":        weather_mood,
        "activities":          activities_with_reasons,
        "hotel_recommendation": hotel_recommendation,
        "tips":                tips,
        "plan_reasoning":      plan_reasoning,
    }


# ══════════════════════════════════════════════════════════════════════════════
# PUBLIC: generate_itinerary
# ══════════════════════════════════════════════════════════════════════════════

# ── Time-of-day activity pools ────────────────────────────────────────────────
# Each activity has preferred_interests — the interests it best serves.
# Empty list = suitable for all travellers.

_MORNING_POOL = [
    {"name": "Sunrise Hike or Viewpoint Walk",        "desc": "Start the day with the city's best views at dawn — minimal crowds, golden light.",        "interests": ["nature", "adventure"]},
    {"name": "Outdoor Yoga in the Park",               "desc": "Join a free sunrise yoga session in a local park to energise the day.",                   "interests": ["wellness", "nature"]},
    {"name": "Morning Food Market Visit",              "desc": "Explore the freshest local produce and street breakfast dishes before the tourist rush.",  "interests": ["food"]},
    {"name": "Hotel Breakfast & Neighbourhood Stroll", "desc": "Enjoy breakfast at the hotel, then walk the surrounding streets at a relaxed pace.",      "interests": []},
    {"name": "Beach Swim at Sunrise",                  "desc": "Arrive before the crowds for calm water and the best waves of the day.",                   "interests": ["beach", "adventure"]},
    {"name": "Museum Opening — First In",              "desc": "Museums are emptiest in the first hour — ideal for unhurried exploration.",               "interests": ["culture"]},
    {"name": "Cycling Tour of the City",               "desc": "Rent bikes and cover more ground across the city's highlights before the heat builds.",   "interests": ["adventure", "nature"]},
]

_AFTERNOON_POOL = [
    {"name": "Guided Historic Walking Tour",           "desc": "A local guide brings the city's history to life on a 2–3 hour walking tour.",           "interests": ["culture", "food"]},
    {"name": "Main Landmark Sightseeing",              "desc": "Visit the destination's iconic must-see attractions in the afternoon light.",             "interests": []},
    {"name": "Snorkelling or Boat Tour",               "desc": "Explore clear coastal waters on a guided marine or boat excursion.",                     "interests": ["beach", "adventure"]},
    {"name": "Indoor Cooking Class",                   "desc": "Learn to prepare authentic local dishes with a professional chef.",                       "interests": ["food", "culture"]},
    {"name": "Zip-Line or Adventure Park",             "desc": "Spend the afternoon on adrenaline-fuelled activities at a local adventure centre.",       "interests": ["adventure"]},
    {"name": "Art & Gallery Afternoon",                "desc": "Browse contemporary and traditional art galleries at a comfortable pace.",                "interests": ["culture"]},
    {"name": "Spa or Hammam Session",                  "desc": "A traditional bathhouse experience — deeply relaxing mid-trip recharge.",                "interests": ["wellness"]},
    {"name": "Local Bazaar & Shopping",                "desc": "Hunt for souvenirs and artisan goods at authentic local markets.",                        "interests": ["shopping", "culture"]},
    {"name": "Botanical Garden or Nature Reserve",     "desc": "Explore curated green spaces and wildlife on a peaceful afternoon walk.",                "interests": ["nature", "wellness"]},
]

_EVENING_POOL = [
    {"name": "Sunset Rooftop or Viewpoint",            "desc": "Watch the city light up at golden hour from the best vantage point.",                    "interests": []},
    {"name": "Neighbourhood Street Food Crawl",        "desc": "Wander local streets sampling the city's best casual evening bites.",                   "interests": ["food", "culture"]},
    {"name": "Live Music, Theatre, or Comedy Show",    "desc": "Catch a live performance — one of the best ways to experience local culture.",           "interests": ["culture"]},
    {"name": "Wine Tasting or Craft Beer Tour",        "desc": "Evening tasting session at a local winery, brewery, or bar.",                           "interests": ["food", "wellness"]},
    {"name": "Coastal Sunset Walk",                    "desc": "A golden-hour stroll along the beach or waterfront as the day winds down.",              "interests": ["beach", "nature"]},
    {"name": "Night Market Visit",                     "desc": "Many cities have vibrant evening markets — food, crafts, and local atmosphere.",         "interests": ["shopping", "food"]},
    {"name": "Evening Meditation Walk",                "desc": "A quiet, mindful walk through a scenic park or along a riverside promenade.",            "interests": ["wellness", "nature"]},
    {"name": "Fine Dining or Restaurant Experience",   "desc": "Reserve a table at a highly-rated local restaurant for a memorable dinner.",            "interests": ["food"]},
]

# Indoor fallbacks for bad-weather (rainy / snowy / foggy) days
_INDOOR_FALLBACKS = {
    "morning":   {"name": "Cosy Café Morning",           "desc": "Find a local café with character — enjoy breakfast, read, and watch the city wake up."},
    "afternoon": {"name": "Museum or Gallery Deep Dive", "desc": "A full afternoon in a great museum — audio guides turn it into a rich, immersive experience."},
    "evening":   {"name": "Indoor Dinner & Live Music",  "desc": "Book a restaurant with live acoustic performance — warm, atmospheric, and local."},
}

_BAD_WEATHER_MOODS = {"rainy", "snowy", "foggy"}

# Day themes give each day a distinct narrative arc
_DAY_THEMES = [
    "Arrival & City Orientation",
    "Deep Dive — Culture & Experiences",
    "Relaxed Exploration & Local Life",
]


def _score_slot(activity: dict, interests: list) -> int:
    """Score an activity by how many of the user's interests it matches."""
    return sum(1 for i in activity["interests"] if i in interests)


def _pick_slot(pool: list, interests: list, used: set, slot: str, bad_weather: bool) -> dict:
    """
    Pick the best unused activity from a slot pool.

    1. Score all candidates by interest overlap.
    2. Choose the highest-scoring unused one.
    3. If pool is exhausted or bad weather applies, use indoor fallback.
    """
    candidates = [a for a in pool if a["name"] not in used]
    candidates.sort(key=lambda a: _score_slot(a, interests), reverse=True)

    if candidates:
        chosen = candidates[0]
        used.add(chosen["name"])
        return {"name": chosen["name"], "description": chosen["desc"]}

    # All candidates used — return weather-appropriate fallback
    fb = _INDOOR_FALLBACKS.get(slot, {"name": "Free Exploration", "desc": "Wander and discover the city at your own pace."})
    return {"name": fb["name"], "description": fb["desc"]}


def generate_itinerary(plan: dict) -> dict:
    """
    Generate a realistic 2–3 day, time-slotted travel itinerary.

    Takes the structured output of generate_travel_plan() and produces a
    day-by-day schedule: morning, afternoon, and evening slots per day.

    Scheduling rules (deterministic — no randomness):
      - Activities never repeat across days or slots (global deduplication)
      - Morning slots: energising, early-opening, or gentle orientation
      - Afternoon slots: main attraction or immersive experience
      - Evening slots: cultural, dining, or relaxation
      - Bad weather (rain/snow/fog): Day 2+ morning/afternoon prefer indoor options
      - Day 1 always starts with a gentle neighbourhood orientation
      - 2 days for ≤2 interests, 3 days for ≥3 interests

    Args:
        plan (dict): Output of generate_travel_plan(). Must contain:
                     - 'weather_mood' (str)
                     - 'activities'   (list) — used to detect interests
                     - 'destination_plan' (str)

    Returns:
        dict: {
          "days": [
            {
              "day_number": int,
              "theme":      str,
              "morning":    { "name": str, "description": str },
              "afternoon":  { "name": str, "description": str },
              "evening":    { "name": str, "description": str },
            }, ...
          ],
          "num_days": int,
          "summary":  str
        }
    """
    weather_mood = plan.get("weather_mood", "mild")
    destination  = plan.get("destination_plan", "your trip")
    activities   = plan.get("activities", [])
    bad_weather  = weather_mood in _BAD_WEATHER_MOODS

    # Detect which interests were actually used, from the activity catalogue
    interests = list({
        interest
        for interest, acts in _ACTIVITY_CATALOGUE.items()
        for act in acts
        if any(a["name"] == act["name"] for a in activities)
    })

    # 3 days for ≥3 distinct interests, else 2 days
    num_days = 3 if len(interests) >= 3 else 2

    used: set = set()   # global deduplication — no activity repeated
    days = []

    for day_num in range(1, num_days + 1):
        theme = _DAY_THEMES[day_num - 1]

        # Day 1 always starts gently regardless of weather
        if day_num == 1:
            morning_pool = _MORNING_POOL
        elif bad_weather:
            # On bad-weather later days, prefer morning activities tagged for indoor interests
            morning_pool = [a for a in _MORNING_POOL if any(i in a["interests"] for i in ["culture", "wellness"])]
            if not morning_pool:
                morning_pool = _MORNING_POOL
        else:
            morning_pool = _MORNING_POOL

        morning   = _pick_slot(morning_pool,   interests, used, "morning",   bad_weather and day_num > 1)
        afternoon = _pick_slot(_AFTERNOON_POOL, interests, used, "afternoon", bad_weather and day_num > 1)
        evening   = _pick_slot(_EVENING_POOL,   interests, used, "evening",   False)  # evening is always flexible

        days.append({
            "day_number": day_num,
            "theme":      theme,
            "morning":    morning,
            "afternoon":  afternoon,
            "evening":    evening,
        })

    # Build summary string
    city_name = destination.split(" trip to ")[-1].split(" —")[0].strip().title() \
                if " trip to " in destination else "your destination"
    interest_label = ", ".join(i.title() for i in interests[:3]) if interests else "General"
    summary = (
        f"{num_days}-day itinerary for {city_name} · "
        f"Weather: {weather_mood.replace('_', ' ')} · "
        f"Focus: {interest_label}"
    )

    return {
        "days":     days,
        "num_days": num_days,
        "summary":  summary,
    }
