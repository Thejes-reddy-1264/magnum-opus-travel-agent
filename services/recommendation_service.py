"""
services/recommendation_service.py
Generates AI-like travel tips by combining weather + interests.
Includes generate_weather_recommendation() for intelligent weather-based activity suggestions.
No external AI API needed — rule-based logic for reliable, fast results.
"""

# ── Tip database ────────────────────────────────────────────────────────────
_INTEREST_TIPS = {
    "nature": [
        "🌿 Visit local botanical gardens and national parks early in the morning.",
        "🦋 Look for guided eco-tours — they reveal hidden natural gems.",
        "🌄 Sunrise hikes offer the best views with the fewest crowds.",
    ],
    "adventure": [
        "🧗 Check local adventure sports clubs for group discounts.",
        "🪂 Book adrenaline activities (rafting, zip-lining) in advance — slots fill fast.",
        "🗺️ Rent a bike or scooter to explore off-the-beaten-path trails.",
    ],
    "food": [
        "🍜 Skip tourist-center restaurants; wander 2–3 streets away for authentic local eats.",
        "🌮 Visit street markets in the morning for the freshest produce and snacks.",
        "🍷 Ask your hotel concierge for a neighbourhood food tour recommendation.",
    ],
    "culture": [
        "🏛️ Many museums offer free entry on the first Sunday of the month.",
        "🎭 Check local Facebook/Eventbrite for pop-up cultural events during your stay.",
        "📚 A short history podcast before visiting landmarks makes them 10× more meaningful.",
    ],
    "beach": [
        "🏄 Arrive at beaches before 9am — best waves, fewer people.",
        "🐚 Sunset beach walks often reveal calmer, lesser-known coves nearby.",
        "🌊 Check surf forecasts (e.g., Surfline) even if you only plan to swim.",
    ],
    "shopping": [
        "🛍️ Local bazaars and flea markets offer unique souvenirs at far better prices.",
        "💳 Always carry small cash — many artisan shops don't accept cards.",
        "🕐 Visit malls during weekday mornings to avoid weekend crowds.",
    ],
    "wellness": [
        "🧘 Many cities have free outdoor yoga sessions in public parks — search online.",
        "♨️ Look for traditional bath houses or hammams for an authentic spa experience.",
        "🌙 Evening meditation walks on scenic promenades are free and rejuvenating.",
    ],
}

_WEATHER_TIPS = {
    "hot": [
        "☀️ Stay hydrated — carry a reusable water bottle and fill it often.",
        "🧴 Apply SPF 50+ sunscreen every 2 hours, especially near water.",
        "🌴 Plan outdoor activities before 10am and after 4pm to avoid peak heat.",
    ],
    "cold": [
        "🧣 Layer up — moisture-wicking base layers under a windproof jacket work best.",
        "☕ Warm up with local hot drinks (chai, herbal teas) between sightseeing stops.",
        "🧤 Gloves and a beanie are essential; pack them even if forecasts seem mild.",
    ],
    "rainy": [
        "☔ Pack a compact travel umbrella — it's your best friend in unexpected showers.",
        "🏛️ Rainy days are perfect for museums, galleries, and indoor food markets.",
        "👟 Waterproof shoes or sandals prevent blisters on wet cobblestone streets.",
    ],
    "mild": [
        "🚶 Perfect weather for long walking tours — lace up comfortable shoes.",
        "🚲 Mild temperatures are ideal for cycling tours around the city.",
        "🌳 Pack a light jacket — evenings can be cooler than afternoons.",
    ],
}


def _classify_weather(temp: float, description: str) -> str:
    """Map temperature + description to a simple category."""
    desc = description.lower()
    if "rain" in desc or "shower" in desc or "drizzle" in desc or "storm" in desc:
        return "rainy"
    if temp >= 30:
        return "hot"
    if temp <= 12:
        return "cold"
    return "mild"


def get_recommendations(weather: dict, interests: list[str], budget: str) -> dict:
    """
    Build personalised travel tips from weather + user interests.

    Args:
        weather   (dict): Parsed weather data from weather_service.
        interests (list): Lowercase interest strings.
        budget    (str):  'budget', 'mid-range', or 'luxury'.

    Returns:
        dict: { 'weather_tips': [...], 'interest_tips': [...], 'budget_tip': str }
    """
    # Weather-based tips
    temp        = weather.get("temperature", 20)
    description = weather.get("description", "")
    category    = _classify_weather(temp, description)
    weather_tips = _WEATHER_TIPS.get(category, _WEATHER_TIPS["mild"])

    # Interest-based tips (up to 2 per interest, max 3 interests)
    interest_tips = []
    for interest in interests[:3]:
        tips = _INTEREST_TIPS.get(interest.lower(), [])
        interest_tips.extend(tips[:2])

    # Budget tip
    budget_tips = {
        "budget":    "💰 Search for free walking tours, public transit day passes, and local food stalls to stretch your budget.",
        "mid-range": "💳 Look for combo tickets (museums + transport) — they often save 20–30% vs buying separately.",
        "luxury":    "✨ Consider a hotel concierge for private guided experiences — they unlock access not available online.",
    }
    budget_tip = budget_tips.get(budget.lower(), budget_tips["mid-range"])

    return {
        "weather_tips":  weather_tips,
        "interest_tips": interest_tips if interest_tips else ["🗺️ Explore the city freely — sometimes the best discoveries are unplanned!"],
        "budget_tip":    budget_tip,
    }


