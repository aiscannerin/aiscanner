from datetime import datetime, timezone

from app.extensions import db
from app.models.otp_verification import OtpVerification


def create(
    email: str,
    otp_hash: str,
    purpose: str,
    expires_at: datetime,
    user_id=None,
) -> OtpVerification:
    otp = OtpVerification(
        user_id=user_id,
        email=email.strip().lower(),
        otp_hash=otp_hash,
        purpose=purpose,
        expires_at=expires_at,
        attempts=0,
    )
    db.session.add(otp)
    db.session.commit()
    return otp


def get_latest_valid(email: str, purpose: str) -> OtpVerification | None:
    """
    Return the most recently created, unverified OTP for this email + purpose.
    Expired records are included here — expiry is checked in the service layer
    so callers can return the correct error message.
    """
    return db.session.execute(
        db.select(OtpVerification)
        .where(
            OtpVerification.email == email.strip().lower(),
            OtpVerification.purpose == purpose,
            OtpVerification.verified_at.is_(None),
        )
        .order_by(OtpVerification.created_at.desc())
        .limit(1)
    ).scalar_one_or_none()


def increment_attempts(otp: OtpVerification) -> None:
    otp.attempts += 1
    db.session.commit()


def mark_verified(otp: OtpVerification) -> None:
    """Mark OTP as used. Called only after bcrypt check passes."""
    otp.verified_at = datetime.now(timezone.utc)
    db.session.commit()
