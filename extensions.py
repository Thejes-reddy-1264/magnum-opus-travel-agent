"""
extensions.py — Flask extensions (bcrypt, jwt).

Instantiated here to avoid circular imports.
Import from here, not from app.py.
"""

from flask_bcrypt import Bcrypt
from flask_jwt_extended import JWTManager

bcrypt = Bcrypt()
jwt    = JWTManager()
