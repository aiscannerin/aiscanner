import os
from datetime import datetime, timedelta, timezone

from flask import current_app

from app.extensions import bcrypt
from app.repositories import otp_repository
from app.utils.security import generate_otp


def generate_and_send(email: str, purpose: str, user_id=None) -> None:
    """
    Generate a 6-digit OTP, bcrypt-hash it, persist it, then deliver it.
    Any previous unverified OTPs for the same email+purpose remain in the DB
    but are superseded — the service always validates against the latest record.

    Delivery (via _deliver) is intentionally called AFTER the hash is stored.
    A delivery failure never rolls back the stored OTP — the user can always
    request a resend, and the hash is never exposed.
    """
    expires_minutes = current_app.config.get("OTP_EXPIRES_MINUTES", 10)
    expires_at = datetime.now(timezone.utc) + timedelta(minutes=expires_minutes)

    otp_code = generate_otp(6)
    otp_hash = bcrypt.generate_password_hash(otp_code).decode("utf-8")

    otp_repository.create(
        email=email,
        otp_hash=otp_hash,
        purpose=purpose,
        expires_at=expires_at,
        user_id=user_id,
    )

    _deliver(email=email, otp_code=otp_code, purpose=purpose)


def _deliver(email: str, otp_code: str, purpose: str) -> None:
    """
    Deliver the OTP to the user.

    Logic:
      1. In development → always print OTP to console (safe fallback for local testing).
      2. If BREVO_ENABLED=true → attempt Brevo email delivery regardless of env.
         - On success in development: print confirmation (no OTP, no key).
         - On failure in development: log warning and fall through (console already printed).
         - On failure in production: log error. OTP is still stored — user can resend.
      3. In production with BREVO_ENABLED != true → log a warning (misconfiguration).

    Security guarantees:
      - otp_code is NEVER written to any log in production.
      - BREVO_API_KEY is NEVER passed to any logger.
      - The plain OTP is never returned to callers or stored anywhere except this stack frame.
    """
    is_dev      = os.getenv("FLASK_ENV", "development") == "development"
    brevo_on    = current_app.config.get("BREVO_ENABLED", False)

    # ── Step 1: development console print ────────────────────────────────────
    if is_dev:
        print(f"\n{'=' * 50}", flush=True)
        print(f"  DEV OTP for {email} [{purpose}]: {otp_code}", flush=True)
        print(f"{'=' * 50}\n", flush=True)

    # ── Step 2: Brevo delivery ────────────────────────────────────────────────
    if brevo_on:
        # Import inside function to guarantee no circular import risk.
        from app.services.email_service import send_otp_email  # noqa: PLC0415

        sent = send_otp_email(to_email=email, otp=otp_code, purpose=purpose)

        if sent:
            if is_dev:
                current_app.logger.debug(
                    "[otp_service] Brevo OTP email delivered to %s (%s)", email, purpose
                )
        else:
            if is_dev:
                current_app.logger.warning(
                    "[otp_service] Brevo delivery failed for %s (%s) — "
                    "console OTP is still available above.",
                    email, purpose,
                )
            else:
                # Production: delivery failed. OTP is still stored so the user
                # can request a resend. We log the failure for ops visibility
                # but do NOT expose details to the client.
                current_app.logger.error(
                    "[otp_service] Brevo delivery failed for %s (%s). "
                    "OTP stored — user can resend.",
                    email, purpose,
                )
        return

    # ── Step 3: production without Brevo configured ───────────────────────────
    if not is_dev:
        current_app.logger.warning(
            "[otp_service] BREVO_ENABLED is not set for %s (%s). "
            "OTP was not delivered. Set BREVO_ENABLED=true and configure "
            "BREVO_API_KEY / BREVO_SENDER_EMAIL.",
            email, purpose,
        )
