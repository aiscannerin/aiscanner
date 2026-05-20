from datetime import datetime

from sqlalchemy import update

from app.extensions import db
from app.models.refresh_token import RefreshToken


def create(user_id, token_hash: str, expires_at: datetime) -> RefreshToken:
    token = RefreshToken(
        user_id=user_id,
        token_hash=token_hash,
        expires_at=expires_at,
        revoked=False,
    )
    db.session.add(token)
    db.session.commit()
    return token


def get_by_hash(token_hash: str) -> RefreshToken | None:
    return db.session.execute(
        db.select(RefreshToken).where(RefreshToken.token_hash == token_hash)
    ).scalar_one_or_none()


def revoke(token: RefreshToken) -> None:
    token.revoked = True
    db.session.commit()


def revoke_all_for_user(user_id) -> None:
    """Revoke every active refresh token for a user. Called on password reset."""
    db.session.execute(
        update(RefreshToken)
        .where(
            RefreshToken.user_id == user_id,
            RefreshToken.revoked == False,  # noqa: E712
        )
        .values(revoked=True)
    )
    db.session.commit()
