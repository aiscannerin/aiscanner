"""
/api/broker — per-user broker (Dhan) API credential management

GET    /api/broker/dhan          current connection status (no token returned)
PUT    /api/broker/dhan          save/update credentials (client_id + access_token)
POST   /api/broker/dhan/test     re-validate stored credentials
DELETE /api/broker/dhan          disconnect (delete stored credentials)
"""

import logging

from flask import g, request

from app.api.broker import broker_bp
from app.middleware.auth_guard import require_auth
from app.services import broker_credential_service as svc
from app.utils.response import error, success

logger = logging.getLogger(__name__)

_BROKER = "dhan"


@broker_bp.get("/api/broker/dhan")
@require_auth
def get_dhan_status():
    return success(data=svc.get_status(g.current_user.id, _BROKER))


@broker_bp.put("/api/broker/dhan")
@require_auth
def save_dhan():
    body = request.get_json(silent=True) or {}
    client_id    = body.get("client_id")
    access_token = body.get("access_token")
    try:
        status = svc.save(g.current_user.id, client_id, access_token, _BROKER)
    except ValueError as exc:
        return error(str(exc), 400, error_code="INVALID_CREDENTIALS")
    except Exception as exc:
        logger.error("[BROKER] save failed: %s", exc, exc_info=True)
        return error("Could not save credentials. Please try again.", 500)

    if status.get("is_valid"):
        return success(message="Dhan account connected and verified.", data=status)
    return success(
        message=(
            "Credentials saved, but verification failed: "
            f"{status.get('last_error') or 'unknown error'}. "
            "Double-check your Client ID and Access Token."
        ),
        data=status,
    )


@broker_bp.post("/api/broker/dhan/test")
@require_auth
def test_dhan():
    res = svc.test(g.current_user.id, _BROKER)
    if res["valid"]:
        return success(message="Connection OK.", data=res)
    return error(
        res.get("error") or "Verification failed.",
        400,
        error_code="DHAN_INVALID",
    )


@broker_bp.delete("/api/broker/dhan")
@require_auth
def delete_dhan():
    removed = svc.remove(g.current_user.id, _BROKER)
    if not removed:
        return error("No Dhan account connected.", 404)
    return success(message="Dhan account disconnected.")
