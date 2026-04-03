"""
services/hotel_service.py
Handles hotel search via RapidAPI (Booking.com).

Architecture:
  _parse_hotel()      — raw API dict → clean hotel dict (robust to missing fields)
  filter_hotels()     — PUBLIC: filter + sort + top-5 by budget tier
  get_hotels()        — orchestrates API calls then delegates to filter_hotels()

Production additions:
  - Structured logging at every stage
  - TTL in-memory caching (dest_id + hotel search results)
  - Status-specific error messages
  - Explicit connection/read timeout tuple
"""

import logging
import requests
from datetime import datetime, timedelta
from config import RAPIDAPI_KEY, RAPIDAPI_HOST, RAPIDAPI_BASE_URL, CACHE_TTL_HOTELS
from services.cache import api_cache

logger = logging.getLogger(__name__)

# (connect_timeout_sec, read_timeout_sec)
_TIMEOUT_DEST   = (5, 8)
_TIMEOUT_SEARCH = (5, 15)


# ── Budget tier config ─────────────────────────────────────────────────────
# Each tier defines: price band (min/max USD/night), star preference,
# a label for the UI badge, and the sort strategy.
#
# To add a new tier, add an entry here — no other changes needed.
#
BUDGET_TIERS = {
    # low / budget — cheapest options first, no star requirement
    "low": {
        "label":     "Budget-friendly",
        "price_min": 0,
        "price_max": 80,
        "min_stars": 0,       # any star rating accepted
        "sort":      "price_asc",   # cheapest first
    },
    # Keep "budget" as alias so existing callers still work
    "budget": {
        "label":     "Budget-friendly",
        "price_min": 0,
        "price_max": 80,
        "min_stars": 0,
        "sort":      "price_asc",
    },
    # medium / mid-range — mid-price band, prefer higher-rated
    "medium": {
        "label":     "Mid-range",
        "price_min": 50,
        "price_max": 200,
        "min_stars": 0,
        "sort":      "relevance",   # rating × star composite
    },
    # Keep "mid-range" as alias
    "mid-range": {
        "label":     "Mid-range",
        "price_min": 50,
        "price_max": 200,
        "min_stars": 0,
        "sort":      "relevance",
    },
    # high / luxury — premium band, prefer 4-5 star, top-rated first
    "high": {
        "label":     "Luxury",
        "price_min": 150,
        "price_max": 99_999,
        "min_stars": 4,
        "sort":      "rating_desc",  # best reviewed first
    },
    # Keep "luxury" as alias
    "luxury": {
        "label":     "Luxury",
        "price_min": 150,
        "price_max": 99_999,
        "min_stars": 4,
        "sort":      "rating_desc",
    },
}

# Fallback tier when the caller passes an unrecognised budget string
_DEFAULT_TIER = "mid-range"

# How many results to return after filtering + sorting
TOP_N = 5


# ══════════════════════════════════════════════════════════════════════════════
# MOCK HOTEL DATA  (used when RapidAPI is unavailable)
# Data sourced from the comprehensive India tourism assessment.
# ══════════════════════════════════════════════════════════════════════════════

