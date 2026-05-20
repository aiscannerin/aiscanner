"""
scan_snapshot_service.py
========================
Persistence layer for full-universe scanner snapshots.

Public API
----------
  save_scan_snapshot(scan_response, threshold)
  get_latest_snapshot(threshold=None)
  get_snapshot_history(limit=20)
  load_snapshot_payload(snapshot)
  count_snapshots()

Design notes
------------
• All DB access uses db.session.execute(db.select(...)) — the Flask-SQLAlchemy
  3.x preferred form.  Model.query is deprecated and behaves differently under
  some session configurations.
• Threshold matching uses approximate equality (|a-b| < 0.01) instead of exact
  float ==, avoiding IEEE-754 edge cases.
• All functions log every decision branch so failures are immediately visible
  in the Flask dev-server output.
• Every function is wrapped in try/except so a DB hiccup never crashes the
  scan endpoint — snapshots are best-effort.
"""

from __future__ import annotations

import json
import logging
import os
from typing import Optional

from sqlalchemy import func, text

logger = logging.getLogger(__name__)

# How close two threshold floats must be to be considered the same threshold.
_THRESHOLD_EPSILON = 0.01


# ---------------------------------------------------------------------------
# Lazy accessors — avoids circular imports before Flask app context exists.
# ---------------------------------------------------------------------------

def _model():
    from app.models.scan_snapshot import ScanSnapshot
    return ScanSnapshot


def _db():
    from app.extensions import db
    return db


def _db_uri_masked() -> str:
    """Return the DATABASE_URL with password redacted (safe to log)."""
    try:
        import re
        uri = os.getenv("DATABASE_URL", "unknown")
        return re.sub(r"://([^:]+):([^@]+)@", r"://\1:***@", uri)
    except Exception:
        return "<could not read DATABASE_URL>"


# ---------------------------------------------------------------------------
# save_scan_snapshot
# ---------------------------------------------------------------------------

def save_scan_snapshot(
    scan_response: dict,
    threshold: float = 2.0,
) -> Optional[object]:
    """
    Persist the full run_scanner() response dict as a ScanSnapshot row.

    Skips silently when results list is empty (market-closed-only runs).
    Returns the saved ORM row on success, None on skip or error.
    """
    ScanSnapshot = _model()
    db           = _db()

    results            = scan_response.get("results", [])
    metrics            = scan_response.get("metrics", {})
    market_closed_list = scan_response.get("market_closed", [])

    logger.info(
        "[snapshot.save] called — results=%d market_closed=%d threshold=%.2f db=%s",
        len(results), len(market_closed_list), threshold, _db_uri_masked(),
    )

    if not results:
        logger.info(
            "[snapshot.save] SKIP — no live results to persist "
            "(market_closed=%d, errors=%d)",
            len(market_closed_list),
            len(scan_response.get("errors", [])),
        )
        return None

    market_status = "open" if results else ("closed" if market_closed_list else "unknown")

    try:
        snapshot = ScanSnapshot(
            threshold       = threshold,
            symbol_count    = len(results),
            avg_fetch_ms    = metrics.get("avg_fetch_ms"),
            scan_elapsed_ms = metrics.get("scan_elapsed_ms"),
            market_status   = market_status,
            payload_json    = json.dumps(scan_response, default=str),
        )
        db.session.add(snapshot)
        db.session.flush()   # assign id before commit so we can log it
        snap_id = str(snapshot.id)[:8]
        db.session.commit()
        logger.info(
            "[snapshot.save] COMMITTED id=%s threshold=%.2f%% symbols=%d "
            "market_status=%s",
            snap_id, threshold, len(results), market_status,
        )
        return snapshot

    except Exception as exc:
        logger.error(
            "[snapshot.save] FAILED to commit snapshot: %s", exc, exc_info=True
        )
        try:
            db.session.rollback()
        except Exception:
            pass
        return None


# ---------------------------------------------------------------------------
# get_latest_snapshot
# ---------------------------------------------------------------------------

