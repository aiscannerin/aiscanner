import uuid
from datetime import datetime, timezone

from app.extensions import db


# Notification types that are supported
class NotificationType:
    BECAME_CONFIRMED  = "became_confirmed"
    IMPROVED_LEVEL    = "improved_level"
    BECAME_WATCHLIST  = "became_watchlist"


class ScannerNotification(db.Model):
    __tablename__ = "scanner_notifications"

    __table_args__ = (
        db.UniqueConstraint("scan_result_id",
                            name="uq_notification_scan_result_id"),
        db.UniqueConstraint("symbol", "notification_type", "scan_run_id",
                            name="uq_notification_symbol_type_run"),
        db.Index("ix_notif_user_read",  "user_id",  "is_read"),
        db.Index("ix_notif_created_at", "created_at"),
        db.Index("ix_notif_symbol",     "symbol"),
    )

    id                = db.Column(db.UUID(as_uuid=True), primary_key=True,
                                  default=uuid.uuid4, nullable=False)
    user_id           = db.Column(db.UUID(as_uuid=True),
                                  db.ForeignKey("users.id", ondelete="CASCADE"),
                                  nullable=True)
    scan_run_id       = db.Column(db.UUID(as_uuid=True),
                                  db.ForeignKey("scan_jobs.id", ondelete="SET NULL"),
                                  nullable=True)
    scan_result_id    = db.Column(db.UUID(as_uuid=True),
                                  db.ForeignKey("scan_results.id", ondelete="SET NULL"),
                                  nullable=True)
    symbol            = db.Column(db.String(50),  nullable=False)
    notification_type = db.Column(db.String(50),  nullable=False)
    title             = db.Column(db.String(200), nullable=False)
    message           = db.Column(db.Text,        nullable=False)
    priority          = db.Column(db.Integer,     nullable=False, default=0)
    is_read           = db.Column(db.Boolean,     nullable=False, default=False)
    # "global"  → created because progression_priority >= global threshold
    # "tracked" → created because symbol is tracked AND alert preference allows it
    notification_scope = db.Column(db.String(20), nullable=False, default="global")
    email_sent         = db.Column(db.Boolean(),              nullable=False, default=False)
    email_sent_at      = db.Column(db.DateTime(timezone=True), nullable=True)
    email_error        = db.Column(db.String(200),             nullable=True)
    created_at        = db.Column(db.DateTime(timezone=True), nullable=False,
                                  default=lambda: datetime.now(timezone.utc))

    def __repr__(self):
        return f"<ScannerNotification {self.symbol} {self.notification_type} read={self.is_read}>"

    def to_dict(self):
        return {
            "id":                str(self.id),
            "user_id":           str(self.user_id) if self.user_id else None,
            "scan_run_id":       str(self.scan_run_id)    if self.scan_run_id    else None,
            "scan_result_id":    str(self.scan_result_id) if self.scan_result_id else None,
            "symbol":            self.symbol,
            "notification_type": self.notification_type,
            "title":             self.title,
            "message":           self.message,
            "priority":          self.priority,
            "is_read":              self.is_read,
            "notification_scope":   self.notification_scope,
            "email_sent":           self.email_sent,
            "email_sent_at":        self.email_sent_at.isoformat() if self.email_sent_at else None,
            "email_error":          self.email_error,
            "created_at":           self.created_at.isoformat(),
        }
