from flask import Blueprint, g, jsonify, request

from app.extensions import limiter
from app.middleware.auth_guard import require_auth
from app.services import payment_service
from app.utils.response import success

payments_bp = Blueprint("payments", __name__)


@payments_bp.post("/create-order")
@require_auth
@limiter.limit("10 per hour")
def create_order():
    data = request.get_json(silent=True) or {}
    return payment_service.create_order(g.current_user, data)


@payments_bp.post("/verify-payment")
@require_auth
@limiter.limit("10 per hour")
def verify_payment():
    data = request.get_json(silent=True) or {}
    return payment_service.verify_payment(g.current_user, data)


@payments_bp.post("/webhook")
def razorpay_webhook():
    # Raw bytes MUST be read before any JSON parsing — the signature is over
    # the unmodified body. Flask's get_data() returns bytes and does not consume
    # the stream for subsequent reads.
    raw_body = request.get_data()
    signature = request.headers.get("X-Razorpay-Signature", "")

    result, status_code = payment_service.handle_webhook(raw_body, signature)
    return jsonify(result), status_code


@payments_bp.get("/history")
@require_auth
def payment_history():
    payments = payment_service.get_payment_history(g.current_user.id)
    return success(data=payments)
