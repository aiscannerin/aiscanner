import logging
import bcrypt as _bcrypt_lib
from datetime import datetime, timedelta, timezone

from flask import current_app, g
from flask_jwt_extended import create_access_token, decode_token

logger = logging.getLogger(__name__)

from app.extensions import bcrypt, db
from app.models.otp_verification import OtpPurpose
from app.models.plan import PlanName
from app.models.role import RoleName
from app.models.subscription import BillingCycle, Subscription, SubscriptionStatus
from app.repositories import (
    otp_repository,
    refresh_token_repository,
    role_repository,
    subscription_repository,
    user_repository,
)
from app.services import otp_service
from app.utils.response import error, success
from app.utils.security import generate_secure_token, hash_token
from app.utils.validators import (
    VALID_GENDERS,
    VALID_TRADING_EXPERIENCE,
    validate_dob,
    validate_email,
    validate_gender,
    validate_password,
    validate_phone,
    validate_trading_experience,
    validate_username,
)

# Pre-computed at module load for timing-safe "user not found" login checks.
# rounds=4 is intentionally fast — this hash is never used for real security,
# only to make login response time consistent whether or not a user exists.
_TIMING_DUMMY_HASH = _bcrypt_lib.hashpw(
    b"__timing_safe_dummy__",
    _bcrypt_lib.gensalt(rounds=4),
)


# ── Register ────────────────────────────────────────────────────────────────────

def register_user(data: dict):
    full_name = (data.get("full_name") or "").strip()
    username = (data.get("username") or "").strip().lower()
    email = (data.get("email") or "").strip().lower()
    phone = (data.get("phone") or "").strip()
    dob = (data.get("dob") or "").strip()
    gender = (data.get("gender") or "").strip().lower()
    address = (data.get("address") or "").strip()
    trading_experience = (data.get("trading_experience") or "").strip().lower()
    password = data.get("password") or ""

    # ── Required presence check ──────────────────────────────────────────────────
    missing = [
        f for f, v in [
            ("full_name", full_name),
            ("username", username),
            ("email", email),
            ("phone", phone),
            ("dob", dob),
            ("gender", gender),
            ("address", address),
            ("trading_experience", trading_experience),
            ("password", password),
        ]
        if not v
    ]
    if missing:
        return error(
            "Missing required fields.",
            400,
            errors=[{"field": f, "message": "This field is required."} for f in missing],
        )

    # ── Field-level validation ───────────────────────────────────────────────────
    field_errors = []

    if not validate_username(username):
        field_errors.append({"field": "username", "message": "3–50 characters, letters, numbers, and underscores only."})

    if not validate_email(email):
        field_errors.append({"field": "email", "message": "Enter a valid email address."})

    if not validate_phone(phone):
        field_errors.append({"field": "phone", "message": "Enter a valid Indian mobile number (e.g. 9876543210 or +919876543210)."})

    if not validate_dob(dob):
        field_errors.append({"field": "dob", "message": "Enter a valid date in YYYY-MM-DD format."})

    if not validate_gender(gender):
        field_errors.append({"field": "gender", "message": f"Must be one of: {', '.join(sorted(VALID_GENDERS))}."})

    if len(address) < 5:
        field_errors.append({"field": "address", "message": "Address must be at least 5 characters."})

    if not validate_trading_experience(trading_experience):
        field_errors.append({"field": "trading_experience", "message": f"Must be one of: {', '.join(sorted(VALID_TRADING_EXPERIENCE))}."})

    pw_errors = validate_password(password)
    for msg in pw_errors:
        field_errors.append({"field": "password", "message": msg})

    if field_errors:
        return error("Validation failed.", 400, errors=field_errors)

    if user_repository.get_by_email(email):
        return error("An account with this email already exists.", 409, error_code="EMAIL_TAKEN")
    if user_repository.get_by_username(username):
        return error("This username is already taken.", 409, error_code="USERNAME_TAKEN")

    user_role = role_repository.get_by_name(RoleName.USER)
    if not user_role:
        return error(
            "System setup error: run `flask seed-db` before registering users.",
            500,
            error_code="SETUP_ERROR",
        )

    password_hash = bcrypt.generate_password_hash(password).decode("utf-8")

    user = user_repository.create(
        {
            "full_name": full_name,
            "username": username,
            "email": email,
            "password_hash": password_hash,
            "phone": phone,
            "dob": dob,
            "gender": gender,
            "address": address,
            "trading_experience": trading_experience,
            "role_id": user_role.id,
            "email_verified": False,
            "is_active": True,
        }
    )

    otp_service.generate_and_send(
        email=email,
        purpose=OtpPurpose.SIGNUP,
        user_id=user.id,
    )

    return success(
        data={"email": email},
        message="Registration successful. Check your email for the OTP to verify your account.",
        status_code=201,
    )