_MOCK_HOTELS: dict[str, list[dict]] = {
    # ── Goa ──────────────────────────────────────────────────────────────────
    "goa": [
        {"name": "Taj Exotica Resort & Spa",       "price": 320, "stars": 5, "rating": 9.2, "review_word": "Exceptional",  "city": "Goa", "photo": "", "url": "#"},
        {"name": "Novotel Goa Dona Sylvia Resort", "price": 145, "stars": 5, "rating": 8.6, "review_word": "Fabulous",     "city": "Goa", "photo": "", "url": "#"},
        {"name": "Hacienda De Goa Resort",         "price": 95,  "stars": 4, "rating": 8.2, "review_word": "Very Good",    "city": "Goa", "photo": "", "url": "#"},
        {"name": "Panjim Inn Heritage Hotel",      "price": 55,  "stars": 3, "rating": 7.9, "review_word": "Good",         "city": "Goa", "photo": "", "url": "#"},
        {"name": "Zostel Goa (Palolem)",           "price": 18,  "stars": 1, "rating": 7.5, "review_word": "Good",         "city": "Goa", "photo": "", "url": "#"},
    ],
    # ── Delhi ────────────────────────────────────────────────────────────────
    "delhi": [
        {"name": "The Taj Mahal Hotel New Delhi",  "price": 380, "stars": 5, "rating": 9.3, "review_word": "Exceptional",  "city": "Delhi", "photo": "", "url": "#"},
        {"name": "Shangri-La Eros Hotel",          "price": 260, "stars": 5, "rating": 8.9, "review_word": "Fabulous",     "city": "Delhi", "photo": "", "url": "#"},
        {"name": "Lemon Tree Premier Aerocity",    "price": 110, "stars": 4, "rating": 8.4, "review_word": "Very Good",    "city": "Delhi", "photo": "", "url": "#"},
        {"name": "Hotel City Star Paharganj",      "price": 45,  "stars": 3, "rating": 7.6, "review_word": "Good",         "city": "Delhi", "photo": "", "url": "#"},
        {"name": "Hotel Ajanta New Delhi",         "price": 28,  "stars": 2, "rating": 7.1, "review_word": "Pleasant",     "city": "Delhi", "photo": "", "url": "#"},
    ],
    # ── New Delhi alias ───────────────────────────────────────────────────────
    "new delhi": [
        {"name": "The Taj Mahal Hotel New Delhi",  "price": 380, "stars": 5, "rating": 9.3, "review_word": "Exceptional",  "city": "New Delhi", "photo": "", "url": "#"},
        {"name": "Shangri-La Eros Hotel",          "price": 260, "stars": 5, "rating": 8.9, "review_word": "Fabulous",     "city": "New Delhi", "photo": "", "url": "#"},
        {"name": "Lemon Tree Premier Aerocity",    "price": 110, "stars": 4, "rating": 8.4, "review_word": "Very Good",    "city": "New Delhi", "photo": "", "url": "#"},
        {"name": "Hotel City Star Paharganj",      "price": 45,  "stars": 3, "rating": 7.6, "review_word": "Good",         "city": "New Delhi", "photo": "", "url": "#"},
        {"name": "Hotel Ajanta",                  "price": 28,  "stars": 2, "rating": 7.1, "review_word": "Pleasant",     "city": "New Delhi", "photo": "", "url": "#"},
    ],
    # ── Agra ─────────────────────────────────────────────────────────────────
    "agra": [
        {"name": "The Oberoi Amarvilas",           "price": 750, "stars": 5, "rating": 9.6, "review_word": "Exceptional",  "city": "Agra", "photo": "", "url": "#"},
        {"name": "ITC Mughal Agra",               "price": 290, "stars": 5, "rating": 9.0, "review_word": "Exceptional",  "city": "Agra", "photo": "", "url": "#"},
        {"name": "DoubleTree by Hilton Agra",     "price": 130, "stars": 4, "rating": 8.5, "review_word": "Very Good",    "city": "Agra", "photo": "", "url": "#"},
        {"name": "Aman Homestay Taj Ganj",        "price": 60,  "stars": 3, "rating": 8.0, "review_word": "Very Good",    "city": "Agra", "photo": "", "url": "#"},
        {"name": "Zostel Agra",                   "price": 15,  "stars": 1, "rating": 7.8, "review_word": "Good",         "city": "Agra", "photo": "", "url": "#"},
    ],
    # ── Jaipur ───────────────────────────────────────────────────────────────
    "jaipur": [
        {"name": "Rambagh Palace",                "price": 680, "stars": 5, "rating": 9.5, "review_word": "Exceptional",  "city": "Jaipur", "photo": "", "url": "#"},
        {"name": "The Oberoi Rajvilas",           "price": 540, "stars": 5, "rating": 9.4, "review_word": "Exceptional",  "city": "Jaipur", "photo": "", "url": "#"},
        {"name": "Samode Haveli",                 "price": 120, "stars": 4, "rating": 8.7, "review_word": "Fabulous",     "city": "Jaipur", "photo": "", "url": "#"},
        {"name": "Shahpura House",                "price": 75,  "stars": 3, "rating": 8.3, "review_word": "Very Good",    "city": "Jaipur", "photo": "", "url": "#"},
        {"name": "Moustache Hostel Jaipur",       "price": 12,  "stars": 1, "rating": 8.1, "review_word": "Very Good",    "city": "Jaipur", "photo": "", "url": "#"},
    ],
    # ── Varanasi ─────────────────────────────────────────────────────────────
    "varanasi": [
        {"name": "Taj Nadesar Palace",            "price": 420, "stars": 5, "rating": 9.4, "review_word": "Exceptional",  "city": "Varanasi", "photo": "", "url": "#"},
        {"name": "BrijRama Palace on Ganges",     "price": 310, "stars": 5, "rating": 9.2, "review_word": "Exceptional",  "city": "Varanasi", "photo": "", "url": "#"},
        {"name": "Shree Shivay Namastubhyam",     "price": 85,  "stars": 3, "rating": 8.6, "review_word": "Fabulous",     "city": "Varanasi", "photo": "", "url": "#"},
        {"name": "Hotel Temple on Ganges",        "price": 55,  "stars": 3, "rating": 8.0, "review_word": "Very Good",    "city": "Varanasi", "photo": "", "url": "#"},
        {"name": "Ganpati Guest House",           "price": 20,  "stars": 1, "rating": 7.7, "review_word": "Good",         "city": "Varanasi", "photo": "", "url": "#"},
    ],
    # ── Kerala ───────────────────────────────────────────────────────────────
    "kerala": [
        {"name": "Kumarakom Lake Resort",         "price": 480, "stars": 5, "rating": 9.5, "review_word": "Exceptional",  "city": "Kerala", "photo": "", "url": "#"},
        {"name": "Spice Village CGH Earth",       "price": 220, "stars": 5, "rating": 9.1, "review_word": "Exceptional",  "city": "Kerala", "photo": "", "url": "#"},
        {"name": "Malabar House Kochi",           "price": 110, "stars": 4, "rating": 8.8, "review_word": "Fabulous",     "city": "Kerala", "photo": "", "url": "#"},
        {"name": "Old Harbour Hotel Kochi",       "price": 80,  "stars": 3, "rating": 8.2, "review_word": "Very Good",    "city": "Kerala", "photo": "", "url": "#"},
        {"name": "Zostel Kochi",                  "price": 14,  "stars": 1, "rating": 7.9, "review_word": "Good",         "city": "Kerala", "photo": "", "url": "#"},
    ],
    # ── Mumbai ───────────────────────────────────────────────────────────────
    "mumbai": [
        {"name": "The Taj Mahal Palace Mumbai",   "price": 520, "stars": 5, "rating": 9.5, "review_word": "Exceptional",  "city": "Mumbai", "photo": "", "url": "#"},
        {"name": "Four Seasons Hotel Mumbai",     "price": 340, "stars": 5, "rating": 9.1, "review_word": "Exceptional",  "city": "Mumbai", "photo": "", "url": "#"},
        {"name": "Trident Hotel Nariman Point",   "price": 160, "stars": 5, "rating": 8.7, "review_word": "Fabulous",     "city": "Mumbai", "photo": "", "url": "#"},
        {"name": "Hotel Suba International",      "price": 70,  "stars": 3, "rating": 7.8, "review_word": "Good",         "city": "Mumbai", "photo": "", "url": "#"},
        {"name": "Zostel Mumbai",                 "price": 16,  "stars": 1, "rating": 7.6, "review_word": "Good",         "city": "Mumbai", "photo": "", "url": "#"},
    ],
}

