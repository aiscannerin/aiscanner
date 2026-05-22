"""
Broker Credential Service
========================
Save / retrieve / validate per-user broker (Dhan) API credentials.
Access tokens are encrypted at rest via app.utils.crypto.
"""

from __future__ import annotations

import logging

from app.repositories import user_broker_credential_repository as repo
from app.utils.crypto import encrypt, decrypt
from app.services import dhan_option_chain_service as dhan

logger = logging.getLogger(__name__)


def get_status(user_id, broker: str = "dhan") -> dict:
    """Public status (never includes the token). Returns connected=False if none."""
    row = repo.get(user_id, broker)
    if row is None:
        return {"broker": broker, "connected": False, "is_valid": False}
    return row.to_dict()


def get_decrypted(user_id, broker: str = "dhan") -> tuple[str, str] | None:
    """
    Return (client_id, access_token) for the user, or None if not connected.
    Raises ValueError if the stored token cannot be decrypted.
    """
    row = repo.get(user_id, broker)
    if row is None:
        return None
    return row.client_id, decrypt(row.access_token_encrypted)


def save(user_id, client_id: str, access_token: str, broker: str = "dhan") -> dict:
    """
    Validate the credentials against Dhan, then store them (token encrypted).
    Returns the public status dict including validity + any error.
    """
    client_id = (client_id or "").strip()
    access_token = (access_token or "").strip()
    if not client_id or not access_token:
        raise ValueError("Both Client ID and Access Token are required.")

    is_valid, err = dhan.validate_credentials(client_id, access_token)

    row = repo.upsert(
        user_id,
        broker=broker,
        client_id=client_id,
        access_token_encrypted=encrypt(access_token),
        is_valid=is_valid,
        last_error=err,
    )
    logger.info(
        "[BROKER] Saved %s credentials for user=%s valid=%s",
        broker, str(user_id)[:8], is_valid,
    )
    return row.to_dict()


def test(user_id, broker: str = "dhan") -> dict:
    """Re-validate stored credentials. Returns {valid, error}."""
    creds = get_decrypted(user_id, broker)
    if creds is None:
        return {"valid": False, "error": "No credentials saved."}
    client_id, access_token = creds
    is_valid, err = dhan.validate_credentials(client_id, access_token)
    repo.mark_validation(user_id, broker, is_valid, err)
    return {"valid": is_valid, "error": err}


def remove(user_id, broker: str = "dhan") -> bool:
    return repo.delete(user_id, broker)
