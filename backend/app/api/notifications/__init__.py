from flask import Blueprint

notifications_bp = Blueprint("notifications", __name__)

from app.api.notifications import routes  # noqa: F401, E402
