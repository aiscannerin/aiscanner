import logging

from flask import Blueprint, request, current_app

from app.extensions import limiter
from app.middleware.auth_guard import require_auth
from app.services import auth_service
from app.utils.response import error, success

logger = logging.getLogger(__name__)

auth_bp = Blueprint("auth", __name__)


@auth_bp.post("/register")
@limiter.limit("10 per hour")
def register():
    data = request.get_json(silent=True) or {}
    return auth_service.register_user(data)


@auth_bp.post("/send-otp")
@limiter.limit("5 per hour")
def send_otp():
    data = request.get_json(silent=True) or {}
    return auth_service.send_otp(data)


@auth_bp.post("/verify-otp")
@limiter.limit("10 per hour")
def verify_otp():
    data = request.get_json(silent=True) or {}
    return auth_service.verify_otp(data)


@auth_bp.post("/login")
@limiter.limit("20 per hour")
def login():
    data = request.get_json(silent=True) or {}
    logger.info(
        "[ROUTE /login] email=%s has_password=%s",
        (data.get("email") or "")[:40],
        bool(data.get("password")),
    )
    return auth_service.login_user(data)


@auth_bp.post("/refresh")
@limiter.limit("30 per hour")
def refresh():
    data = request.get_json(silent=True) or {}
    return auth_service.refresh_access_token(data)


@auth_bp.post("/logout")
@require_auth
def logout():
    data = request.get_json(silent=True) or {}
    return auth_service.logout_user(data)


@auth_bp.get("/me")
@require_auth
def me():
    return auth_service.get_current_user()


@auth_bp.post("/forgot-password")
@limiter.limit("5 per hour")
def forgot_password():
    data = request.get_json(silent=True) or {}
    return auth_service.forgot_password(data)


@auth_bp.post("/reset-password")
@limiter.limit("10 per hour")
def reset_password():
    data = request.get_json(silent=True) or {}
    return auth_service.reset_password(data)


# ── Debug endpoint (development only) ────────────────────────────────────────
# Returns auth system status, JWT config, DB connectivity, and an optional
# user lookup so you can diagnose login failures without needing psql access.
#
# REMOVE or gate behind an admin role before going to production.
#
# Usage:
#   GET /api/auth/debug
#   GET /api/auth/debug?email=user@example.com   ← also tests user lookup

@auth_bp.get("/debug")
def debug_auth():
    """
    Temporary diagnostic endpoint.
    Returns:
      - Flask/JWT config values (secrets redacted)
      - Database connectivity
      - Optional user lookup (pass ?email=... to test)
    """
    from datetime import datetime, timezone
    from app.extensions import db
    from app.repositories import user_repository

    report = {}

    # ── JWT config ────────────────────────────────────────────────────────────
    jwt_secret = current_app.config.get("JWT_SECRET_KEY", "")
    report["jwt"] = {
        "secret_key_set":          bool(jwt_secret),
        "secret_key_length":       len(jwt_secret),
        "token_location":          current_app.config.get("JWT_TOKEN_LOCATION"),
        "header_name":             current_app.config.get("JWT_HEADER_NAME"),
        "header_type":             current_app.config.get("JWT_HEADER_TYPE"),
        "access_token_expires":    str(current_app.config.get("JWT_ACCESS_TOKEN_EXPIRES")),
        "refresh_token_expires":   str(current_app.config.get("JWT_REFRESH_TOKEN_EXPIRES")),
    }

    # ── Database connectivity ─────────────────────────────────────────────────
    try:
        db.session.execute(db.text("SELECT 1"))
        report["database"] = {"connected": True, "error": None}
    except Exception as exc:
        report["database"] = {"connected": False, "error": str(exc)}

    # ── CORS config ───────────────────────────────────────────────────────────
    report["cors"] = {
        "origins": current_app.config.get("CORS_ORIGINS"),
    }

    # ── Optional user lookup ──────────────────────────────────────────────────
    email = (request.args.get("email") or "").strip().lower()
    if email:
        try:
            user = user_repository.get_by_email(email)
            if user:
                report["user_lookup"] = {
                    "found":          True,
                    "id":             str(user.id),
                    "email":          user.email,
                    "is_active":      user.is_active,
                    "email_verified": user.email_verified,
                    "has_password_hash": bool(user.password_hash),
                    "password_hash_prefix": (user.password_hash or "")[:7],
                    "role":           user.role.name if user.role else None,
                    "created_at":     user.created_at.isoformat(),
                }
            else:
                report["user_lookup"] = {"found": False, "email": email}
        except Exception as exc:
            report["user_lookup"] = {"found": None, "error": str(exc)}

    report["generated_at"] = datetime.now(timezone.utc).isoformat()

    logger.info("[DEBUG] Auth debug endpoint called (email_query=%s)", email or "none")
    return success(data=report, message="Auth debug report")
