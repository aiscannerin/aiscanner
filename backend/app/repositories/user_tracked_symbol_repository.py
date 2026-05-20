from app.extensions import db
from app.models.user_tracked_symbol import UserTrackedSymbol


def get_all_for_user(user_id) -> list[UserTrackedSymbol]:
    """Return all active tracked symbols for a user, newest first."""
    return db.session.execute(
        db.select(UserTrackedSymbol)
        .where(UserTrackedSymbol.user_id == user_id)
        .where(UserTrackedSymbol.is_active == True)   # noqa: E712
        .order_by(UserTrackedSymbol.created_at.desc())
    ).scalars().all()


def get_by_id(tracked_id) -> UserTrackedSymbol | None:
    return db.session.get(UserTrackedSymbol, tracked_id)


def find_active(user_id, symbol: str, scanner_name: str, htf: str, ltf: str | None) -> UserTrackedSymbol | None:
    """Return an existing active entry matching the unique combo, or None."""
    q = (
        db.select(UserTrackedSymbol)
        .where(UserTrackedSymbol.user_id      == user_id)
        .where(UserTrackedSymbol.symbol       == symbol.upper())
        .where(UserTrackedSymbol.scanner_name == scanner_name)
        .where(UserTrackedSymbol.htf          == htf)
        .where(UserTrackedSymbol.is_active    == True)   # noqa: E712
    )
    if ltf:
        q = q.where(UserTrackedSymbol.ltf == ltf)
    else:
        q = q.where(UserTrackedSymbol.ltf == None)   # noqa: E711
    return db.session.execute(q).scalar_one_or_none()


def create(user_id, symbol: str, scanner_name: str, htf: str,
           ltf: str | None = None, note: str | None = None) -> UserTrackedSymbol:
    entry = UserTrackedSymbol(
        user_id      = user_id,
        symbol       = symbol.upper(),
        scanner_name = scanner_name,
        htf          = htf,
        ltf          = ltf or None,
        note         = note,
        is_active    = True,
    )
    db.session.add(entry)
    db.session.commit()
    return entry


def delete(entry: UserTrackedSymbol) -> None:
    db.session.delete(entry)
    db.session.commit()


def update_note(entry: UserTrackedSymbol, note: str | None) -> UserTrackedSymbol:
    entry.note = note
    db.session.commit()
    return entry


_ALERT_BOOL_FIELDS = {
    "alert_became_confirmed",
    "alert_improved_level",
    "alert_became_watchlist",
    "alert_degraded",
    "alert_score_crossed_threshold",
}


def update_alert_prefs(entry: UserTrackedSymbol, prefs: dict) -> UserTrackedSymbol:
    """
    Apply alert preference updates from a dict.
    Only recognised boolean keys and score_threshold are applied.
    """
    for key in _ALERT_BOOL_FIELDS:
        if key in prefs:
            val = prefs[key]
            if isinstance(val, bool):
                setattr(entry, key, val)

    if "score_threshold" in prefs:
        val = prefs["score_threshold"]
        entry.score_threshold = int(val) if val is not None else None

    db.session.commit()
    return entry