# ── Send OTP (resend) ────────────────────────────────────────────────────────────

def send_otp(data: dict):
    email = (data.get("email") or "").strip().lower()
    purpose = (data.get("purpose") or "").strip()

    if not email or not validate_email(email):
        return error("A valid email address is required.", 400)
    if purpose not in OtpPurpose.ALL:
        return error(
            f"Invalid purpose. Must be one of: {', '.join(OtpPurpose.ALL)}.",
            400,
        )

    user = user_repository.get_by_email(email)
    # Always return the same message to avoid revealing whether the email is registered
    if user:
        otp_service.generate_and_send(email=email, purpose=purpose, user_id=user.id)

    return success(message="If this email is registered, an OTP has been sent.")


# ── Verify OTP ───────────────────────────────────────────────────────────────────

def verify_otp(data: dict):
    email = (data.get("email") or "").strip().lower()
    otp_code = (data.get("otp") or "").strip()
    purpose = (data.get("purpose") or "").strip()

    if not email or not otp_code or not purpose:
        return error("email, otp, and purpose are required.", 400)
    if purpose not in OtpPurpose.ALL:
        return error("Invalid purpose.", 400)

    otp_record = otp_repository.get_latest_valid(email=email, purpose=purpose)
    if not otp_record:
        return error(
            "No valid OTP found. Please request a new one.",
            400,
            error_code="OTP_NOT_FOUND",
        )

    max_attempts = current_app.config.get("OTP_MAX_ATTEMPTS", 5)

    if otp_record.is_exhausted(max_attempts):
        return error(
            "Too many incorrect attempts. Please request a new OTP.",
            400,
            error_code="OTP_EXHAUSTED",
        )

    if otp_record.is_expired:
        return error(
            "OTP has expired. Please request a new one.",
            400,
            error_code="OTP_EXPIRED",
        )

    if not bcrypt.check_password_hash(otp_record.otp_hash, otp_code):
        otp_repository.increment_attempts(otp_record)
        remaining = max_attempts - (otp_record.attempts)
        return error(
            f"Invalid OTP. {remaining} attempt(s) remaining.",
            400,
            error_code="OTP_INVALID",
        )

    # ── Handle by purpose ────────────────────────────────────────────────────────

    if purpose == OtpPurpose.SIGNUP:
        return _complete_signup_verification(otp_record, email)

    if purpose == OtpPurpose.FORGOT_PASSWORD:
        return _complete_forgot_password_verification(otp_record, email)

    # EMAIL_CHANGE or any future purpose — just mark verified
    otp_repository.mark_verified(otp_record)
    return success(message="OTP verified successfully.")


def _complete_signup_verification(otp_record, email: str):
    """
    Atomically: mark OTP verified + set email_verified + create Free subscription.
    All three changes commit together or all roll back.
    """
    user = user_repository.get_by_email(email)
    if not user:
        return error("User not found.", 404)

    sub_result = subscription_repository.create_free_subscription_no_commit(user.id)
    if sub_result.get("error"):
        return error(sub_result["error"], 500, error_code="SETUP_ERROR")

    try:
        otp_record.verified_at = datetime.now(timezone.utc)
        user.email_verified = True
        user.updated_at = datetime.now(timezone.utc)
        # subscription was already added to session by create_free_subscription_no_commit
        db.session.commit()
    except Exception as exc:
        db.session.rollback()
        current_app.logger.error("Signup verification commit failed: %s", exc)
        return error("Verification failed due to a server error. Please try again.", 500)

    return success(message="Email verified successfully. You can now log in.")


