from app.extensions import db
from app.models.payment import Payment, PaymentStatus


def create(
    user_id,
    plan_id,
    billing_cycle: str,
    razorpay_order_id: str,
    amount: float,
    currency: str = "INR",
) -> Payment:
    payment = Payment(
        user_id=user_id,
        plan_id=plan_id,
        billing_cycle=billing_cycle,
        razorpay_order_id=razorpay_order_id,
        amount=amount,
        currency=currency,
        status=PaymentStatus.CREATED,
    )
    db.session.add(payment)
    db.session.commit()
    return payment


def get_by_razorpay_order_id(order_id: str) -> Payment | None:
    return db.session.execute(
        db.select(Payment).where(Payment.razorpay_order_id == order_id)
    ).scalar_one_or_none()


def get_by_webhook_event_id(event_id: str) -> Payment | None:
    return db.session.execute(
        db.select(Payment).where(Payment.webhook_event_id == event_id)
    ).scalar_one_or_none()


def get_user_payments(user_id) -> list[Payment]:
    return db.session.execute(
        db.select(Payment)
        .where(Payment.user_id == user_id)
        .order_by(Payment.created_at.desc())
    ).scalars().all()
