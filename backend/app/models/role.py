import uuid
from datetime import datetime, timezone

from app.extensions import db


class RoleName:
    ADMIN = "admin"
    USER = "user"
    ALL = [ADMIN, USER]


class Role(db.Model):
    __tablename__ = "roles"

    id = db.Column(
        db.UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
        nullable=False,
    )
    name = db.Column(db.String(50), unique=True, nullable=False)
    description = db.Column(db.Text, nullable=True)
    created_at = db.Column(
        db.DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
    )

    # ── Relationships ───────────────────────────────────────────────────────────
    # lazy="dynamic" is deprecated in SQLAlchemy 2.x — use default lazy="select"
    users = db.relationship("User", back_populates="role")

    def __repr__(self):
        return f"<Role {self.name}>"

    def to_dict(self):
        return {
            "id": str(self.id),
            "name": self.name,
            "description": self.description,
        }
