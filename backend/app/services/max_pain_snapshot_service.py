"""
Max Pain Snapshot Service
==========================
Persistent storage and retrieval of max pain snapshots.

Public API
----------
    store_snapshot(result, chain, captured_at=None) -> MaxPainSnapshot
    get_latest_snapshot(symbol, expiry=None)        -> Optional[MaxPainSnapshot]
    get_historical_snapshots(symbol, window, expiry, max_points) -> list[dict]
    capture_symbol(symbol, expiry=None)             -> MaxPainSnapshot
    capture_symbols(symbols, expiry=None)           -> dict
    cleanup_old_snapshots(retention_days)           -> int
"""

from __future__ import annotations

import logging
import uuid
from datetime import datetime, timedelta, timezone
from typing import Optional

from app.extensions import db
from app.models.max_pain_snapshot import MaxPainSnapshot, OIWallSnapshot
from app.services.max_pain_engine import MaxPainResult, calculate_max_pain, get_oi_walls
from app.services.nse_option_chain_service import get_option_chain, OptionChainResult

logger = logging.getLogger(__name__)

# Top-N OI walls stored per snapshot tick (CE and PE separately)
_TOP_N_WALLS = 5

# Window string → timedelta mapping (shared with history service)
_WINDOW_MAP = {
    "1h":  timedelta(hours=1),
    "4h":  timedelta(hours=4),
    "1d":  timedelta(days=1),
    "3d":  timedelta(days=3),
    "7d":  timedelta(days=7),
    "30d": timedelta(days=30),
}


def _parse_window(window: str) -> datetime:
    delta = _WINDOW_MAP.get(window, timedelta(days=1))
    return datetime.now(timezone.utc) - delta


def _downsample(rows: list, max_points: int) -> list:
    """Thin a list to at most max_points, preserving first and last."""
    if len(rows) <= max_points:
        return rows
    step = len(rows) / max_points
    indices = {0, len(rows) - 1}
    indices |= {round(i * step) for i in range(1, max_points - 1)}
    return [rows[i] for i in sorted(indices)]


def _top_walls(chain: OptionChainResult, n: int = _TOP_N_WALLS) -> tuple[list, list]:
    """
    Return top-N CE walls (above spot) and top-N PE walls (below spot)
    as plain dicts for JSONB storage.
    """
    spot = chain.spot_price
    strikes = chain.strikes

    above = sorted(
        [s for s in strikes if s.strike > spot],
        key=lambda s: s.ce.oi, reverse=True,
    )[:n]
    below = sorted(
        [s for s in strikes if s.strike < spot],
        key=lambda s: s.pe.oi, reverse=True,
    )[:n]

    top_ce = [{"strike": s.strike, "oi": s.ce.oi} for s in above]
    top_pe = [{"strike": s.strike, "oi": s.pe.oi} for s in below]
    return top_ce, top_pe


def _oi_wall_rows(
    chain: OptionChainResult,
    symbol: str,
    expiry: str,
    captured_at: datetime,
    n: int = _TOP_N_WALLS,
) -> list[OIWallSnapshot]:
    """Build OIWallSnapshot rows for the top-N CE and PE walls."""
    spot    = chain.spot_price
    strikes = chain.strikes

    above = sorted(
        [s for s in strikes if s.strike > spot],
        key=lambda s: s.ce.oi, reverse=True,
    )[:n]
    below = sorted(
        [s for s in strikes if s.strike < spot],
        key=lambda s: s.pe.oi, reverse=True,
    )[:n]

    rows: list[OIWallSnapshot] = []
    for rank, s in enumerate(above, start=1):
        rows.append(OIWallSnapshot(
            symbol=symbol, expiry=expiry, captured_at=captured_at,
            side="CE", rank=rank, strike=s.strike,
            oi=s.ce.oi, oi_change=s.ce.oi_change,
        ))
    for rank, s in enumerate(below, start=1):
        rows.append(OIWallSnapshot(
            symbol=symbol, expiry=expiry, captured_at=captured_at,
            side="PE", rank=rank, strike=s.strike,
            oi=s.pe.oi, oi_change=s.pe.oi_change,
        ))
    return rows


