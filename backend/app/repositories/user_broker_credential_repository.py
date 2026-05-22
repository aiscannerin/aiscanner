import uuid
from datetime import datetime, timezone

from app.extensions import db
from app.models.user_broker_credential import UserBrokerCredential


def _as_uuid(user_id):
    return uuid.UUID(str(user_id))


def get(user_id, broker: str = "dhan") -> UserBrokerCredential | None:
    return db.session.execute(
        db.select(UserBrokerCredential).where(
            UserBrokerCredential.user_id == _as_uuid(user_id),
            UserBrokerCredential.broker == broker,
        )
    ).scalar_one_or_none()


def upsert(
    user_id,
    *,
    broker: str = "dhan",
    client_id: str,
    access_token_encrypted: str,
    is_valid: bool = False,
    last_error: str | None = None,
) -> UserBrokerCredential:
    row = get(user_id, broker)
    now = datetime.now(timezone.utc)
    if row is None:
        row = UserBrokerCredential(
            user_id=_as_uuid(user_id),
            broker=broker,
        )
        db.session.add(row)

    row.client_id = client_id
    row.access_token_encrypted = access_token_encrypted
    row.is_valid = is_valid
    row.last_error = last_error
    if is_valid:
        row.last_validated_at = now
    row.updated_at = now

    db.session.commit()
    db.session.refresh(row)
    return row


def mark_validation(user_id, broker: str, is_valid: bool, error: str | None) -> None:
    row = get(user_id, broker)
    if row is None:
        return
    row.is_valid = is_valid
    row.last_error = error
    if is_valid:
        row.last_validated_at = datetime.now(timezone.utc)
    db.session.commit()


def delete(user_id, broker: str = "dhan") -> bool:
    row = get(user_id, broker)
    if row is None:
        return False
    db.session.delete(row)
    db.session.commit()
    return True
