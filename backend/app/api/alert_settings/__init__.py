from flask import Blueprint

alert_settings_bp = Blueprint("alert_settings", __name__)

from app.api.alert_settings import routes  # noqa: E402, F401