# ---------------------------------------------------------------------------
# Core write path
# ---------------------------------------------------------------------------

def store_snapshot(
    result: MaxPainResult,
    chain: OptionChainResult,
    captured_at: Optional[datetime] = None,
) -> MaxPainSnapshot:
    """
    Persist one MaxPainSnapshot + associated OIWallSnapshot rows.

    Args:
        result:      Typed MaxPainResult from calculate_max_pain().
        chain:       The OptionChainResult the result was derived from.
        captured_at: Timestamp to tag the snapshot (default: now UTC).

    Returns:
        The committed MaxPainSnapshot ORM object.

    Raises:
        SQLAlchemy errors on commit failure (caller should handle).
    """
    ts     = captured_at or datetime.now(timezone.utc)
    symbol = chain.symbol
    expiry = chain.expiry

    top_ce, top_pe = _top_walls(chain)

    # PCR bias label — plain string, no scoring
    if result.pcr > 1.2:
        pcr_bias = "bullish"
    elif result.pcr < 0.8:
        pcr_bias = "bearish"
    else:
        pcr_bias = "neutral"

    # Top pain strikes as compact JSON
    top_pain_json = [p.to_dict() for p in result.top_pain_strikes]

    snap = MaxPainSnapshot(
        id             = uuid.uuid4(),
        symbol         = symbol,
        expiry         = expiry,
        captured_at    = ts,
        spot_price     = result.spot_price,
        max_pain       = result.max_pain,
        distance_pct   = result.distance_pct,
        total_ce_oi    = result.total_ce_oi,
        total_pe_oi    = result.total_pe_oi,
        pcr            = result.pcr,
        pcr_bias       = pcr_bias,
        ce_wall_strike = result.ce_wall.strike if result.ce_wall else None,
        ce_wall_oi     = result.ce_wall.oi     if result.ce_wall else None,
        pe_wall_strike = result.pe_wall.strike if result.pe_wall else None,
        pe_wall_oi     = result.pe_wall.oi     if result.pe_wall else None,
        atm_ce_iv      = chain.atm_ce_iv,
        atm_pe_iv      = chain.atm_pe_iv,
        avg_iv         = round((chain.atm_ce_iv + chain.atm_pe_iv) / 2, 2)
                         if chain.atm_ce_iv and chain.atm_pe_iv else None,
        total_ce_volume = chain.total_ce_volume,
        total_pe_volume = chain.total_pe_volume,
        top_ce_strikes  = top_ce,
        top_pe_strikes  = top_pe,
        top_pain_strikes = top_pain_json,
    )
    db.session.add(snap)

    # OI wall rows for migration tracking
    for wall_row in _oi_wall_rows(chain, symbol, expiry, ts):
        db.session.add(wall_row)

    logger.debug(
        "Staged snapshot: symbol=%s expiry=%s max_pain=%.2f dist=%.2f%%",
        symbol, expiry, result.max_pain, result.distance_pct,
    )
    return snap


# ---------------------------------------------------------------------------
# Core read paths
# ---------------------------------------------------------------------------

def get_latest_snapshot(
    symbol: str,
    expiry: Optional[str] = None,
) -> Optional[MaxPainSnapshot]:
    """
    Return the most recent stored snapshot for symbol.
    Optionally filter by expiry.
    """
    q = (
        db.session.query(MaxPainSnapshot)
        .filter(MaxPainSnapshot.symbol == symbol.upper())
    )
    if expiry:
        q = q.filter(MaxPainSnapshot.expiry == expiry)
    return q.order_by(MaxPainSnapshot.captured_at.desc()).first()


