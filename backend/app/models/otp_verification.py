import uuid
from datetime import datetime, timezone

from app.extensions import db

OTP_MAX_ATTEMPTS_DEFAULT = 5


class OtpPurpose:
    SIGNUP = "signup"
    FORGOT_PASSWORD = "forgot_password"
    EMAIL_CHANGE = "email_change"
    ALL = [SIGNUP, FORGOT_PASSWORD, EMAIL_CHANGE]


class OtpVerification(db.Model):
    __tablename__ = "otp_verifications"

    __table_args__ = (
        db.Index("ix_otp_email_purpose", "email", "purpose"),
    )

    id = db.Column(
        db.UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
        nullable=False,
    )
    # Nullable: signup OTPs are created before the user row exists
    user_id = db.Column(
        db.UUID(as_uuid=True),
        db.ForeignKey("users.id", ondelete="CASCADE"),
        nullable=True,
    )
    email = db.Column(db.String(255), nullable=False)
    otp_hash = db.Column(db.String(255), nullable=False)
    purpose = db.Column(db.String(30), nullable=False)
    expires_at = db.Column(db.DateTime(timezone=True), nullable=False)
    verified_at = db.Column(db.DateTime(timezone=True), nullable=True)
    attempts = db.Column(db.Integer, nullable=False, default=0)
    created_at = db.Column(
        db.DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
    )

    # ── Relationships ───────────────────────────────────────────────────────────
    user = db.relationship("User", back_populates="otp_verifications")

    @property
    def is_expired(self):
        return datetime.now(timezone.utc) > self.expires_at

    @property
    def is_verified(self):
        return self.verified_at is not None

    def is_exhausted(self, max_attempts: int = OTP_MAX_ATTEMPTS_DEFAULT) -> bool:
        """
        Accepts max_attempts as a parameter so callers can pass app.config value.
        Avoids importing current_app inside a model property (fragile outside request context).
        """
        return self.attempts >= max_attempts

    def __repr__(self):
        return f"<OtpVerification {self.email} [{self.purpose}]>"