# Generic fallback used for any city not in the curated list above
_GENERIC_MOCK_HOTELS = [
    {"name": "Grand Heritage Palace Hotel",   "price": 280, "stars": 5, "rating": 9.0, "review_word": "Exceptional", "photo": "", "url": "#"},
    {"name": "City Centre Comfort Suites",    "price": 130, "stars": 4, "rating": 8.5, "review_word": "Fabulous",    "photo": "", "url": "#"},
    {"name": "Boutique Stay at Old Quarter",  "price": 75,  "stars": 3, "rating": 8.0, "review_word": "Very Good",   "photo": "", "url": "#"},
    {"name": "Budget Inn Central",            "price": 40,  "stars": 2, "rating": 7.4, "review_word": "Good",        "photo": "", "url": "#"},
    {"name": "The Travellers Hostel",         "price": 15,  "stars": 1, "rating": 7.2, "review_word": "Good",        "photo": "", "url": "#"},
]


def _get_mock_hotels(city: str, budget: str) -> dict:
    """
    Return mock hotel data filtered by budget, used when RapidAPI is unavailable.
    Looks up the city in the curated database, falls back to generic hotels.
    """
    city_key = city.strip().lower()
    raw_list = _MOCK_HOTELS.get(city_key, None)

    if raw_list is None:
        # Try prefix match for compound names like "North Goa"
        for key in _MOCK_HOTELS:
            if key in city_key or city_key in key:
                raw_list = _MOCK_HOTELS[key]
                break

    if raw_list is None:
        logger.info("No curated mock hotels for '%s' — using generic fallback.", city)
        raw_list = [{**h, "city": city} for h in _GENERIC_MOCK_HOTELS]

    tier = BUDGET_TIERS.get(budget.lower(), BUDGET_TIERS[_DEFAULT_TIER])

    # Convert to the same shape as _parse_hotel() returns
    parsed = []
    for h in raw_list:
        parsed.append({
            "name":            h["name"],
            "price":           float(h["price"]),
            "currency":        "USD",
            "rating":          h["rating"],
            "rating_numeric":  float(h["rating"]),
            "review_word":     h.get("review_word", ""),
            "stars":           h["stars"],
            "address":         "",
            "city":            h.get("city", city),
            "photo":           h.get("photo", ""),
            "url":             h.get("url", "#"),
            "budget_tag":      tier["label"],
            "relevance_score": 0.0,
        })

    top = filter_hotels(parsed, budget)
    logger.info(
        "Mock hotels for '%s' (budget=%s): returning %d/%d results.",
        city, budget, len(top), len(parsed)
    )
    return {
        "hotels": top,
        "filter_summary": {
            "tier":      tier["label"],
            "price_min": tier["price_min"],
            "price_max": tier["price_max"] if tier["price_max"] < 99_999 else None,
            "sort":      tier["sort"],
            "returned":  len(top),
        },
        "mock": True,   # flag so the UI can show a disclaimer if desired
    }


