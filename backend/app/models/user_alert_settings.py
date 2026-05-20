import uuid
from datetime import datetime, timezone

from app.extensions import db


class UserAlertSettings(db.Model):
    __tablename__ = "user_alert_settings"

    __table_args__ = (
        db.UniqueConstraint("user_id", name="uq_alert_settings_user_id"),
        db.Index("ix_alert_settings_user_id", "user_id"),
    )

    id                   = db.Column(db.UUID(as_uuid=True), primary_key=True,
                                     default=uuid.uuid4, nullable=False)
    user_id              = db.Column(db.UUID(as_uuid=True),
                                     db.ForeignKey("users.id", ondelete="CASCADE"),
                                     nullable=True)
    email_alerts_enabled = db.Column(db.Boolean(), nullable=False, default=False)
    email_address        = db.Column(db.String(254), nullable=True)

    created_at = db.Column(db.DateTime(timezone=True), nullable=False,
                           default=lambda: datetime.now(timezone.utc))
    updated_at = db.Column(db.DateTime(timezone=True), nullable=False,
                           default=lambda: datetime.now(timezone.utc),
                           onupdate=lambda: datetime.now(timezone.utc))

    def __repr__(self):
        return (f"<UserAlertSettings user={self.user_id} "
                f"email_alerts={self.email_alerts_enabled}>")

    def to_dict(self):
        return {
            "id":                   str(self.id),
            "user_id":              str(self.user_id) if self.user_id else None,
            "email_alerts_enabled": self.email_alerts_enabled,
            "email_address":        self.email_address,
            "updated_at":           self.updated_at.isoformat(),
        }
