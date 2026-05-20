import json
from datetime import datetime, timedelta, timezone

from flask import current_app

from app.extensions import db
from app.models.payment import PaymentStatus
from app.models.plan import PlanName
from app.models.subscription import BillingCycle
from app.repositories import payment_repository, plan_repository, subscription_repository
from app.services import razorpay_service
from app.utils.response import error, success


# ── Create Razorpay order ────────────────────────────────────────────────────────

def create_order(user, data: dict):
    plan_id = (data.get("plan_id") or "").strip()
    billing_cycle = (data.get("billing_cycle") or "").strip().lower()

    if not plan_id:
        return error("plan_id is required.", 400)
    if billing_cycle not in (BillingCycle.MONTHLY, BillingCycle.YEARLY):
        return error("billing_cycle must be 'monthly' or 'yearly'.", 400)

    plan = plan_repository.get_by_id(plan_id)
    if not plan or not plan.is_active:
        return error("Plan not found.", 404, error_code="PLAN_NOT_FOUND")
    if plan.name == PlanName.FREE:
        return error(
            "The Free plan cannot be purchased. It is assigned automatically on signup.",
            400,
            error_code="FREE_PLAN_NOT_PURCHASABLE",
        )

    amount = plan.monthly_price if billing_cycle == BillingCycle.MONTHLY else plan.yearly_price
    if amount <= 0:
        return error("Selected plan has no payable amount.", 400, error_code="INVALID_AMOUNT")

    # Razorpay requires amount in paise (INR × 100, as integer)
    amount_paise = int(amount * 100)

    try:
        rz_order = razorpay_service.create_order(amount_paise=amount_paise)
    except Exception as exc:
        current_app.logger.error("Razorpay create_order failed: %s", exc)
        return error("Failed to create payment order. Please try again.", 502, error_code="PAYMENT_GATEWAY_ERROR")

    payment = payment_repository.create(
        user_id=user.id,
        plan_id=plan.id,
        billing_cycle=billing_cycle,
        razorpay_order_id=rz_order["id"],
        amount=float(amount),
        currency=rz_order.get("currency", "INR"),
    )

    return success(
        data={
            "key_id": current_app.config["RAZORPAY_KEY_ID"],
            "order_id": rz_order["id"],
            "amount": amount_paise,
            "currency": rz_order.get("currency", "INR"),
            "plan": plan.to_dict(),
            "billing_cycle": billing_cycle,
            "payment_id": str(payment.id),
        },
        message="Order created. Proceed with payment.",
        status_code=201,
    )


# ── Verify payment signature from frontend ───────────────────────────────────────

def verify_payment(user, data: dict):
    razorpay_order_id = (data.get("razorpay_order_id") or "").strip()
    razorpay_payment_id = (data.get("razorpay_payment_id") or "").strip()
    razorpay_signature = (data.get("razorpay_signature") or "").strip()

    if not razorpay_order_id or not razorpay_payment_id or not razorpay_signature:
        return error(
            "razorpay_order_id, razorpay_payment_id, and razorpay_signature are required.",
            400,
        )

    # ── Ownership: find payment row and verify it belongs to this user ────────────
    payment = payment_repository.get_by_razorpay_order_id(razorpay_order_id)
    if not payment:
        return error("Payment order not found.", 404, error_code="ORDER_NOT_FOUND")
    if str(payment.user_id) != str(user.id):
        return error("This order does not belong to your account.", 403, error_code="ORDER_OWNERSHIP_MISMATCH")

    # ── Idempotency: reject duplicate verification ────────────────────────────────
    if payment.status == PaymentStatus.PAID:
        return error(
            "This payment has already been verified.",
            409,
            error_code="PAYMENT_ALREADY_VERIFIED",
        )
    if payment.status == PaymentStatus.FAILED:
        return error(
            "This payment has failed. Please create a new order.",
            400,
            error_code="PAYMENT_FAILED",
        )

    # ── Signature verification ────────────────────────────────────────────────────
    signature_valid = razorpay_service.verify_payment_signature(
        razorpay_order_id=razorpay_order_id,
        razorpay_payment_id=razorpay_payment_id,
        razorpay_signature=razorpay_signature,
    )
    if not signature_valid:
        current_app.logger.warning(
            "Invalid Razorpay signature for order %s user %s",
            razorpay_order_id,
            user.id,
        )
        return error(
            "Payment signature verification failed.",
            400,
            error_code="SIGNATURE_INVALID",
        )

    # ── Activate subscription ─────────────────────────────────────────────────────
    start_date = datetime.now(timezone.utc)
    expiry_date = _compute_expiry(payment.billing_cycle, start_date)

    try:
        new_sub = subscription_repository.activate_paid_subscription(
            user_id=user.id,
            plan_id=payment.plan_id,
            billing_cycle=payment.billing_cycle,
            start_date=start_date,
            expiry_date=expiry_date,
        )
        # Link payment → subscription and mark paid in the same transaction
        payment.status = PaymentStatus.PAID
        payment.razorpay_payment_id = razorpay_payment_id
        payment.razorpay_signature = razorpay_signature
        payment.verified_at = datetime.now(timezone.utc)
        payment.subscription_id = new_sub.id
        db.session.commit()
    except Exception as exc:
        db.session.rollback()
        current_app.logger.error("verify_payment commit failed: %s", exc)
        return error("Payment verification failed due to a server error. Please contact support.", 500)

    return success(
        data={
            "subscription": new_sub.to_dict(),
            "payment": payment.to_dict(),
        },
        message="Payment verified. Your subscription is now active.",
    )


