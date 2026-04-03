"""
services/booking_service.py
Razorpay payment integration for TripSense.

Flow:
  1. Frontend calls POST /api/create-payment-order → backend creates Razorpay order
  2. Frontend opens Razorpay checkout with order_id
  3. After payment, frontend calls POST /api/verify-payment → backend verifies HMAC
  4. On success, booking record is saved to DB
"""

import hashlib
import hmac
import json
import logging
import uuid
from datetime import datetime

import razorpay

from config import RAZORPAY_KEY_ID, RAZORPAY_KEY_SECRET

logger = logging.getLogger(__name__)

# Initialise Razorpay client (lazy — only if keys are set)
_client = None

def _get_client():
    global _client
    if _client is None:
        if not RAZORPAY_KEY_ID or not RAZORPAY_KEY_SECRET:
            raise RuntimeError("Razorpay keys not configured.")
        _client = razorpay.Client(auth=(RAZORPAY_KEY_ID, RAZORPAY_KEY_SECRET))
    return _client


# ── Create Razorpay Order ─────────────────────────────────────────────────────

def create_payment_order(amount_inr: float, booking_type: str, description: str) -> dict:
    """
    Create a Razorpay order for the given amount (in ₹).

    Returns:
        { "order_id": str, "amount": int (paise), "currency": "INR",
          "key_id": str, "description": str }
    """
    amount_paise = int(amount_inr * 100)  # Razorpay uses paise

    client = _get_client()
    order = client.order.create({
        "amount":   amount_paise,
        "currency": "INR",
        "notes": {
            "booking_type": booking_type,
            "description":  description,
        },
    })

    logger.info("Razorpay order created: %s  ₹%.2f", order["id"], amount_inr)
    return {
        "order_id":    order["id"],
        "amount":      amount_paise,
        "currency":    "INR",
        "key_id":      RAZORPAY_KEY_ID,
        "description": description,
    }


# ── Verify Payment Signature ─────────────────────────────────────────────────

def verify_payment_signature(
    razorpay_order_id:   str,
    razorpay_payment_id: str,
    razorpay_signature:  str,
) -> bool:
    """
    Verify HMAC SHA256 signature returned by Razorpay checkout.
    Returns True if signature is valid.
    """
    message = f"{razorpay_order_id}|{razorpay_payment_id}"
    expected = hmac.new(
        RAZORPAY_KEY_SECRET.encode("utf-8"),
        message.encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()
    return hmac.compare_digest(expected, razorpay_signature)


# ── Save Booking Record ───────────────────────────────────────────────────────

def save_booking(
    db_session,
    BookingModel,
    user_id:       int,
    booking_type:  str,
    destination:   str,
    amount_inr:    float,
    payment_id:    str,
    order_id:      str,
    details:       dict,
) -> dict:
    """
    Persist a confirmed booking to the database.

    Returns the booking summary dict.
    """
    reference = f"TS-{uuid.uuid4().hex[:8].upper()}"

    booking = BookingModel(
        user_id      = user_id,
        booking_type = booking_type,
        destination  = destination,
        amount_inr   = amount_inr,
        payment_id   = payment_id,
        order_id     = order_id,
        reference    = reference,
        details_json = json.dumps(details),
        created_at   = datetime.utcnow(),
    )
    db_session.add(booking)
    db_session.commit()

    logger.info(
        "Booking saved: ref=%s  type=%s  dest=%s  ₹%.2f  user=%s",
        reference, booking_type, destination, amount_inr, user_id,
    )

    return {
        "reference":    reference,
        "booking_type": booking_type,
        "destination":  destination,
        "amount_inr":   amount_inr,
        "payment_id":   payment_id,
        "created_at":   booking.created_at.isoformat(),
        "status":       "confirmed",
    }
