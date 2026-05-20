from flask import Blueprint

scans_bp = Blueprint("scans", __name__)

from app.api.scans import routes  # noqa: F401, E402