# ═══════════════════════════════════════════════════════════════════════════════
# generate_weather_recommendation — Intelligent Weather-Based Activity Suggester
# ═══════════════════════════════════════════════════════════════════════════════

# Activity bundles keyed by weather "mood".
# Each bundle has: icon, headline, blurb, and a list of activity suggestions.
# To extend: add a new key below following the same structure.
_WEATHER_ACTIVITIES = {

    # ── Rain / Drizzle / Thunderstorm ────────────────────────────────────────
    "rain": {
        "mood":      "rainy",
        "icon":      "🌧️",
        "color":     "blue",
        "headline":  "Rainy Day — Go Indoors & Explore!",
        "blurb":     "It's wet outside — a perfect excuse to discover the city's indoor gems.",
        "activities": [
            "🏛️  Visit museums, galleries, or historical exhibitions",
            "📚  Spend a cosy afternoon in a local bookshop or library",
            "🎭  Book a theatre show, live-music venue, or comedy club",
            "☕  Cafe-hop and sample local coffee culture",
            "🍜  Take an indoor cooking class or food tasting tour",
            "🧖  Treat yourself to a spa or wellness centre session",
            "🎮  Check out a board-game café or escape room for fun",
        ],
    },

    # ── Snow / Sleet ─────────────────────────────────────────────────────────
    "snow": {
        "mood":      "snowy",
        "icon":      "❄️",
        "color":     "cyan",
        "headline":  "Snow Day — Embrace the Winter Magic!",
        "blurb":     "A snowy backdrop makes the city look like a postcard. Wrap up and enjoy it!",
        "activities": [
            "⛷️  Hit nearby ski slopes or snowboarding runs",
            "🛷  Find a sledding hill — free, fast, and fun for all ages",
            "🏔️  Take a scenic cable-car ride for panoramic snow views",
            "☕  Warm up with hot chocolate in a cosy mountain lodge",
            "📸  Golden-hour snow photography in the old town centre",
            "🧊  Visit an ice-skating rink (outdoor or indoor)",
            "🏛️  Explore heated indoor attractions on the coldest days",
        ],
    },

    # ── Clear sky + Hot (≥ 30 °C) ────────────────────────────────────────────
    "hot_sunny": {
        "mood":      "hot & sunny",
        "icon":      "🌊",
        "color":     "teal",
        "headline":  "Hot & Sunny — Head for the Water!",
        "blurb":     "It's scorching — the best places to be are the beach and water parks.",
        "activities": [
            "🏖️  Spend the day at the nearest beach or lakeside resort",
            "🤿  Try snorkelling or scuba diving in clear coastal waters",
            "🚤  Book a boat tour, kayaking, or paddleboard session",
            "🌊  Visit a waterpark or outdoor pool for a refreshing dip",
            "🏄  Take a surfing lesson if the waves are good",
            "🌴  Relax in the shade with a cold drink and a beach read",
            "🐠  Explore a reef or marine reserve on a guided tour",
        ],
    },

    # ── Clear sky + Mild (13–29 °C) ──────────────────────────────────────────
    "clear_sunny": {
        "mood":      "clear & mild",
        "icon":      "☀️",
        "color":     "yellow",
        "headline":  "Perfect Day — Time for Outdoor Sightseeing!",
        "blurb":     "Ideal conditions for exploring the city's iconic landmarks and hidden corners.",
        "activities": [
            "🗺️  Join a free walking tour to discover the city's history",
            "🏰  Visit open-air landmarks, castles, or historic sites",
            "🌸  Stroll through botanical gardens or city parks",
            "🚲  Rent a bike and explore the city at your own pace",
            "📸  Golden-hour photography at the most photogenic spots",
            "🎡  Visit an outdoor market or street food festival",
            "🧗  Try an outdoor hiking trail with a viewpoint at the top",
        ],
    },

    # ── Partly cloudy / Overcast ─────────────────────────────────────────────
    "cloudy": {
        "mood":      "cloudy",
        "icon":      "⛅",
        "color":     "purple",
        "headline":  "Mixed Skies — Best of Both Worlds!",
        "blurb":     "Clouds keep it comfortable — great for sightseeing without harsh sun.",
        "activities": [
            "🗺️  Walking tours are comfortable — no harsh sun to deal with",
            "🏛️  Mix outdoor landmarks with indoor galleries in one day",
            "🍽️  Explore the local food scene: markets, cafés, restaurants",
            "🚂  Take a scenic train or tram ride through the city",
            "🎨  Visit a street-art district or outdoor sculpture park",
            "🌿  Nature walks in parks or countryside — perfect lighting for photos",
            "🛍️  Browse local markets and artisan shops outdoors",
        ],
    },

    # ── Cold / Wind ──────────────────────────────────────────────────────────
    "cold": {
        "mood":      "cold",
        "icon":      "🧊",
        "color":     "indigo",
        "headline":  "Cold Weather — Layer Up & Embrace It!",
        "blurb":     "The cold keeps the crowds away — a great time to explore without queues.",
        "activities": [
            "🧣  Visit popular attractions with shorter queues than in peak season",
            "☕  Warm up between sights at local coffee shops and bakeries",
            "🏛️  Spend time in heated museums, libraries, and galleries",
            "🍲  Try hearty local cuisine — winter dishes are often the best",
            "🌆  Night walks look magical in cold, clear air — bring a good coat",
            "♨️  Look for indoor hot springs, saunas, or hammams nearby",
            "🎭  Evening shows and concerts are perfect cold-weather entertainment",
        ],
    },

    # ── Mist / Fog ───────────────────────────────────────────────────────────
    "fog": {
        "mood":      "misty",
        "icon":      "🌫️",
        "color":     "gray",
        "headline":  "Misty & Atmospheric — A Moody Adventure!",
        "blurb":     "Fog adds a mysterious, cinematic quality — embrace the atmosphere.",
        "activities": [
            "📸  Moody fog photography at bridges, waterfronts, and old towns",
            "🏰  Historic districts look hauntingly beautiful in morning mist",
            "☕  Hunt for atmospheric cafés with rain-streaked windows",
            "🚢  A ferry or river cruise in the mist is unforgettable",
            "🏛️  Great day for indoor museums and cultural centres",
            "🕵️  Self-guided mystery walking tour through the fog",
            "🍷  Wine tasting or whisky distillery tour — warmth from the inside!",
        ],
    },
}