def get_historical_snapshots(
    symbol: str,
    window: str = "1d",
    expiry: Optional[str] = None,
    max_points: int = 200,
) -> list[dict]:
    """
    Return time-series snapshots for symbol within the requested window.

    Args:
        symbol:     NSE symbol (case-insensitive).
        window:     One of "1h", "4h", "1d", "3d", "7d", "30d".
        expiry:     Optional expiry filter.
        max_points: Downsample to at most this many points.

    Returns:
        List of dicts ordered by captured_at ascending.
    """
    cutoff = _parse_window(window)
    q = (
        db.session.query(MaxPainSnapshot)
        .filter(MaxPainSnapshot.symbol == symbol.upper())
        .filter(MaxPainSnapshot.captured_at >= cutoff)
    )
    if expiry:
        q = q.filter(MaxPainSnapshot.expiry == expiry)

    rows = q.order_by(MaxPainSnapshot.captured_at.asc()).all()
    rows = _downsample(rows, max_points)
    return [r.to_dict() for r in rows]


# ---------------------------------------------------------------------------
# Capture helpers (fetch → compute → store)
# ---------------------------------------------------------------------------

def capture_symbol(
    symbol: str,
    expiry: Optional[str] = None,
    captured_at: Optional[datetime] = None,
) -> MaxPainSnapshot:
    """
    Fetch live option chain, compute max pain, and persist a snapshot.
    Commits the session on success; re-raises on error.
    """
    chain  = get_option_chain(symbol.upper(), expiry=expiry)
    result = calculate_max_pain(chain)
    ts     = captured_at or datetime.now(timezone.utc)

    snap   = store_snapshot(result, chain, captured_at=ts)
    db.session.commit()

    logger.info(
        "Captured snapshot: symbol=%s expiry=%s max_pain=%.2f dist=%.2f%% ts=%s",
        symbol, chain.expiry, result.max_pain, result.distance_pct,
        ts.isoformat(),
    )
    return snap


def capture_symbols(
    symbols: list[str],
    expiry: Optional[str] = None,
) -> dict:
    """
    Bulk-capture snapshots for a list of symbols in one transaction batch.

    Returns {"saved": int, "errors": [(symbol, message)], "captured_at": ISO8601}.
    """
    ts     = datetime.now(timezone.utc)
    saved  = 0
    errors = []

    for symbol in symbols:
        try:
            chain  = get_option_chain(symbol.upper(), expiry=expiry)
            result = calculate_max_pain(chain)
            store_snapshot(result, chain, captured_at=ts)
            saved += 1
        except Exception as exc:
            logger.error("Snapshot capture failed for %s: %s", symbol, exc)
            errors.append({"symbol": symbol, "error": str(exc)})

    if saved:
        try:
            db.session.commit()
            logger.info(
                "Snapshot batch committed: saved=%d errors=%d ts=%s",
                saved, len(errors), ts.isoformat(),
            )
        except Exception as exc:
            db.session.rollback()
            logger.error("Snapshot batch commit failed: %s", exc)
            raise

    return {
        "saved":       saved,
        "errors":      errors,
        "captured_at": ts.isoformat(),
        "total":       len(symbols),
    }


# ---------------------------------------------------------------------------
# Data retention / cleanup
# ---------------------------------------------------------------------------

def cleanup_old_snapshots(retention_days: int) -> int:
    """
    Delete snapshots older than retention_days from both tables.

    Returns total rows deleted.
    Commits its own transaction.
    """
    cutoff = datetime.now(timezone.utc) - timedelta(days=retention_days)

    wall_deleted = (
        db.session.query(OIWallSnapshot)
        .filter(OIWallSnapshot.captured_at < cutoff)
        .delete(synchronize_session=False)
    )
    snap_deleted = (
        db.session.query(MaxPainSnapshot)
        .filter(MaxPainSnapshot.captured_at < cutoff)
        .delete(synchronize_session=False)
    )
    db.session.commit()

    total = wall_deleted + snap_deleted
    logger.info(
        "Retention cleanup: deleted %d snapshot rows and %d wall rows "
        "(cutoff=%s retention_days=%d)",
        snap_deleted, wall_deleted, cutoff.date().isoformat(), retention_days,
    )
    return total
