"""
Max Pain Celery Tasks
=====================
Beat schedule: every 5 minutes during NSE market hours.

Market hours guard: 09:15–15:30 IST = 03:45–10:00 UTC (Mon–Fri).
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Optional

from celery import shared_task
from flask import current_app

from app.services.max_pain_scanner_service import DEFAULT_FO_UNIVERSE
from app.services.max_pain_snapshot_service import (
    capture_symbols,
    capture_symbol,
    cleanup_old_snapshots,
)

logger = logging.getLogger(__name__)

# NSE 09:15–15:30 IST = 03:45–10:00 UTC
_OPEN_UTC  = (3, 45)
_CLOSE_UTC = (10, 0)


def _is_market_open() -> bool:
    """Return True only during NSE trading hours Mon–Fri."""
    now = datetime.now(timezone.utc)
    if now.weekday() >= 5:                          # Sat=5, Sun=6
        return False
    open_m  = _OPEN_UTC[0]  * 60 + _OPEN_UTC[1]
    close_m = _CLOSE_UTC[0] * 60 + _CLOSE_UTC[1]
    current = now.hour * 60 + now.minute
    return open_m <= current < close_m


# ---------------------------------------------------------------------------
# Scheduled bulk capture — runs every 5 minutes
# ---------------------------------------------------------------------------

@shared_task(
    name="app.tasks.max_pain_tasks.capture_max_pain_snapshot",
    bind=True, max_retries=2, default_retry_delay=60,
)
def capture_max_pain_snapshot(
    self,
    symbols: Optional[list] = None,
    expiry: Optional[str]   = None,
    force: bool             = False,
):
    """
    Capture max pain snapshots for the F&O universe.

    Args:
        symbols: Override default universe (default: all DEFAULT_FO_UNIVERSE).
        expiry:  Pin to a specific expiry (default: nearest per symbol).
        force:   Set True to bypass market-hours guard (for backfill / testing).
    """
    if not force and not _is_market_open():
        logger.info("Max pain snapshot skipped — outside market hours")
        return {"skipped": True, "reason": "outside_market_hours"}

    target = symbols or DEFAULT_FO_UNIVERSE
    logger.info("Max pain snapshot starting: %d symbols", len(target))

    try:
        result = capture_symbols(target, expiry=expiry)
        logger.info(
            "Max pain snapshot done: saved=%d errors=%d",
            result["saved"], len(result["errors"]),
        )
        return result
    except Exception as exc:
        logger.error("Snapshot task failed: %s", exc, exc_info=True)
        raise self.retry(exc=exc)


# ---------------------------------------------------------------------------
# On-demand single symbol — triggered by user viewing the drawer
# ---------------------------------------------------------------------------

@shared_task(
    name="app.tasks.max_pain_tasks.capture_single_symbol",
    bind=True, max_retries=3, default_retry_delay=20,
)
def capture_single_symbol_task(
    self,
    symbol: str,
    expiry: Optional[str] = None,
):
    """Immediate on-demand snapshot for one symbol."""
    try:
        snap = capture_symbol(symbol, expiry=expiry)
        return {
            "symbol":     snap.symbol,
            "expiry":     snap.expiry,
            "max_pain":   snap.max_pain,
            "captured_at": snap.captured_at.isoformat(),
        }
    except Exception as exc:
        logger.error("Single symbol capture failed for %s: %s", symbol, exc)
        raise self.retry(exc=exc)


# ---------------------------------------------------------------------------
# Retention cleanup — run daily (configure separately in CELERYBEAT_SCHEDULE)
# ---------------------------------------------------------------------------

@shared_task(
    name="app.tasks.max_pain_tasks.cleanup_snapshots",
    bind=False,
)
def cleanup_snapshots_task():
    """
    Delete snapshots older than MAX_PAIN_RETENTION_DAYS (default 90).
    Schedule in CELERYBEAT_SCHEDULE as a daily cron.
    """
    retention = current_app.config.get("MAX_PAIN_RETENTION_DAYS", 90)
    deleted   = cleanup_old_snapshots(retention)
    logger.info("Snapshot retention cleanup: %d rows deleted (retention=%dd)", deleted, retention)
    return {"deleted": deleted, "retention_days": retention}
