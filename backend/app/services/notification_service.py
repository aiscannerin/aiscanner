"""
Internal scanner notification service.

Creates in-app notifications for setup progressions and, when configured,
sends email alerts for tracked-symbol notifications.

Two-tier notification decision:

  TRACKED symbol  → per-symbol alert preferences gate whether a notification is
                    created.  scope = "tracked".

  UNTRACKED symbol → global rule: progression_priority >= _GLOBAL_MIN_PRIORITY (70).
                    scope = "global".

Email alerts (tracked only):
  - user_alert_settings.email_alerts_enabled = true
  - email_address is set
  - notification_scope = "tracked"
  - email_sent = false  (duplicate protection)

Duplicate protection:
  • unique constraint on scan_result_id  (one notification per result row)
  • unique constraint on (symbol, notification_type, scan_run_id)
  • email_sent flag (never send email twice for same notification)
"""

import logging
from datetime import datetime, timezone

from app.extensions import db
from app.models.scanner_notification import ScannerNotification

logger = logging.getLogger(__name__)

_GLOBAL_MIN_PRIORITY = 70

_NOTIFIABLE_TYPES = frozenset({
    "became_confirmed",
    "improved_level",
    "became_watchlist",
    "degraded_level",
    "became_near_miss",
})


# ── Public entry point ─────────────────────────────────────────────────────────

def create_from_results(job, saved_results: list) -> int:
    """
    Inspect saved ScanResult ORM objects, create ScannerNotification rows, and
    attempt email delivery for tracked-scope notifications.

    Returns: count of notifications actually created.
    """
    if not saved_results or job.user_id is None:
        return 0

    # Batch-load tracked symbols for this user (active only)
    from app.repositories.user_tracked_symbol_repository import get_all_for_user
    tracked_map: dict = {e.symbol: e for e in get_all_for_user(job.user_id)}

    # Determine eligible candidates with scope
    candidates: list[tuple] = []
    for r in saved_results:
        ptype = r.progression_type
        if ptype not in _NOTIFIABLE_TYPES:
            continue

        tracked = tracked_map.get(r.symbol)
        if tracked and tracked.is_active:
            if not tracked.alert_allowed(ptype):
                logger.debug("notif skip (pref off): %s  type=%s", r.symbol, ptype)
                continue
            scope = "tracked"
        else:
            if (r.progression_priority or 0) < _GLOBAL_MIN_PRIORITY:
                continue
            scope = "global"

        candidates.append((r, scope))

    if not candidates:
        return 0

    # Pre-fetch existing notifications to avoid duplicate inserts
    cand_result_ids = [r.id for r, _ in candidates]
    existing_result_ids = set(
        row[0] for row in db.session.execute(
            db.select(ScannerNotification.scan_result_id)
            .where(ScannerNotification.scan_result_id.in_(cand_result_ids))
        ).fetchall()
    )

    # Build and insert
    created_notifs: list[ScannerNotification] = []
    for r, scope in candidates:
        if r.id in existing_result_ids:
            logger.debug("notif skip dup: result_id=%s", r.id)
            continue

        notif = _build(job, r, scope)
        if notif is None:
            continue

        db.session.add(notif)
        created_notifs.append(notif)
        logger.info(
            "notif created: %s  type=%s  prio=%d  scope=%s",
            r.symbol, r.progression_type, r.progression_priority, scope,
        )

    if not created_notifs:
        return 0

    try:
        db.session.commit()
    except Exception as exc:
        db.session.rollback()
        logger.warning("notif commit skipped (likely dup): %s", exc)
        return 0

    # Send email alerts for tracked-scope notifications
    _send_emails_for_tracked(job.user_id, created_notifs)

    return len(created_notifs)


# ── Email delivery ─────────────────────────────────────────────────────────────

