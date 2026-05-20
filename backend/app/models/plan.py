import uuid
from datetime import datetime, timezone

from app.extensions import db


class PlanName:
    FREE = "Free"
    PRO = "Pro"
    EXPERT = "Expert"
    ALL = [FREE, PRO, EXPERT]


class Plan(db.Model):
    __tablename__ = "plans"

    id = db.Column(
        db.UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
        nullable=False,
    )
    name = db.Column(db.String(50), unique=True, nullable=False)
    monthly_price = db.Column(db.Numeric(10, 2), nullable=False, default=0.00)
    yearly_price = db.Column(db.Numeric(10, 2), nullable=False, default=0.00)
    description = db.Column(db.Text, nullable=True)
    is_active = db.Column(db.Boolean, nullable=False, default=True)
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
    plan_tool_maps = db.relationship(
        "PlanToolMap",
        back_populates="plan",
        cascade="all, delete-orphan",
    )
    subscriptions = db.relationship("Subscription", back_populates="plan")

    def __repr__(self):
        return f"<Plan {self.name}>"

    def to_dict(self):
        return {
            "id": str(self.id),
            "name": self.name,
            "monthly_price": float(self.monthly_price),
            "yearly_price": float(self.yearly_price),
            "description": self.description,
            "is_active": self.is_active,
        }