def _headers() -> dict:
    """Shared RapidAPI request headers."""
    return {
        "X-RapidAPI-Key":  RAPIDAPI_KEY,
        "X-RapidAPI-Host": RAPIDAPI_HOST,
    }


def _safe_float(value, default: float = 0.0) -> float:
    """Safely convert a value to float, returning default on failure."""
    try:
        return float(value) if value not in (None, "", "N/A") else default
    except (TypeError, ValueError):
        return default


def _safe_int(value, default: int = 0) -> int:
    """Safely convert a value to int, returning default on failure."""
    try:
        return int(float(value)) if value not in (None, "", "N/A") else default
    except (TypeError, ValueError):
        return default


def _parse_hotel(raw: dict, budget_label: str, city_fallback: str) -> dict:
    """
    Convert a raw Booking.com hotel dict into a clean, normalised hotel dict.
    All field accesses are guarded — missing keys produce safe defaults.

    Args:
        raw          (dict): Single hotel entry from the API response.
        budget_label (str):  Human-readable budget tier (for UI badge).
        city_fallback(str):  City name to use if the hotel doesn't include one.

    Returns:
        dict: Clean hotel record.
    """
    # Price: try multiple possible field names in the API response
    price_raw = (
        raw.get("min_total_price")
        or raw.get("price_breakdown", {}).get("gross_price")
        or raw.get("composite_price_breakdown", {}).get("gross_amount", {}).get("value")
        or 0
    )
    price = round(_safe_float(price_raw), 2)

    # Rating: numeric score out of 10
    rating = _safe_float(raw.get("review_score"), default=0.0)

    # Star class: integer 1-5 (may be 0 if unclassified)
    stars = _safe_int(raw.get("class"), default=0)

    return {
        "name":           raw.get("hotel_name") or "Unknown Hotel",
        "price":          price,
        "currency":       raw.get("currency_code") or "USD",
        "rating":         rating if rating > 0 else "N/A",
        "rating_numeric": rating,          # always a float, for sorting
        "review_word":    raw.get("review_score_word") or "",
        "stars":          stars,
        "address":        raw.get("address") or "",
        "city":           raw.get("city") or city_fallback,
        "photo":          raw.get("main_photo_url") or "",
        "url":            raw.get("url") or "#",
        "budget_tag":     budget_label,
        "relevance_score": 0.0,           # populated by filter_hotels()
    }


def _compute_relevance(hotel: dict) -> float:
    """
    Composite relevance score used for 'relevance' sort mode.

    Formula (all components normalised to 0-1 range, then weighted):
        score = 0.55 × (rating / 10)
              + 0.30 × (stars / 5)
              + 0.15 × (1 - price_norm)

    A higher score means more relevant for mid-range travellers.
    """
    rating_score = hotel["rating_numeric"] / 10.0        # 0-1
    star_score   = min(hotel["stars"], 5) / 5.0          # 0-1
    # Normalise price: assume 0–300 USD range; lower price = higher score
    price_norm   = min(hotel["price"], 300) / 300.0 if hotel["price"] > 0 else 0.5
    price_score  = 1.0 - price_norm                      # 0-1, cheaper = higher

    return round(0.55 * rating_score + 0.30 * star_score + 0.15 * price_score, 4)