def _send_emails_for_tracked(user_id, notifications: list) -> None:
    """
    For each tracked-scope notification, attempt email delivery if the user has
    email alerts enabled.  Updates email_sent / email_sent_at / email_error on
    each notification and commits once.
    """
    # Only process tracked-scope items
    tracked_notifs = [n for n in notifications if n.notification_scope == "tracked"]
    if not tracked_notifs:
        return

    from app.repositories.user_alert_settings_repository import get_or_create
    from app.services.email_service import send_scanner_alert_email
    from flask import current_app

    try:
        settings = get_or_create(user_id)
        db.session.commit()   # flush the get_or_create if it inserted
    except Exception as exc:
        logger.warning("alert_settings lookup failed: %s", exc)
        db.session.rollback()
        return

    if not settings.email_alerts_enabled or not settings.email_address:
        logger.debug(
            "email skip (disabled or no address): user=%s  enabled=%s  addr=%s",
            user_id, settings.email_alerts_enabled, bool(settings.email_address),
        )
        return

    dashboard_url = current_app.config.get("DASHBOARD_URL", "")
    to_email      = settings.email_address
    to_name       = settings.email_address  # name not stored separately

    any_updated = False
    for notif in tracked_notifs:
        if notif.email_sent:
            logger.debug("email skip (already sent): notif_id=%s", notif.id)
            continue

        sent, err = send_scanner_alert_email(to_email, to_name, notif, dashboard_url)

        notif.email_sent  = sent
        notif.email_error = err
        if sent:
            notif.email_sent_at = datetime.now(timezone.utc)
            logger.info("email sent: %s → %s  notif=%s", notif.symbol, to_email, notif.id)
        else:
            logger.warning("email failed: %s  err=%s  notif=%s", notif.symbol, err, notif.id)

        any_updated = True

    if any_updated:
        try:
            db.session.commit()
        except Exception as exc:
            db.session.rollback()
            logger.warning("email status commit failed: %s", exc)


# ── Private builders ───────────────────────────────────────────────────────────

def _build(job, r, scope: str = "global") -> ScannerNotification | None:
    """Build a ScannerNotification ORM object; returns None if type not supported."""
    ptype   = r.progression_type
    symbol  = r.symbol
    score   = f"{float(r.score):.1f}" if r.score is not None else "—"
    grade   = r.grade or "—"
    curr_wl = r.watchlist_level or ""
    prev_cl = r.previous_status or ""
    prev_wl = r.previous_watchlist_level or ""
    stage   = r.current_stage_label or ""

    if ptype == "became_confirmed":
        if prev_cl == "watchlist" and prev_wl:
            prev_desc = f"Watchlist {prev_wl}"
        elif prev_cl:
            prev_desc = prev_cl.replace("_", " ").title()
        else:
            prev_desc = "prior state"
        title   = f"{symbol} Confirmed"
        message = (
            f"{symbol} improved from {prev_desc} to Confirmed. "
            f"Score {score}, grade {grade}."
        )

    elif ptype == "improved_level":
        from_wl = prev_wl or "L1"
        to_wl   = curr_wl or "L?"
        title   = f"{symbol} improved to {to_wl}"
        message = f"{symbol} moved from {from_wl} to {to_wl}."
        if stage:
            message += f" {stage}."

    elif ptype == "became_watchlist":
        wl_str  = f" {curr_wl}" if curr_wl else ""
        title   = f"{symbol} Watchlist{wl_str}"
        message = f"{symbol} moved from Near Miss to Watchlist{wl_str}."
        if stage:
            message += f" {stage}."

    elif ptype in ("degraded_level", "became_near_miss"):
        action = "degraded" if ptype == "degraded_level" else "became Near Miss"
        title   = f"{symbol} {action.title()}"
        if prev_cl:
            message = f"{symbol} {action} (was {prev_cl.replace('_',' ')} {prev_wl}).".strip()
        else:
            message = f"{symbol} {action}."

    else:
        return None

    return ScannerNotification(
        user_id            = job.user_id,
        scan_run_id        = job.id,
        scan_result_id     = r.id,
        symbol             = symbol,
        notification_type  = ptype,
        title              = title,
        message            = message,
        priority           = r.progression_priority or 0,
        is_read            = False,
        notification_scope = scope,
    )
