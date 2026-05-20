import os
from datetime import datetime, timezone

from flask import Blueprint, current_app
from sqlalchemy import text

from app.extensions import db, get_redis_client

health_bp = Blueprint("health", __name__)


@health_bp.route("/health")
def health():
    """
    Deep health check — actively probes DB and Redis.
    Returns HTTP 200 only when both services are reachable.
    Returns HTTP 503 if either service fails.
    Never hides real failures behind a fake "ok".
    """
    db_status, db_error = _check_database()
    redis_status, redis_error = _check_redis()

    all_healthy = db_status == "ok" and redis_status == "ok"
    http_status = 200 if all_healthy else 503

    payload = {
        "status": "ok" if all_healthy else "degraded",
        "service": "Stop Hunter Pro API",
        "environment": os.getenv("FLASK_ENV", "development"),
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "checks": {
            "database": {
                "status": db_status,
            },
            "redis": {
                "status": redis_status,
            },
        },
    }

    # Include error detail only when something is wrong
    if db_error:
        payload["checks"]["database"]["error"] = db_error
    if redis_error:
        payload["checks"]["redis"]["error"] = redis_error

    return payload, http_status


def _check_database() -> tuple[str, str | None]:
    """
    Execute SELECT 1 against the configured PostgreSQL database.
    Returns ("ok", None) on success or ("fail", "<reason>") on any error.
    """
    try:
        db.session.execute(text("SELECT 1"))
        return "ok", None
    except Exception as exc:
        current_app.logger.error("Health DB check failed: %s", exc)
        return "fail", str(exc)


def _check_redis() -> tuple[str, str | None]:
    """
    Send PING to Redis using the app-configured REDIS_URL.
    Returns ("ok", None) on success or ("fail", "<reason>") on any error.
    """
    try:
        client = get_redis_client(current_app._get_current_object())
        if not client.ping():
            return "fail", "Redis PING returned False"
        return "ok", None
    except Exception as exc:
        current_app.logger.error("Health Redis check failed: %s", exc)
        return "fail", str(exc)