def get_latest_snapshot(threshold: Optional[float] = None) -> Optional[object]:
    """
    Fetch the most recent ScanSnapshot.

    Lookup strategy (in order):
      1. If threshold given → approximate match (|stored - threshold| < 0.01)
      2. If nothing found  → return newest row regardless of threshold
      (Caller can pass threshold=None to skip to step 2 directly.)

    All lookup steps are logged so failures are visible immediately.
    """
    ScanSnapshot = _model()
    db           = _db()

    logger.info(
        "[snapshot.get] called — threshold=%s db=%s",
        f"{threshold:.2f}" if threshold is not None else "any",
        _db_uri_masked(),
    )

    try:
        # ── Step 0: total row count (sanity check) ────────────────────────
        total = db.session.execute(
            db.select(func.count()).select_from(ScanSnapshot)
        ).scalar_one()
        logger.info("[snapshot.get] total rows in scan_snapshots: %d", total)

        if total == 0:
            logger.info("[snapshot.get] table is empty — returning None")
            return None

        # ── Step 1: approximate threshold match ───────────────────────────
        if threshold is not None:
            stmt = (
                db.select(ScanSnapshot)
                .where(func.abs(ScanSnapshot.threshold - threshold) < _THRESHOLD_EPSILON)
                .order_by(ScanSnapshot.created_at.desc())
                .limit(1)
            )
            row = db.session.execute(stmt).scalar_one_or_none()
            if row is not None:
                logger.info(
                    "[snapshot.get] FOUND (approx threshold match) "
                    "id=%s threshold=%.2f created_at=%s age_min=%.1f",
                    str(row.id)[:8], row.threshold,
                    row.created_at.isoformat(), row.age_minutes(),
                )
                return row
            logger.info(
                "[snapshot.get] no approx-threshold match for %.2f "
                "— falling back to newest row",
                threshold,
            )

        # ── Step 2: newest row regardless of threshold ────────────────────
        stmt_any = (
            db.select(ScanSnapshot)
            .order_by(ScanSnapshot.created_at.desc())
            .limit(1)
        )
        row_any = db.session.execute(stmt_any).scalar_one_or_none()
        if row_any is not None:
            logger.info(
                "[snapshot.get] FOUND (any-threshold fallback) "
                "id=%s threshold=%.2f created_at=%s age_min=%.1f",
                str(row_any.id)[:8], row_any.threshold,
                row_any.created_at.isoformat(), row_any.age_minutes(),
            )
            return row_any

        logger.info("[snapshot.get] no rows found — returning None")
        return None

    except Exception as exc:
        logger.error(
            "[snapshot.get] EXCEPTION during lookup: %s", exc, exc_info=True
        )
        return None


# ---------------------------------------------------------------------------
# get_snapshot_history
# ---------------------------------------------------------------------------

def get_snapshot_history(limit: int = 20) -> list[dict]:
    """Return the N most recent snapshots as metadata dicts (no payload)."""
    ScanSnapshot = _model()
    db           = _db()

    try:
        stmt = (
            db.select(ScanSnapshot)
            .order_by(ScanSnapshot.created_at.desc())
            .limit(limit)
        )
        rows = db.session.execute(stmt).scalars().all()
        logger.debug("[snapshot.history] returning %d rows (limit=%d)", len(rows), limit)
        return [r.to_meta() for r in rows]

    except Exception as exc:
        logger.error("[snapshot.history] FAILED: %s", exc, exc_info=True)
        return []


# ---------------------------------------------------------------------------
# count_snapshots
# ---------------------------------------------------------------------------

def count_snapshots() -> int:
    """Return total number of ScanSnapshot rows (0 on error)."""
    ScanSnapshot = _model()
    db           = _db()

    try:
        return db.session.execute(
            db.select(func.count()).select_from(ScanSnapshot)
        ).scalar_one()
    except Exception as exc:
        logger.error("[snapshot.count] FAILED: %s", exc, exc_info=True)
        return 0


# ---------------------------------------------------------------------------
# load_snapshot_payload
# ---------------------------------------------------------------------------

def load_snapshot_payload(snapshot) -> Optional[dict]:
    """
    Deserialise payload_json.  Returns None on error (logs the failure).
    """
    if snapshot is None:
        logger.debug("[snapshot.load] called with None — returning None")
        return None
    try:
        payload = json.loads(snapshot.payload_json)
        results = payload.get("results", [])
        logger.info(
            "[snapshot.load] decoded payload for id=%s — results=%d",
            str(getattr(snapshot, "id", "?"))[:8], len(results),
        )
        return payload
    except (json.JSONDecodeError, TypeError) as exc:
        logger.error(
            "[snapshot.load] JSON decode error for id=%s: %s",
            str(getattr(snapshot, "id", "?"))[:8], exc,
        )
        return None