def generate_weather_recommendation(weather_data: dict) -> dict:
    """
    Generate intelligent, weather-based activity recommendations.

    This is the primary public function for weather-driven suggestions.
    It interprets the OpenWeather API response and returns a structured
    recommendation bundle ready to be sent to the frontend.

    Logic:
        - Rain / Drizzle / Thunderstorm  → indoor activities
        - Snow / Sleet                   → winter sports & cosy indoors
        - Clear + temp ≥ 30 °C           → beaches & water activities
        - Clear + temp 13–29 °C          → outdoor sightseeing
        - Clouds / Overcast              → mixed indoor + outdoor
        - Cold (≤ 12 °C) & no rain       → cold-weather exploration
        - Mist / Fog / Haze              → atmospheric, moody activities

    Args:
        weather_data (dict): Parsed weather dict from weather_service.get_weather().
                             Expected keys: temperature, description, icon.

    Returns:
        dict: {
            "mood":       str,    # human-readable condition label
            "icon":       str,    # emoji icon for the condition
            "color":      str,    # theme color hint for the UI
            "headline":   str,    # short headline recommendation
            "blurb":      str,    # one-sentence context sentence
            "activities": [str],  # list of 7 specific activity suggestions
        }
        On error (bad input): returns a safe fallback bundle.

    Extension guide:
        Add new weather moods to _WEATHER_ACTIVITIES above following the
        same dict structure. No changes needed to this function.
    """
    # Guard: return a safe fallback if weather data is missing or errored
    if not weather_data or "error" in weather_data:
        return _WEATHER_ACTIVITIES["clear_sunny"]   # sensible default

    temp        = weather_data.get("temperature", 20)
    description = weather_data.get("description", "").lower()

    # ── Rule table (order matters — most specific checks first) ──────────────

    # 1. Rain family
    if any(kw in description for kw in ("rain", "drizzle", "shower", "thunderstorm", "storm")):
        return _WEATHER_ACTIVITIES["rain"]

    # 2. Snow family
    if any(kw in description for kw in ("snow", "sleet", "blizzard", "hail")):
        return _WEATHER_ACTIVITIES["snow"]

    # 3. Mist / Fog / Haze
    if any(kw in description for kw in ("mist", "fog", "haze", "smoke", "dust", "sand")):
        return _WEATHER_ACTIVITIES["fog"]

    # 4. Clear sky — split by temperature
    if any(kw in description for kw in ("clear", "sunny", "fair")):
        if temp >= 30:
            return _WEATHER_ACTIVITIES["hot_sunny"]   # beaches & water
        return _WEATHER_ACTIVITIES["clear_sunny"]     # outdoor sightseeing

    # 5. Clouds / Overcast — split by temperature
    if any(kw in description for kw in ("cloud", "overcast", "broken")):
        if temp <= 12:
            return _WEATHER_ACTIVITIES["cold"]        # cold & cloudy
        return _WEATHER_ACTIVITIES["cloudy"]          # mixed activities

    # 6. Temperature-only fallbacks when description is generic
    if temp >= 30:
        return _WEATHER_ACTIVITIES["hot_sunny"]
    if temp <= 12:
        return _WEATHER_ACTIVITIES["cold"]

    # 7. Default — pleasant mild day
    return _WEATHER_ACTIVITIES["clear_sunny"]
