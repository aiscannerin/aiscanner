import uuid
from datetime import datetime, timezone

from app.extensions import db


class BillingCycle:
    FREE = "free"
    MONTHLY = "monthly"
    YEARLY = "yearly"
    ALL = [FREE, MONTHLY, YEARLY]


class SubscriptionStatus:
    ACTIVE = "active"
    EXPIRED = "expired"
    CANCELLED = "cancelled"
    PAYMENT_PENDING = "payment_pending"
    ALL = [ACTIVE, EXPIRED, CANCELLED, PAYMENT_PENDING]


class Subscription(db.Model):
    __tablename__ = "subscriptions"

    __table_args__ = (
        db.Index("ix_subscriptions_user_status_expiry", "user_id", "status", "expiry_date"),
    )

    id = db.Column(
        db.UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
        nullable=False,
    )
    user_id = db.Column(
        db.UUID(as_uuid=True),
        db.ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
    )
    plan_id = db.Column(
        db.UUID(as_uuid=True),
        db.ForeignKey("plans.id", ondelete="RESTRICT"),
        nullable=False,
    )
    billing_cycle = db.Column(db.String(20), nullable=False)
    start_date = db.Column(db.DateTime(timezone=True), nullable=False)
    # Null means never expires (Free plan)
    expiry_date = db.Column(db.DateTime(timezone=True), nullable=True)
    status = db.Column(
        db.String(20),
        nullable=False,
        default=SubscriptionStatus.ACTIVE,
    )
    # Populated only for Razorpay recurring subscriptions
    razorpay_subscription_id = db.Column(db.String(255), nullable=True)
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
    user = db.relationship("User", back_populates="subscriptions")
    plan = db.relationship("Plan", back_populates="subscriptions")
    payments = db.relationship("Payment", back_populates="subscription")

    @property
    def is_active_and_valid(self):
        if self.status != SubscriptionStatus.ACTIVE:
            return False
        if self.expiry_date is None:
            return True  # Free plan never expires
        return datetime.now(timezone.utc) < self.expiry_date

    def __repr__(self):
        return f"<Subscription user={self.user_id} plan={self.plan_id} status={self.status}>"

    def to_dict(self):
        return {
            "id": str(self.id),
            "user_id": str(self.user_id),
            "plan": self.plan.to_dict() if self.plan else None,
            "billing_cycle": self.billing_cycle,
            "start_date": self.start_date.isoformat(),
            "expiry_date": self.expiry_date.isoformat() if self.expiry_date else None,
            "status": self.status,
            "razorpay_subscription_id": self.razorpay_subscription_id,
            "created_at": self.created_at.isoformat(),
        }
