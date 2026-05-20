"""
/api/alert-settings — user-level alert preferences

GET   /api/alert-settings      return current settings (creates defaults if none)
PATCH /api/alert-settings      update email_alerts_enabled and/or email_address
"""
import re

from flask import g, request

from app.api.alert_settings import alert_settings_bp
from app.middleware.auth_guard import require_auth
from app.repositories import user_alert_settings_repository as repo
from app.utils.response import error, success

_EMAIL_RE = re.compile(r'^[^\s@]+@[^\s@]+\.[^\s@]+$')


@alert_settings_bp.get("")
@require_auth
def get_settings():
    settings = repo.get_or_create(g.current_user.id)
    from app.extensions import db
    db.session.commit()   # flush any auto-created row
    return success(data=settings.to_dict())


@alert_settings_bp.patch("")
@require_auth
def update_settings():
    body = request.get_json(silent=True) or {}

    email_alerts_enabled = body.get("email_alerts_enabled")
    email_address        = body.get("email_address", ...)   # sentinel: not provided

    # Validate types
    if email_alerts_enabled is not None and not isinstance(email_alerts_enabled, bool):
        return error("email_alerts_enabled must be a boolean.", 400)

    if email_address is not ...:
        if email_address and not _EMAIL_RE.match(str(email_address).strip()):
            return error("Invalid email address format.", 400,
                         error_code="INVALID_EMAIL")

    settings = repo.upsert(
        g.current_user.id,
        email_alerts_enabled = email_alerts_enabled,
        email_address        = email_address,
    )
    return success(message="Alert settings updated.", data=settings.to_dict())
