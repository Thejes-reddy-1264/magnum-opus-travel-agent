"""
services/cost_service.py — Trip cost estimation engine.

Calculates realistic per-person and total trip costs based on:
  - Destination city (estimated cost-of-living tier)
  - Budget tier (budget / mid-range / luxury)
  - Number of days
  - Number of persons
  - Group type (solo / couple / small_group / large_group)

All figures are in USD per person per day and are reasonable estimates
for planning purposes — not real-time prices.
"""

import logging

logger = logging.getLogger(__name__)

# ── Cost tiers: (accommodation, food, activities) per person per day ──────────
# Values in USD. These are planning estimates — not real-time prices.
_BUDGET_COSTS = {
    "budget":    {"accommodation": 30,  "food": 15, "activities": 10, "transport": 8},
    "low":       {"accommodation": 30,  "food": 15, "activities": 10, "transport": 8},
    "mid-range": {"accommodation": 90,  "food": 40, "activities": 30, "transport": 20},
    "medium":    {"accommodation": 90,  "food": 40, "activities": 30, "transport": 20},
    "high":      {"accommodation": 220, "food": 90, "activities": 70, "transport": 40},
    "luxury":    {"accommodation": 220, "food": 90, "activities": 70, "transport": 40},
}

# ── Group type classifier ─────────────────────────────────────────────────────
def classify_group(persons: int) -> dict:
    """
    Classify the travel group and return metadata.

    Returns:
        {
          "type":        "solo" | "couple" | "small_group" | "large_group",
          "label":       str,   # human-friendly label
          "emoji":       str,
          "description": str,  # used in frontend badges
          "discount":    float # group discount multiplier (1.0 = no discount)
        }
    """
    if persons == 1:
        return {
            "type":        "solo",
            "label":       "Solo Traveller",
            "emoji":       "🧳",
            "description": "Solo-friendly activities selected",
            "discount":    1.0,
        }
    elif persons == 2:
        return {
            "type":        "couple",
            "label":       "Couple",
            "emoji":       "💑",
            "description": "Couple-friendly & romantic activities selected",
            "discount":    1.0,
        }
    elif persons <= 4:
        return {
            "type":        "small_group",
            "label":       f"Small Group ({persons})",
            "emoji":       "👫",
            "description": "Small group activities selected",
            "discount":    0.95,   # 5% group discount
        }
    else:
        return {
            "type":        "large_group",
            "label":       f"Group of {persons}",
            "emoji":       "👥",
            "description": "Group activities & shared experiences selected",
            "discount":    0.90,   # 10% group discount
        }


# ── Group activity tags ───────────────────────────────────────────────────────
_GROUP_ACTIVITY_TAGS = {
    "solo":        ["independent",  "self-paced", "solo-friendly"],
    "couple":      ["romantic",     "intimate",   "couple-friendly"],
    "small_group": ["interactive",  "social",     "small-group"],
    "large_group": ["group",        "shared",     "guided-tour"],
}

_GROUP_ACTIVITY_SUGGESTIONS = {
    "solo": [
        "Free walking tours — ideal for meeting other solo travellers",
        "Hostel social events and communal dinners",
        "Solo-friendly cooking classes (shared tables)",
        "Day hikes with guided group departures",
    ],
    "couple": [
        "Sunset dinner cruise or rooftop dining",
        "Private cooking class for two",
        "Couples spa or wellness retreat",
        "Guided wine tasting for two",
        "Sunrise private boat tour",
    ],
    "small_group": [
        "Private guided city tour (shared cost = great value)",
        "Group cooking experience",
        "Escape rooms or interactive experiences",
        "Shared boat hire or day trip",
    ],
    "large_group": [
        "Private bus/van day trips",
        "Group surf or yoga lessons",
        "Pub/food crawl with a local guide",
        "Group cooking class with competitive dishes",
        "Ticketed group access to major attractions",
    ],
}


def get_group_activity_suggestions(group_type: str) -> list[str]:
    """Return activity suggestions tailored to the group type."""
    return _GROUP_ACTIVITY_SUGGESTIONS.get(group_type, _GROUP_ACTIVITY_SUGGESTIONS["small_group"])


# ── Cost calculator ───────────────────────────────────────────────────────────
def calculate_trip_cost(
    budget: str,
    number_of_days: int,
    number_of_persons: int,
) -> dict:
    """
    Calculate total estimated trip cost with per-category breakdown.

    Args:
        budget:           Budget tier string ("budget", "mid-range", "luxury", etc.)
        number_of_days:   Trip duration in days
        number_of_persons: Number of travellers

    Returns:
        {
          "currency":       "USD",
          "per_person_per_day": {
              "accommodation": float,
              "food":          float,
              "activities":    float,
              "transport":     float,
              "total":         float,
          },
          "per_person_total": float,
          "group_discount":   float,   # 0 if no discount
          "total_cost":       float,   # grand total for all persons
          "breakdown": {
              "accommodation": float,
              "food":          float,
              "activities":    float,
              "transport":     float,
          },
          "note": str,   # disclaimer
        }
    """
    norm_budget = budget.strip().lower()
    rates = _BUDGET_COSTS.get(norm_budget, _BUDGET_COSTS["mid-range"])
    group = classify_group(number_of_persons)
    discount = group["discount"]

    # Per-person per-day costs
    ppd = {k: round(v * discount, 2) for k, v in rates.items()}
    ppd["total"] = round(sum(ppd.values()), 2)

    # Per-person total for the trip
    pp_total = round(ppd["total"] * number_of_days, 2)

    # Grand total for all persons
    total = round(pp_total * number_of_persons, 2)

    # Category breakdown (all persons, all days)
    breakdown = {
        k: round(v * discount * number_of_days * number_of_persons, 2)
        for k, v in rates.items()
    }

    discount_pct = round((1 - discount) * 100)
    note = (
        f"Estimated costs in USD. "
        f"{'Group discount of ' + str(discount_pct) + '% applied. ' if discount_pct else ''}"
        "Actual prices vary by season and availability."
    )

    logger.info(
        "Cost estimate: budget=%s days=%d persons=%d total=$%.2f",
        norm_budget, number_of_days, number_of_persons, total
    )

    return {
        "currency":            "USD",
        "per_person_per_day":  ppd,
        "per_person_total":    pp_total,
        "group_discount_pct":  discount_pct,
        "total_cost":          total,
        "breakdown":           breakdown,
        "note":                note,
    }
