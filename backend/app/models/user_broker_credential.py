import uuid
from datetime import datetime, timezone

from app.extensions import db


class UserBrokerCredential(db.Model):
    """
    Per-user broker API credentials (currently Dhan only).

    The access token can place trades on the user's account, so it is stored
    ENCRYPTED at rest (see app.utils.crypto). client_id is not secret and is
    stored in plaintext for display.
    """
    __tablename__ = "user_broker_credentials"

    __table_args__ = (
        db.UniqueConstraint("user_id", "broker", name="uq_broker_cred_user_broker"),
        db.Index("ix_broker_cred_user_id", "user_id"),
    )

    id = db.Column(db.UUID(as_uuid=True), primary_key=True,
                   default=uuid.uuid4, nullable=False)
    user_id = db.Column(db.UUID(as_uuid=True),
                        db.ForeignKey("users.id", ondelete="CASCADE"),
                        nullable=False)

    broker = db.Column(db.String(20), nullable=False, default="dhan")

    client_id = db.Column(db.String(50), nullable=False)
    # Fernet-encrypted access token — never stored or returned in plaintext
    access_token_encrypted = db.Column(db.Text, nullable=False)

    # Validation state (set when we test the token against Dhan)
    is_valid          = db.Column(db.Boolean, nullable=False, default=False)
    last_validated_at = db.Column(db.DateTime(timezone=True), nullable=True)
    last_error        = db.Column(db.String(255), nullable=True)

    created_at = db.Column(db.DateTime(timezone=True), nullable=False,
                           default=lambda: datetime.now(timezone.utc))
    updated_at = db.Column(db.DateTime(timezone=True), nullable=False,
                           default=lambda: datetime.now(timezone.utc),
                           onupdate=lambda: datetime.now(timezone.utc))

    def __repr__(self):
        return f"<UserBrokerCredential user={self.user_id} broker={self.broker} valid={self.is_valid}>"

    def to_dict(self):
        """Safe public representation — NEVER includes the access token."""
        return {
            "broker":            self.broker,
            "client_id":         self.client_id,
            "connected":         True,
            "is_valid":          self.is_valid,
            "last_validated_at":  self.last_validated_at.isoformat() if self.last_validated_at else None,
            "last_error":        self.last_error,
            "updated_at":        self.updated_at.isoformat(),
        }
