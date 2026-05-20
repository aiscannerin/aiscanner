from app.extensions import db
from app.models.user_alert_settings import UserAlertSettings


def get_for_user(user_id) -> UserAlertSettings | None:
    return db.session.execute(
        db.select(UserAlertSettings)
        .where(UserAlertSettings.user_id == user_id)
    ).scalar_one_or_none()


def get_or_create(user_id) -> UserAlertSettings:
    """Return existing settings row or create a default one (no commit)."""
    row = get_for_user(user_id)
    if row is None:
        row = UserAlertSettings(user_id=user_id)
        db.session.add(row)
        db.session.flush()   # assign id without full commit
    return row


def upsert(user_id, email_alerts_enabled: bool | None = None,
           email_address: str | None = ...) -> UserAlertSettings:
    """
    Update alert settings for a user.  Only supplied fields are changed.
    Uses sentinel default (...) so callers can explicitly pass None to clear.
    Commits the session.
    """
    row = get_or_create(user_id)

    if email_alerts_enabled is not None:
        row.email_alerts_enabled = bool(email_alerts_enabled)

    # email_address sentinel: ... means "not provided"
    if email_address is not ...:
        row.email_address = (email_address.strip() or None) if email_address else None

    db.session.commit()
    return row