# ══════════════════════════════════════════════════════════════════════════════
# PUBLIC: filter_hotels
# ══════════════════════════════════════════════════════════════════════════════

def filter_hotels(hotels: list[dict], budget: str) -> list[dict]:
    """
    Filter, score, sort, and return top-N hotels based on the budget tier.

    This is the primary public filtering function. It is called internally
    by get_hotels() but can also be used independently (e.g., to re-filter
    a cached hotel list without a new API call).

    Budget tier mapping:
        low    / budget    → cheapest hotels (≤ $80/night), sorted price ascending
        medium / mid-range → mid-range ($50–$200/night), sorted by relevance score
        high   / luxury    → premium (≥ $150/night, ≥ 4 stars), sorted by rating

    Args:
        hotels (list[dict]): List of parsed hotel dicts (from _parse_hotel).
        budget (str):        Budget string — any of: low, budget, medium,
                             mid-range, high, luxury (case-insensitive).

    Returns:
        list[dict]: Up to TOP_N hotels, filtered and sorted per tier rules.
                    Each hotel gains a 'relevance_score' field.
                    Returns an empty list if no hotels pass the filters.
    """
    tier = BUDGET_TIERS.get(budget.lower(), BUDGET_TIERS[_DEFAULT_TIER])

    # ── Step 1: Filter ────────────────────────────────────────────────────────
    filtered = []
    for h in hotels:
        price = h["price"]
        stars = h["stars"]

        # Price band check — skip hotels with known price outside the range.
        # Hotels with price == 0 (unknown) are always kept as a safety net.
        if price > 0:
            if price < tier["price_min"] or price > tier["price_max"]:
                continue

        # Star rating minimum (only enforced for luxury tier)
        if tier["min_stars"] > 0 and stars > 0 and stars < tier["min_stars"]:
            continue

        filtered.append(h)

    # ── Step 2: Score every hotel that passed the filter ──────────────────────
    for h in filtered:
        h["relevance_score"] = _compute_relevance(h)

    # ── Step 3: Sort per tier strategy ────────────────────────────────────────
    sort_mode = tier["sort"]

    if sort_mode == "price_asc":
        # Cheapest first; hotels with unknown price (0) go to the end
        filtered.sort(key=lambda h: (h["price"] == 0, h["price"]))

    elif sort_mode == "rating_desc":
        # Highest-rated first; unknown ratings (0) go to the end
        filtered.sort(key=lambda h: (h["rating_numeric"] == 0, -h["rating_numeric"]))

    else:  # "relevance" — composite score descending
        filtered.sort(key=lambda h: -h["relevance_score"])

    # ── Step 4: Return top N ──────────────────────────────────────────────────
    return filtered[:TOP_N]


# ══════════════════════════════════════════════════════════════════════════════
# RapidAPI helpers
# ══════════════════════════════════════════════════════════════════════════════

def _get_destination_id(city: str) -> str | None:
    """
    Resolve a city name to a Booking.com destination_id via the RapidAPI
    /hotels/locations endpoint. Returns None on any failure so the caller
    can trigger the mock fallback.
    """
    url = f"{RAPIDAPI_BASE_URL}/hotels/locations"
    params = {"name": city, "locale": "en-gb"}

    try:
        response = requests.get(
            url, headers=_headers(), params=params, timeout=_TIMEOUT_DEST
        )
        response.raise_for_status()
        results = response.json()

        if not results:
            logger.warning("No destination results for city='%s'.", city)
            return None

        # Prefer city-type results; fall back to first result
        for item in results:
            if item.get("dest_type") == "city":
                logger.debug("Resolved '%s' → dest_id=%s", city, item['dest_id'])
                return item["dest_id"]

        return results[0]["dest_id"]

    except Exception as exc:
        logger.warning("_get_destination_id failed for '%s': %s", city, exc)
        return None


# ══════════════════════════════════════════════════════════════════════════════
# PUBLIC: get_hotels  (orchestrator)
# ══════════════════════════════════════════════════════════════════════════════

