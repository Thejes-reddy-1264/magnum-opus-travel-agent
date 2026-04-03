"""
database.py — Shared SQLAlchemy db instance.

Import `db` here to avoid circular imports between app.py and models.
"""

from flask_sqlalchemy import SQLAlchemy

db = SQLAlchemy()