def _complete_forgot_password_verification(otp_record, email: str):
    """
    Mark OTP verified and return a short-lived password-reset JWT.
    The reset token is valid for 15 minutes and carries a custom claim
    so it cannot be used as a regular access token.
    """
    user = user_repository.get_by_email(email)
    if not user:
        return error("User not found.", 404)

    try:
        otp_record.verified_at = datetime.now(timezone.utc)
        db.session.commit()
    except Exception as exc:
        db.session.rollback()
        current_app.logger.error("Forgot-password OTP commit failed: %s", exc)
        return error("Verification failed. Please try again.", 500)

    reset_token = create_access_token(
        identity=str(user.id),
        additional_claims={"token_purpose": "password_reset"},
        expires_delta=timedelta(minutes=15),
    )

    return success(
        data={"reset_token": reset_token},
        message="OTP verified. Use the reset_token to set a new password within 15 minutes.",
    )


# ── Login ────────────────────────────────────────────────────────────────────────

def login_user(data: dict):
    email = (data.get("email") or "").strip().lower()
    password = data.get("password") or ""

    if not email or not password:
        logger.warning("[LOGIN] Rejected: missing email or password field")
        return error("Email and password are required.", 400)

    logger.info("[LOGIN] Attempt: email=%s", email)

    user = user_repository.get_by_email(email)

    # Always run bcrypt even when user is not found to prevent timing-based
    # user enumeration attacks. _TIMING_DUMMY_HASH is pre-computed at module load.
    if user:
        password_correct = bcrypt.check_password_hash(user.password_hash, password)
        logger.debug(
            "[LOGIN] User found: id=%s email=%s is_active=%s email_verified=%s password_correct=%s",
            user.id, email, user.is_active, user.email_verified, password_correct,
        )
    else:
        _bcrypt_lib.checkpw(b"dummy", _TIMING_DUMMY_HASH)
        password_correct = False
        logger.warning("[LOGIN] Failed: no user found for email=%s", email)

    if not user or not password_correct:
        if user and not password_correct:
            logger.warning("[LOGIN] Failed: wrong password for email=%s user_id=%s", email, user.id)
        return error("Invalid email or password.", 401, error_code="INVALID_CREDENTIALS")

    if not user.is_active:
        logger.warning("[LOGIN] Rejected: account inactive user_id=%s email=%s", user.id, email)
        return error("Your account has been deactivated. Contact support.", 403, error_code="ACCOUNT_INACTIVE")

    if not user.email_verified:
        logger.warning("[LOGIN] Rejected: email not verified user_id=%s email=%s", user.id, email)
        return error(
            "Please verify your email before logging in.",
            403,
            error_code="EMAIL_NOT_VERIFIED",
        )

    logger.info("[LOGIN] Success: issuing tokens for user_id=%s email=%s", user.id, email)
    return _issue_tokens(user)


# ── Refresh token ────────────────────────────────────────────────────────────────

def refresh_access_token(data: dict):
    raw_token = (data.get("refresh_token") or "").strip()
    if not raw_token:
        logger.warning("[REFRESH] Rejected: no refresh_token in request body")
        return error("refresh_token is required.", 400)

    token_hash = hash_token(raw_token)
    stored = refresh_token_repository.get_by_hash(token_hash)

    if not stored:
        logger.warning("[REFRESH] Failed: token hash not found in DB")
        return error(
            "Invalid or expired refresh token. Please log in again.",
            401,
            error_code="REFRESH_TOKEN_INVALID",
        )

    if not stored.is_valid:
        logger.warning(
            "[REFRESH] Failed: token invalid (revoked=%s, expired=%s) user_id=%s",
            stored.revoked,
            stored.expires_at,
            stored.user_id,
        )
        return error(
            "Invalid or expired refresh token. Please log in again.",
            401,
            error_code="REFRESH_TOKEN_INVALID",
        )

    logger.info("[REFRESH] Rotating token for user_id=%s", stored.user_id)

    # Revoke old token before issuing new one (single-use rotation)
    refresh_token_repository.revoke(stored)

    user = user_repository.get_by_id(str(stored.user_id))
    if not user or not user.is_active:
        logger.warning("[REFRESH] Rejected: user inactive or not found user_id=%s", stored.user_id)
        return error("Account is inactive.", 403, error_code="ACCOUNT_INACTIVE")

    return _issue_tokens(user)


# ── Logout ───────────────────────────────────────────────────────────────────────

