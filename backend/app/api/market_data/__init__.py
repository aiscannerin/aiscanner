from flask import Blueprint

market_data_bp = Blueprint("market_data", __name__)

from app.api.market_data import routes  # noqa: E402, F401
