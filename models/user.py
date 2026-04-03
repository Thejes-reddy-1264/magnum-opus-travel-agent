"""
models/user.py — SQLAlchemy User model for TripSense authentication.

Schema:
  - id          : Primary key
  - username    : Display name (unique)
  - email       : Login identifier (unique, lowercase)
  - password    : bcrypt hash of the user's password
  - preferences : JSON blob for travel preferences (budget, interests)
  - created_at  : Account creation timestamp
"""

import json
from datetime import datetime, timezone

from database import db


class User(db.Model):
    __tablename__ = "users"

    id          = db.Column(db.Integer, primary_key=True)
    username    = db.Column(db.String(80),  unique=True, nullable=False)
    email       = db.Column(db.String(120), unique=True, nullable=False, index=True)
    password    = db.Column(db.String(255), nullable=False)           # bcrypt hash
    _preferences = db.Column("preferences", db.Text, default="{}")   # stored as JSON string
    created_at  = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))

    # ── Preferences helper ────────────────────────────────────────────────────
    @property
    def preferences(self) -> dict:
        try:
            return json.loads(self._preferences or "{}")
        except (json.JSONDecodeError, TypeError):
            return {}

    @preferences.setter
    def preferences(self, value: dict):
        self._preferences = json.dumps(value or {})

    # ── Serialisation ─────────────────────────────────────────────────────────
    def to_dict(self) -> dict:
        """Safe public representation — never includes password."""
        return {
            "id":          self.id,
            "username":    self.username,
            "email":       self.email,
            "preferences": self.preferences,
            "created_at":  self.created_at.isoformat() if self.created_at else None,
        }

    def __repr__(self) -> str:
        return f"<User id={self.id} email={self.email!r}>"
