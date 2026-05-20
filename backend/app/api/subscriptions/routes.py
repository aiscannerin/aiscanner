from flask import Blueprint, g

from app.middleware.auth_guard import require_auth
from app.services.subscription_service import get_current_subscription_detail
from app.utils.response import success

subscriptions_bp = Blueprint("subscriptions", __name__)


@subscriptions_bp.get("/current")
@require_auth
def current_subscription():
    detail = get_current_subscription_detail(g.current_user.id)
    return success(data=detail)