def logout_user(data: dict):
    raw_token = (data.get("refresh_token") or "").strip()

    if raw_token:
        token_hash = hash_token(raw_token)
        stored = refresh_token_repository.get_by_hash(token_hash)
        # Only revoke if the token belongs to the authenticated user
        if stored and str(stored.user_id) == str(g.current_user.id):
            refresh_token_repository.revoke(stored)

    return success(message="Logged out successfully.")


# ── Current user ─────────────────────────────────────────────────────────────────

def get_current_user():
    return success(data=g.current_user.to_dict())


# ── Forgot password ──────────────────────────────────────────────────────────────

def forgot_password(data: dict):
    email = (data.get("email") or "").strip().lower()

    if not email or not validate_email(email):
        return error("A valid email address is required.", 400)

    user = user_repository.get_by_email(email)

    # Send OTP only if user exists and is active.
    # Always return the same message — never reveal whether the email is registered.
    if user and user.is_active:
        otp_service.generate_and_send(
            email=email,
            purpose=OtpPurpose.FORGOT_PASSWORD,
            user_id=user.id,
        )

    return success(
        message="If this email is registered, a password reset OTP has been sent."
    )


# ── Reset password ───────────────────────────────────────────────────────────────

def reset_password(data: dict):
    reset_token = (data.get("reset_token") or "").strip()
    new_password = data.get("new_password") or ""

    if not reset_token or not new_password:
        return error("reset_token and new_password are required.", 400)

    pw_errors = validate_password(new_password)
    if pw_errors:
        return error(
            "Password does not meet requirements.",
            400,
            errors=[{"field": "new_password", "message": m} for m in pw_errors],
        )

    # Decode and validate the reset JWT
    try:
        decoded = decode_token(reset_token)
    except Exception:
        return error(
            "Invalid or expired reset token. Please request a new OTP.",
            400,
            error_code="RESET_TOKEN_INVALID",
        )

    if decoded.get("token_purpose") != "password_reset":
        return error(
            "This token cannot be used to reset a password.",
            400,
            error_code="RESET_TOKEN_INVALID",
        )

    user_id = decoded.get("sub")
    user = user_repository.get_by_id(user_id)
    if not user:
        return error("User not found.", 404)

    new_hash = bcrypt.generate_password_hash(new_password).decode("utf-8")

    try:
        user.password_hash = new_hash
        user.updated_at = datetime.now(timezone.utc)
        db.session.commit()
    except Exception as exc:
        db.session.rollback()
        current_app.logger.error("reset_password commit failed: %s", exc)
        return error("Password reset failed. Please try again.", 500)

    # Revoke all refresh tokens — force re-login on all devices after password change
    try:
        refresh_token_repository.revoke_all_for_user(user.id)
    except Exception as exc:
        current_app.logger.warning("Token revocation after password reset failed: %s", exc)

    return success(message="Password reset successfully. Please log in with your new password.")


# ── Internal helpers ─────────────────────────────────────────────────────────────

def _issue_tokens(user):
    """
    Create a JWT access token + a secure random refresh token.
    Persist only the SHA-256 hash of the refresh token — never the raw value.
    Return both to the caller.
    """
    role_name = user.role.name if user.role else RoleName.USER
    logger.debug("[TOKEN] Creating access token: user_id=%s role=%s", user.id, role_name)

    access_token = create_access_token(
        identity=str(user.id),
        additional_claims={"role": role_name},
    )

    raw_refresh = generate_secure_token()
    token_hash = hash_token(raw_refresh)

    refresh_ttl: timedelta = current_app.config["JWT_REFRESH_TOKEN_EXPIRES"]
    expires_at = datetime.now(timezone.utc) + refresh_ttl

    refresh_token_repository.create(
        user_id=user.id,
        token_hash=token_hash,
        expires_at=expires_at,
    )

    logger.info(
        "[TOKEN] Issued tokens: user_id=%s access_ttl=%s refresh_expires=%s",
        user.id,
        current_app.config["JWT_ACCESS_TOKEN_EXPIRES"],
        expires_at.isoformat(),
    )

    return success(
        data={
            "access_token": access_token,
            "refresh_token": raw_refresh,
            "token_type": "Bearer",
            "user": user.to_dict(),
        },
        message="Authentication successful.",
    )
