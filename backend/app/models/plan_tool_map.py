import uuid
from datetime import datetime, timezone

from app.extensions import db


class PlanToolMap(db.Model):
    __tablename__ = "plan_tool_map"

    __table_args__ = (
        db.Index("ix_plan_tool_map_plan_tool", "plan_id", "tool_id", unique=True),
    )

    id = db.Column(
        db.UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
        nullable=False,
    )
    plan_id = db.Column(
        db.UUID(as_uuid=True),
        db.ForeignKey("plans.id", ondelete="CASCADE"),
        nullable=False,
    )
    tool_id = db.Column(
        db.UUID(as_uuid=True),
        db.ForeignKey("tools.id", ondelete="CASCADE"),
        nullable=False,
    )
    created_at = db.Column(
        db.DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
    )

    # ── Relationships ───────────────────────────────────────────────────────────
    plan = db.relationship("Plan", back_populates="plan_tool_maps")
    tool = db.relationship("Tool", back_populates="plan_tool_maps")

    def __repr__(self):
        return f"<PlanToolMap plan={self.plan_id} tool={self.tool_id}>"

    def to_dict(self):
        return {
            "id": str(self.id),
            "plan_id": str(self.plan_id),
            "tool_id": str(self.tool_id),
            "tool": self.tool.to_dict() if self.tool else None,
        }
