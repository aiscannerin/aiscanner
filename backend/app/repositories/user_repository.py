import uuid
from datetime import datetime, timezone

from app.extensions import db
from app.models.user import User


def get_by_id(user_id: str) -> User | None:
    """Look up a user by UUID primary key. Accepts string or UUID object."""
    try:
        uid = uuid.UUID(str(user_id))
    except (ValueError, AttributeError):
        return None
    return db.session.get(User, uid)


def get_by_email(email: str) -> User | None:
    return db.session.execute(
        db.select(User).where(User.email == email.strip().lower())
    ).scalar_one_or_none()


def get_by_username(username: str) -> User | None:
    return db.session.execute(
        db.select(User).where(User.username == username.strip().lower())
    ).scalar_one_or_none()


def create(data: dict) -> User:
    user = User(**data)
    db.session.add(user)
    db.session.commit()
    db.session.refresh(user)
    return user


def update(user: User, data: dict) -> User:
    for key, value in data.items():
        setattr(user, key, value)
    user.updated_at = datetime.now(timezone.utc)
    db.session.commit()
    return user
