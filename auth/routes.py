"""
auth/routes.py — Authentication API endpoints.

Endpoints:
  POST /api/auth/register  — Create a new account
  POST /api/auth/login     — Login and receive a JWT
  GET  /api/auth/profile   — Protected: return logged-in user info
  PUT  /api/auth/preferences — Protected: save travel preferences
  POST /api/auth/logout    — Client-side logout (invalidate nothing server-side for JWT)
"""

import logging
import re

from flask import Blueprint, request, jsonify
from flask_jwt_extended import (
    create_access_token,
    jwt_required,
    get_jwt_identity,
)

from database import db
from models.user import User
from extensions import bcrypt

logger = logging.getLogger(__name__)

auth_bp = Blueprint("auth", __name__, url_prefix="/api/auth")

# ── Validation helpers ────────────────────────────────────────────────────────
EMAIL_RE = re.compile(r"^[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+$")
MIN_PASSWORD_LEN = 6
MAX_PASSWORD_LEN = 128
MAX_USERNAME_LEN = 50


def _validate_email(email: str) -> str | None:
    """Return error string or None if valid."""
    if not email or not EMAIL_RE.match(email):
        return "Please provide a valid email address."
    return None


def _validate_password(pw: str) -> str | None:
    if not pw or len(pw) < MIN_PASSWORD_LEN:
        return f"Password must be at least {MIN_PASSWORD_LEN} characters."
    if len(pw) > MAX_PASSWORD_LEN:
        return "Password is too long."
    return None


def _validate_username(un: str) -> str | None:
    if not un or len(un.strip()) < 2:
        return "Username must be at least 2 characters."
    if len(un) > MAX_USERNAME_LEN:
        return f"Username must be {MAX_USERNAME_LEN} characters or fewer."
    if not re.match(r"^[A-Za-z0-9_. -]+$", un):
        return "Username may only contain letters, numbers, spaces, underscores, dots, and hyphens."
    return None


# ── POST /api/auth/register ───────────────────────────────────────────────────
@auth_bp.route("/register", methods=["POST"])
def register():
    """Register a new user account."""
    body = request.get_json(silent=True)
    if not body:
        return jsonify({"error": "Request body must be valid JSON."}), 400

    username = (body.get("username") or "").strip()
    email    = (body.get("email")    or "").strip().lower()
    password = (body.get("password") or "")

    # Validate
    err = _validate_username(username)
    if err: return jsonify({"error": err, "field": "username"}), 422

    err = _validate_email(email)
    if err: return jsonify({"error": err, "field": "email"}), 422

    err = _validate_password(password)
    if err: return jsonify({"error": err, "field": "password"}), 422

    # Check for duplicates
    if User.query.filter_by(email=email).first():
        return jsonify({"error": "An account with that email already exists.", "field": "email"}), 409

    if User.query.filter_by(username=username).first():
        return jsonify({"error": "That username is already taken.", "field": "username"}), 409

    # Hash password and persist
    pw_hash = bcrypt.generate_password_hash(password).decode("utf-8")
    user = User(username=username, email=email, password=pw_hash)
    db.session.add(user)
    db.session.commit()

    # Issue JWT immediately so the user is logged in after registration
    token = create_access_token(identity=str(user.id))

    logger.info("New user registered: id=%d email=%s", user.id, email)
    return jsonify({
        "message": "Account created successfully. Welcome!",
        "token":   token,
        "user":    user.to_dict(),
    }), 201


# ── POST /api/auth/login ──────────────────────────────────────────────────────
@auth_bp.route("/login", methods=["POST"])
def login():
    """Authenticate user and return a JWT."""
    body = request.get_json(silent=True)
    if not body:
        return jsonify({"error": "Request body must be valid JSON."}), 400

    email    = (body.get("email")    or "").strip().lower()
    password = (body.get("password") or "")

    if not email or not password:
        return jsonify({"error": "Email and password are required."}), 400

    user = User.query.filter_by(email=email).first()

    # Constant-time comparison (bcrypt handles this) — don't reveal which field was wrong
    if not user or not bcrypt.check_password_hash(user.password, password):
        logger.warning("Failed login attempt for email=%s", email)
        return jsonify({"error": "Invalid email or password."}), 401

    token = create_access_token(identity=str(user.id))
    logger.info("User logged in: id=%d email=%s", user.id, email)

    return jsonify({
        "message": "Login successful.",
        "token":   token,
        "user":    user.to_dict(),
    }), 200


# ── GET /api/auth/profile (protected) ────────────────────────────────────────
@auth_bp.route("/profile", methods=["GET"])
@jwt_required()
def profile():
    """Return the currently authenticated user's profile."""
    user_id = int(get_jwt_identity())
    user = db.session.get(User, user_id)
    if not user:
        return jsonify({"error": "User not found."}), 404
    return jsonify({"user": user.to_dict()}), 200


# ── PUT /api/auth/preferences (protected) ────────────────────────────────────
@auth_bp.route("/preferences", methods=["PUT"])
@jwt_required()
def update_preferences():
    """Save or update travel preferences for the logged-in user."""
    user_id = int(get_jwt_identity())
    user = db.session.get(User, user_id)
    if not user:
        return jsonify({"error": "User not found."}), 404

    body = request.get_json(silent=True) or {}
    prefs = user.preferences  # existing prefs

    # Merge in allowed fields
    if "budget" in body and isinstance(body["budget"], str):
        prefs["budget"] = body["budget"].strip().lower()
    if "interests" in body and isinstance(body["interests"], list):
        prefs["interests"] = [str(i).lower() for i in body["interests"]][:7]
    if "default_city" in body and isinstance(body["default_city"], str):
        prefs["default_city"] = body["default_city"].strip()[:100]

    user.preferences = prefs
    db.session.commit()
    logger.info("Preferences updated for user id=%d", user_id)

    return jsonify({"message": "Preferences saved.", "preferences": user.preferences}), 200


# ── POST /api/auth/logout ─────────────────────────────────────────────────────
@auth_bp.route("/logout", methods=["POST"])
def logout():
    """
    JWT is stateless — actual logout happens client-side by deleting the token.
    This endpoint exists to give the frontend a clean API surface.
    """
    return jsonify({"message": "Logged out successfully."}), 200
