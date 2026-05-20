from flask import Blueprint

watchlist_bp = Blueprint("watchlist", __name__)

from app.api.watchlist import routes  # noqa: E402, F401
