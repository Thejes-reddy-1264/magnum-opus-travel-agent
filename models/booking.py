"""
models/booking.py
SQLAlchemy model for storing confirmed trip bookings.
"""

from datetime import datetime
from database import db


class Booking(db.Model):
    __tablename__ = "bookings"

    id           = db.Column(db.Integer, primary_key=True)
    user_id      = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False)
    booking_type = db.Column(db.String(32), nullable=False)   # hotel | transport | restaurant | trip
    destination  = db.Column(db.String(120), nullable=False)
    amount_inr   = db.Column(db.Float, nullable=False)
    payment_id   = db.Column(db.String(64), nullable=True)    # Razorpay payment_id
    order_id     = db.Column(db.String(64), nullable=True)    # Razorpay order_id
    reference    = db.Column(db.String(20), unique=True, nullable=False)
    details_json = db.Column(db.Text, nullable=True)
    created_at   = db.Column(db.DateTime, default=datetime.utcnow)

    def to_dict(self):
        import json
        return {
            "id":           self.id,
            "booking_type": self.booking_type,
            "destination":  self.destination,
            "amount_inr":   self.amount_inr,
            "reference":    self.reference,
            "payment_id":   self.payment_id,
            "created_at":   self.created_at.isoformat() if self.created_at else None,
            "status":       "confirmed",
        }
