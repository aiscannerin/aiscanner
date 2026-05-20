import uuid
from datetime import datetime, timezone

from app.extensions import db


class RefreshToken(db.Model):
    __tablename__ = "refresh_tokens"

    __table_args__ = (
        # unique enforced by named index only — no unique=True on column too
        db.Index("ix_refresh_tokens_token_hash", "token_hash", unique=True),
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
    # Only the SHA-256 hash of the raw token is stored — raw token stays client-side only
    token_hash = db.Column(db.String(64), nullable=False)
    expires_at = db.Column(db.DateTime(timezone=True), nullable=False)
    revoked = db.Column(db.Boolean, nullable=False, default=False)
    created_at = db.Column(
        db.DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
    )

    # ── Relationships ───────────────────────────────────────────────────────────
    user = db.relationship("User", back_populates="refresh_tokens")

    @property
    def is_valid(self):
        if self.revoked:
            return False
        return datetime.now(timezone.utc) < self.expires_at

    def __repr__(self):
        return f"<RefreshToken user={self.user_id} revoked={self.revoked}>"
