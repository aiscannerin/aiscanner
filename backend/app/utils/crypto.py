"""
Symmetric encryption helpers for sensitive at-rest secrets (e.g. broker
access tokens that can place trades on a user's account).

Uses Fernet (AES-128-CBC + HMAC) from the `cryptography` package.

Key resolution order:
  1. BROKER_TOKEN_KEY env var (a urlsafe-base64 32-byte Fernet key).
     This MUST be identical on every machine that shares the same database,
     otherwise tokens written by one machine cannot be decrypted by another.
  2. Fallback: derive a deterministic key from SECRET_KEY via SHA-256.
     Only used if BROKER_TOKEN_KEY is unset — NOT recommended for production
     because SECRET_KEY differs between dev and server.

Generate a key once with:
    python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
"""

from __future__ import annotations

import base64
import hashlib
import logging
import os

from cryptography.fernet import Fernet, InvalidToken

logger = logging.getLogger(__name__)

_fernet: Fernet | None = None


def _resolve_key() -> bytes:
    explicit = os.getenv("BROKER_TOKEN_KEY", "").strip()
    if explicit:
        return explicit.encode()

    secret = os.getenv("SECRET_KEY", "").strip()
    if not secret:
        raise RuntimeError(
            "Cannot initialise encryption: set BROKER_TOKEN_KEY (preferred) "
            "or SECRET_KEY in the environment."
        )
    logger.warning(
        "BROKER_TOKEN_KEY not set — deriving encryption key from SECRET_KEY. "
        "This breaks if SECRET_KEY differs across machines sharing one DB. "
        "Set BROKER_TOKEN_KEY to the same value everywhere."
    )
    digest = hashlib.sha256(secret.encode()).digest()      # 32 bytes
    return base64.urlsafe_b64encode(digest)


def _get_fernet() -> Fernet:
    global _fernet
    if _fernet is None:
        _fernet = Fernet(_resolve_key())
    return _fernet


def encrypt(plaintext: str) -> str:
    """Encrypt a string, returning a urlsafe token string."""
    if plaintext is None:
        raise ValueError("Cannot encrypt None")
    return _get_fernet().encrypt(plaintext.encode()).decode()


def decrypt(token: str) -> str:
    """
    Decrypt a token produced by encrypt(). Raises ValueError if the token
    is invalid or was encrypted with a different key.
    """
    try:
        return _get_fernet().decrypt(token.encode()).decode()
    except (InvalidToken, ValueError) as exc:
        raise ValueError(
            "Could not decrypt secret — wrong key or corrupted value. "
            "If you changed BROKER_TOKEN_KEY, users must re-enter credentials."
        ) from exc
