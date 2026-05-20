import hashlib
import hmac
import secrets
import string


def hash_token(raw_token: str) -> str:
    """
    SHA-256 hash a raw token string for safe DB storage.
    Used for refresh tokens — only the hash is persisted.
    """
    return hashlib.sha256(raw_token.encode("utf-8")).hexdigest()


def generate_secure_token(nbytes: int = 32) -> str:
    """
    Generate a cryptographically secure URL-safe random token.
    Used for refresh tokens.
    """
    return secrets.token_urlsafe(nbytes)


def generate_otp(length: int = 6) -> str:
    """
    Generate a numeric OTP of given length.
    Uses secrets module for cryptographic randomness.
    """
    digits = string.digits
    return "".join(secrets.choice(digits) for _ in range(length))


def verify_razorpay_webhook_signature(payload_body: bytes, signature: str, secret: str) -> bool:
    """
    Verify Razorpay webhook HMAC-SHA256 signature.

    Razorpay signs the raw request body with the webhook secret.
    payload_body must be the raw bytes from request.get_data().
    """
    expected = hmac.new(
        key=secret.encode("utf-8"),
        msg=payload_body,
        digestmod=hashlib.sha256,
    ).hexdigest()
    return hmac.compare_digest(expected, signature)


def verify_razorpay_payment_signature(
    order_id: str, payment_id: str, signature: str, secret: str
) -> bool:
    """
    Verify Razorpay frontend payment signature.

    Razorpay signs: razorpay_order_id + "|" + razorpay_payment_id
    """
    message = f"{order_id}|{payment_id}"
    expected = hmac.new(
        key=secret.encode("utf-8"),
        msg=message.encode("utf-8"),
        digestmod=hashlib.sha256,
    ).hexdigest()
    return hmac.compare_digest(expected, signature)


def safe_str_compare(a: str, b: str) -> bool:
    """Constant-time string comparison to prevent timing attacks."""
    return hmac.compare_digest(a.encode("utf-8"), b.encode("utf-8"))