# ── Razorpay webhook handler ─────────────────────────────────────────────────────

def handle_webhook(raw_body: bytes, signature: str):
    """
    Entry point for POST /api/payments/webhook.
    raw_body must be the unmodified request bytes — not the parsed payload.
    Returns a plain tuple (response_body_str, status_code) — NOT a Flask response.
    Caller is responsible for returning an HTTP response.
    """
    # ── 1. Verify webhook signature ───────────────────────────────────────────────
    if not razorpay_service.verify_webhook_signature(raw_body, signature):
        current_app.logger.warning("Razorpay webhook: invalid signature.")
        return {"success": False, "message": "Invalid signature."}, 400

    try:
        payload = json.loads(raw_body)
    except (ValueError, TypeError):
        return {"success": False, "message": "Malformed payload."}, 400

    event = payload.get("event")
    webhook_event_id = payload.get("id")  # Razorpay event UUID

    # ── 2. Idempotency: skip if already processed ─────────────────────────────────
    if webhook_event_id:
        existing = payment_repository.get_by_webhook_event_id(webhook_event_id)
        if existing:
            current_app.logger.info("Duplicate webhook event %s — skipped.", webhook_event_id)
            return {"success": True, "message": "Already processed."}, 200

    # ── 3. Route by event type ────────────────────────────────────────────────────
    if event == "payment.captured":
        return _webhook_payment_captured(payload, webhook_event_id)

    if event == "payment.failed":
        return _webhook_payment_failed(payload, webhook_event_id)

    # Unknown event — acknowledge so Razorpay doesn't retry
    return {"success": True, "message": f"Event '{event}' not handled."}, 200


def _webhook_payment_captured(payload: dict, webhook_event_id: str):
    try:
        entity = payload["payload"]["payment"]["entity"]
        rz_order_id = entity["order_id"]
        rz_payment_id = entity["id"]
    except (KeyError, TypeError):
        return {"success": False, "message": "Malformed payment.captured payload."}, 400

    payment = payment_repository.get_by_razorpay_order_id(rz_order_id)
    if not payment:
        current_app.logger.warning("Webhook payment.captured: order %s not found.", rz_order_id)
        return {"success": True, "message": "Order not found — ignored."}, 200

    # If already paid via frontend verify, just stamp the event id and return
    if payment.status == PaymentStatus.PAID:
        if webhook_event_id:
            payment.webhook_event_id = webhook_event_id
            db.session.commit()
        return {"success": True, "message": "Already verified."}, 200

    start_date = datetime.now(timezone.utc)
    expiry_date = _compute_expiry(payment.billing_cycle, start_date)

    try:
        new_sub = subscription_repository.activate_paid_subscription(
            user_id=payment.user_id,
            plan_id=payment.plan_id,
            billing_cycle=payment.billing_cycle,
            start_date=start_date,
            expiry_date=expiry_date,
        )
        payment.status = PaymentStatus.PAID
        payment.razorpay_payment_id = rz_payment_id
        payment.verified_at = datetime.now(timezone.utc)
        payment.subscription_id = new_sub.id
        payment.webhook_event_id = webhook_event_id
        db.session.commit()
    except Exception as exc:
        db.session.rollback()
        current_app.logger.error("Webhook payment.captured commit failed: %s", exc)
        return {"success": False, "message": "DB error."}, 500

    return {"success": True, "message": "Subscription activated."}, 200


def _webhook_payment_failed(payload: dict, webhook_event_id: str):
    try:
        entity = payload["payload"]["payment"]["entity"]
        rz_order_id = entity["order_id"]
    except (KeyError, TypeError):
        return {"success": False, "message": "Malformed payment.failed payload."}, 400

    payment = payment_repository.get_by_razorpay_order_id(rz_order_id)
    if not payment:
        return {"success": True, "message": "Order not found — ignored."}, 200

    if payment.status not in (PaymentStatus.CREATED,):
        # Already processed (paid or failed) — stamp event id and ack
        if webhook_event_id:
            payment.webhook_event_id = webhook_event_id
            db.session.commit()
        return {"success": True, "message": "Already processed."}, 200

    try:
        payment.status = PaymentStatus.FAILED
        payment.webhook_event_id = webhook_event_id
        db.session.commit()
    except Exception as exc:
        db.session.rollback()
        current_app.logger.error("Webhook payment.failed commit failed: %s", exc)
        return {"success": False, "message": "DB error."}, 500

    return {"success": True, "message": "Payment marked failed."}, 200


# ── Payment history ───────────────────────────────────────────────────────────────

def get_payment_history(user_id) -> list:
    payments = payment_repository.get_user_payments(user_id)
    return [p.to_dict() for p in payments]


# ── Internal helpers ──────────────────────────────────────────────────────────────

def _compute_expiry(billing_cycle: str, start: datetime) -> datetime:
    if billing_cycle == BillingCycle.YEARLY:
        return start + timedelta(days=365)
    return start + timedelta(days=30)  # monthly
