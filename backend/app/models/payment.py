import uuid
from datetime import datetime, timezone

from app.extensions import db


class PaymentStatus:
    CREATED = "created"
    PAID = "paid"
    FAILED = "failed"
    REFUNDED = "refunded"
    ALL = [CREATED, PAID, FAILED, REFUNDED]


class Payment(db.Model):
    __tablename__ = "payments"

    __table_args__ = (
        # razorpay_order_id: unique index only here — no unique=True on column too
        db.Index("ix_payments_razorpay_order_id", "razorpay_order_id", unique=True),
        db.Index("ix_payments_razorpay_payment_id", "razorpay_payment_id"),
        db.Index("ix_payments_webhook_event_id", "webhook_event_id"),
    )

    id = db.Column(
        db.UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
        nullable=False,
    )
    user_id = db.Column(
        db.UUID(as_uuid=True),
        db.ForeignKey("users.id", ondelete="RESTRICT"),
        nullable=False,
    )
    # Nullable until payment is confirmed and subscription activated
    subscription_id = db.Column(
        db.UUID(as_uuid=True),
        db.ForeignKey("subscriptions.id", ondelete="SET NULL"),
        nullable=True,
    )
    plan_id = db.Column(
        db.UUID(as_uuid=True),
        db.ForeignKey("plans.id", ondelete="RESTRICT"),
        nullable=False,
    )
    billing_cycle = db.Column(db.String(20), nullable=False)
    # unique enforced by ix_payments_razorpay_order_id — not by column-level unique=True
    razorpay_order_id = db.Column(db.String(255), nullable=False)
    razorpay_payment_id = db.Column(db.String(255), nullable=True)
    razorpay_signature = db.Column(db.String(512), nullable=True)
    amount = db.Column(db.Numeric(10, 2), nullable=False)
    currency = db.Column(db.String(10), nullable=False, default="INR")
    status = db.Column(
        db.String(20),
        nullable=False,
        default=PaymentStatus.CREATED,
    )
    verified_at = db.Column(db.DateTime(timezone=True), nullable=True)
    # Stores Razorpay webhook event ID — checked before processing to prevent duplicate handling
    webhook_event_id = db.Column(db.String(255), nullable=True)
    created_at = db.Column(
        db.DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
    )
    updated_at = db.Column(
        db.DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )

    # ── Relationships ───────────────────────────────────────────────────────────
    user = db.relationship("User", back_populates="payments")
    subscription = db.relationship("Subscription", back_populates="payments")
    plan = db.relationship("Plan")

    def __repr__(self):
        return f"<Payment {self.razorpay_order_id} status={self.status}>"

    def to_dict(self):
        return {
            "id": str(self.id),
            "user_id": str(self.user_id),
            "plan": self.plan.to_dict() if self.plan else None,
            "billing_cycle": self.billing_cycle,
            "razorpay_order_id": self.razorpay_order_id,
            "razorpay_payment_id": self.razorpay_payment_id,
            "amount": float(self.amount),
            "currency": self.currency,
            "status": self.status,
            "verified_at": self.verified_at.isoformat() if self.verified_at else None,
            "created_at": self.created_at.isoformat(),
        }
