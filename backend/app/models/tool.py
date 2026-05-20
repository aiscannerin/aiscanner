import uuid
from datetime import datetime, timezone

from app.extensions import db


class ToolSlug:
    STOP_HUNT_SCANNER = "stop-hunt-scanner"
    # Add future scanner slugs here


class Tool(db.Model):
    __tablename__ = "tools"

    id = db.Column(
        db.UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
        nullable=False,
    )
    slug = db.Column(db.String(100), unique=True, nullable=False)
    name = db.Column(db.String(150), nullable=False)
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
        back_populates="tool",
        cascade="all, delete-orphan",
    )
    scan_jobs = db.relationship("ScanJob", back_populates="tool")

    def __repr__(self):
        return f"<Tool {self.slug}>"

    def to_dict(self):
        return {
            "id": str(self.id),
            "slug": self.slug,
            "name": self.name,
            "description": self.description,
            "is_active": self.is_active,
        }