def get_hotels(city: str, budget: str, interests: list[str]) -> dict:
    """
    Fetch hotels from Booking.com for a city and return smart filtered results.

    Results are cached by (city_lower, budget) for CACHE_TTL_HOTELS seconds.

    Flow:
        1. Resolve city → dest_id  (cached separately)
        2. Call /hotels/search with checkin=tomorrow, checkout=+2 days
        3. Parse each raw hotel via _parse_hotel()
        4. filter_hotels() → top-5 with sorting/scoring

    Returns:
        dict: {'hotels': [...], 'filter_summary': {...}}
              or {'error': '...'} on failure.
    """
    if not RAPIDAPI_KEY:
        logger.warning("RAPIDAPI_KEY not set — using mock hotel data for '%s'.", city)
        return _get_mock_hotels(city, budget)

    tier = BUDGET_TIERS.get(budget.lower(), BUDGET_TIERS[_DEFAULT_TIER])

    # ── Cache check ───────────────────────────────────────────────────────────
    cache_key = f"hotels:{city.strip().lower()}:{budget.lower()}"
    cached = api_cache.get(cache_key)
    if cached is not None:
        logger.info("Hotel cache HIT for '%s' / %s", city, budget)
        return cached

    logger.info("Fetching hotels for '%s' (budget=%s)…", city, budget)

    try:
        # ── 1. Resolve destination ────────────────────────────────────────────
        dest_id = _get_destination_id(city)
        if not dest_id:
            logger.warning("dest_id not found for '%s' — falling back to mock data.", city)
            return _get_mock_hotels(city, budget)

        # ── 2. Search hotels ──────────────────────────────────────────────────
        today    = datetime.today()
        checkin  = (today + timedelta(days=1)).strftime("%Y-%m-%d")
        checkout = (today + timedelta(days=2)).strftime("%Y-%m-%d")

        url = f"{RAPIDAPI_BASE_URL}/hotels/search"
        params = {
            "dest_id":            dest_id,
            "dest_type":          "city",
            "checkin_date":       checkin,
            "checkout_date":      checkout,
            "adults_number":      "2",
            "order_by":           "popularity",
            "filter_by_currency": "USD",
            "locale":             "en-gb",
            "room_number":        "1",
            "units":              "metric",
            "page_number":        "0",
        }

        response = requests.get(
            url, headers=_headers(), params=params, timeout=_TIMEOUT_SEARCH
        )
        response.raise_for_status()
        data = response.json()

        raw_hotels = data.get("result", [])
        logger.info("Hotel search returned %d raw results for '%s'.", len(raw_hotels), city)

        # ── 3. Parse ──────────────────────────────────────────────────────────
        parsed = [
            _parse_hotel(h, tier["label"], city)
            for h in raw_hotels[:25]
        ]

        # ── 4. Filter + sort → top 5 ──────────────────────────────────────────
        top_hotels = filter_hotels(parsed, budget)
        logger.info(
            "filter_hotels('%s') → %d/%d results (tier=%s, sort=%s)",
            city, len(top_hotels), len(parsed), tier["label"], tier["sort"]
        )

        # ── 5. Build response ─────────────────────────────────────────────────
        if not top_hotels:
            # Live API returned nothing useful — fall through to mock data
            logger.warning("Live API returned 0 filtered hotels for '%s' — using mock.", city)
            return _get_mock_hotels(city, budget)

        result = {
            "hotels": top_hotels,
            "filter_summary": {
                "tier":      tier["label"],
                "price_min": tier["price_min"],
                "price_max": tier["price_max"] if tier["price_max"] < 99_999 else None,
                "sort":      tier["sort"],
                "returned":  len(top_hotels),
            },
        }

        api_cache.set(cache_key, result, ttl=CACHE_TTL_HOTELS)
        return result

    except requests.exceptions.HTTPError:
        try:
            status = response.status_code
        except NameError:
            status = 0
        logger.warning("Hotel API HTTP %d for '%s' — falling back to mock data.", status, city)
        return _get_mock_hotels(city, budget)

    except requests.exceptions.ConnectionError:
        logger.error("Cannot reach Hotel API for '%s' — using mock data.", city)
        return _get_mock_hotels(city, budget)

    except requests.exceptions.Timeout:
        logger.error("Hotel API timed out for '%s' — using mock data.", city)
        return _get_mock_hotels(city, budget)

    except Exception as exc:
        logger.exception("Unexpected error in get_hotels for '%s': %s — using mock.", city, exc)
        return _get_mock_hotels(city, budget)
