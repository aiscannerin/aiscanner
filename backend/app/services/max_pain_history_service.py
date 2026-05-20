"""
Max Pain Historical Query Service
Efficient time-series queries for trend, drift, OI wall migration,
and reversal score history.
"""

import logging
from datetime import datetime, timedelta, timezone
from typing import Optional

from sqlalchemy import func, text

from app.extensions import db
from app.models.max_pain_snapshot import MaxPainSnapshot, OIWallSnapshot

logger = logging.getLogger(__name__)


# ── Helpers ───────────────────────────────────────────────────────────────────

def _parse_window(window: str) -> datetime:
    """Convert '1h'|'4h'|'1d'|'3d'|'7d'|'30d' → UTC cutoff datetime."""
    mapping = {
        "1h":  timedelta(hours=1),
        "4h":  timedelta(hours=4),
        "1d":  timedelta(days=1),
        "3d":  timedelta(days=3),
        "7d":  timedelta(days=7),
        "30d": timedelta(days=30),
    }
    delta = mapping.get(window, timedelta(days=1))
    return datetime.now(timezone.utc) - delta


def _downsample(rows: list, max_points: int = 200) -> list:
    """Thin a list of rows to at most max_points, preserving first and last."""
    if len(rows) <= max_points:
        return rows
    step = len(rows) / max_points
    indices = {0, len(rows) - 1}
    indices |= {round(i * step) for i in range(1, max_points - 1)}
    return [rows[i] for i in sorted(indices)]


# ── 1. Max Pain Trend ─────────────────────────────────────────────────────────

def get_max_pain_trend(
    symbol: str,
    window: str = "1d",
    expiry: Optional[str] = None,
    max_points: int = 200,
) -> dict:
    """
    Time-series of spot_price, max_pain, distance_pct, pcr, avg_iv
    for a symbol over the requested window.

    Returns:
    {
        "symbol": str,
        "window": str,
        "expiry": str | None,
        "points": int,
        "series": [
            {
                "t": ISO8601,
                "spot": float,
                "max_pain": float,
                "distance_pct": float,
                "pcr": float,
                "avg_iv": float,
                "reversal_score": float,
            }
        ]
    }
    """
    cutoff = _parse_window(window)
    q = (
        db.session.query(
            MaxPainSnapshot.captured_at,
            MaxPainSnapshot.spot_price,
            MaxPainSnapshot.max_pain,
            MaxPainSnapshot.distance_pct,
            MaxPainSnapshot.pcr,
            MaxPainSnapshot.avg_iv,
            MaxPainSnapshot.reversal_score,
        )
        .filter(MaxPainSnapshot.symbol == symbol.upper())
        .filter(MaxPainSnapshot.captured_at >= cutoff)
    )
    if expiry:
        q = q.filter(MaxPainSnapshot.expiry == expiry)

    rows = q.order_by(MaxPainSnapshot.captured_at.asc()).all()
    rows = _downsample(rows, max_points)

    series = [
        {
            "t":              r.captured_at.isoformat(),
            "spot":           r.spot_price,
            "max_pain":       r.max_pain,
            "distance_pct":   r.distance_pct,
            "pcr":            r.pcr,
            "avg_iv":         r.avg_iv,
            "reversal_score": r.reversal_score,
        }
        for r in rows
    ]

    return {
        "symbol": symbol.upper(),
        "window": window,
        "expiry": expiry,
        "points": len(series),
        "series": series,
    }


# ── 2. Max Pain Drift ─────────────────────────────────────────────────────────

def get_max_pain_drift(
    symbol: str,
    window: str = "1d",
    expiry: Optional[str] = None,
) -> dict:
    """
    Measures how far max pain has moved from its value at the start
    of the window. Also computes:
      - drift_pct: (latest_mp - oldest_mp) / oldest_mp * 100
      - spot_drift_pct: same for spot
      - convergence: spot is moving toward max pain (True/False)
      - distance trend: expanding / contracting / stable

    Returns summary stats plus a short time series of max_pain values.
    """
    cutoff = _parse_window(window)
    q = (
        db.session.query(
            MaxPainSnapshot.captured_at,
            MaxPainSnapshot.spot_price,
            MaxPainSnapshot.max_pain,
            MaxPainSnapshot.distance_pct,
        )
        .filter(MaxPainSnapshot.symbol == symbol.upper())
        .filter(MaxPainSnapshot.captured_at >= cutoff)
    )
    if expiry:
        q = q.filter(MaxPainSnapshot.expiry == expiry)

    rows = q.order_by(MaxPainSnapshot.captured_at.asc()).all()

    if not rows:
        return {"symbol": symbol, "window": window, "error": "no_data"}

    first, last = rows[0], rows[-1]

    def _pct_change(a, b):
        return round((b - a) / a * 100, 3) if a else None

    mp_drift    = _pct_change(first.max_pain,   last.max_pain)
    spot_drift  = _pct_change(first.spot_price, last.spot_price)

    # Convergence: distance shrinking = spot moving toward max pain
    dist_first = first.distance_pct or 0
    dist_last  = last.distance_pct  or 0
    if dist_last < dist_first * 0.9:
        dist_trend = "contracting"
    elif dist_last > dist_first * 1.1:
        dist_trend = "expanding"
    else:
        dist_trend = "stable"

    # Speed of max pain migration (points per hour)
    elapsed_hours = max(
        (last.captured_at - first.captured_at).total_seconds() / 3600, 0.001
    )
    mp_speed = round(abs((last.max_pain or 0) - (first.max_pain or 0)) / elapsed_hours, 2)

    downsampled = _downsample(rows, 100)
    mp_series = [
        {"t": r.captured_at.isoformat(), "max_pain": r.max_pain, "spot": r.spot_price}
        for r in downsampled
    ]

    return {
        "symbol":          symbol.upper(),
        "window":          window,
        "expiry":          expiry,
        "oldest_at":       first.captured_at.isoformat(),
        "latest_at":       last.captured_at.isoformat(),
        "oldest_max_pain": first.max_pain,
        "latest_max_pain": last.max_pain,
        "mp_drift_pct":    mp_drift,
        "spot_drift_pct":  spot_drift,
        "dist_trend":      dist_trend,
        "dist_first":      round(dist_first, 3),
        "dist_last":       round(dist_last, 3),
        "mp_speed_pts_hr": mp_speed,
        "data_points":     len(rows),
        "series":          mp_series,
    }


# ── 3. OI Wall Migration ──────────────────────────────────────────────────────

def get_oi_wall_migration(
    symbol: str,
    side: str = "CE",
    rank: int = 1,
    window: str = "1d",
    expiry: Optional[str] = None,
) -> dict:
    """
    Track how the dominant OI wall (rank=1 CE or PE) migrates over time.

    Returns a series of {t, strike, oi} showing the wall's position history.
    Multiple strikes = wall shifted; same strike = wall strengthened/weakened.
    """
    side = side.upper()
    if side not in ("CE", "PE"):
        raise ValueError("side must be CE or PE")

    cutoff = _parse_window(window)
    q = (
        db.session.query(
            OIWallSnapshot.captured_at,
            OIWallSnapshot.strike,
            OIWallSnapshot.oi,
            OIWallSnapshot.oi_change,
        )
        .filter(OIWallSnapshot.symbol == symbol.upper())
        .filter(OIWallSnapshot.side   == side)
        .filter(OIWallSnapshot.rank   == rank)
        .filter(OIWallSnapshot.captured_at >= cutoff)
    )
    if expiry:
        q = q.filter(OIWallSnapshot.expiry == expiry)

    rows = q.order_by(OIWallSnapshot.captured_at.asc()).all()

    if not rows:
        return {"symbol": symbol, "side": side, "window": window, "error": "no_data"}

    series = [
        {
            "t":         r.captured_at.isoformat(),
            "strike":    r.strike,
            "oi":        r.oi,
            "oi_change": r.oi_change,
        }
        for r in rows
    ]

    # Detect wall shifts (strike changed)
    shifts = []
    prev_strike = None
    for pt in series:
        if prev_strike is not None and pt["strike"] != prev_strike:
            shifts.append({
                "t":          pt["t"],
                "from_strike": prev_strike,
                "to_strike":   pt["strike"],
            })
        prev_strike = pt["strike"]

    # Net strike migration
    net_migration = round(series[-1]["strike"] - series[0]["strike"], 0) if len(series) > 1 else 0

    return {
        "symbol":        symbol.upper(),
        "side":          side,
        "rank":          rank,
        "window":        window,
        "expiry":        expiry,
        "data_points":   len(series),
        "initial_strike": series[0]["strike"] if series else None,
        "current_strike": series[-1]["strike"] if series else None,
        "net_migration":  net_migration,
        "wall_shifts":    shifts,
        "shift_count":    len(shifts),
        "series":         _downsample(series, 200),
    }


# ── 4. Reversal Score History ─────────────────────────────────────────────────

def get_reversal_score_history(
    symbol: str,
    window: str = "1d",
    expiry: Optional[str] = None,
) -> dict:
    """
    Full time-series of reversal_score + category for one symbol.
    Also computes: peak score, trough score, current score,
    and whether score is accelerating or decelerating.
    """
    cutoff = _parse_window(window)
    q = (
        db.session.query(
            MaxPainSnapshot.captured_at,
            MaxPainSnapshot.reversal_score,
            MaxPainSnapshot.reversal_category,
            MaxPainSnapshot.distance_pct,
            MaxPainSnapshot.direction,
        )
        .filter(MaxPainSnapshot.symbol == symbol.upper())
        .filter(MaxPainSnapshot.captured_at >= cutoff)
    )
    if expiry:
        q = q.filter(MaxPainSnapshot.expiry == expiry)

    rows = q.order_by(MaxPainSnapshot.captured_at.asc()).all()

    if not rows:
        return {"symbol": symbol, "window": window, "error": "no_data"}

    scores = [r.reversal_score for r in rows if r.reversal_score is not None]
    series = [
        {
            "t":        r.captured_at.isoformat(),
            "score":    r.reversal_score,
            "category": r.reversal_category,
            "distance": r.distance_pct,
            "direction": r.direction,
        }
        for r in rows
    ]

    # Momentum: compare second half average to first half
    mid = len(scores) // 2
    first_half_avg = sum(scores[:mid]) / mid if mid else 0
    second_half_avg = sum(scores[mid:]) / (len(scores) - mid) if (len(scores) - mid) else 0
    if second_half_avg > first_half_avg * 1.05:
        momentum = "accelerating"
    elif second_half_avg < first_half_avg * 0.95:
        momentum = "decelerating"
    else:
        momentum = "stable"

    return {
        "symbol":          symbol.upper(),
        "window":          window,
        "expiry":          expiry,
        "data_points":     len(series),
        "current_score":   scores[-1] if scores else None,
        "peak_score":      max(scores) if scores else None,
        "trough_score":    min(scores) if scores else None,
        "avg_score":       round(sum(scores) / len(scores), 1) if scores else None,
        "momentum":        momentum,
        "series":          _downsample(series, 200),
    }


# ── 5. Multi-symbol snapshot summary (for dashboard sparklines) ───────────────

def get_latest_snapshots(symbols: list) -> list:
    """Return the most recent MaxPainSnapshot for each of the given symbols."""
    # One subquery per symbol is expensive at scale — use DISTINCT ON (PostgreSQL)
    subq = (
        db.session.query(
            MaxPainSnapshot,
            func.row_number().over(
                partition_by=MaxPainSnapshot.symbol,
                order_by=MaxPainSnapshot.captured_at.desc(),
            ).label("rn"),
        )
        .filter(MaxPainSnapshot.symbol.in_([s.upper() for s in symbols]))
        .subquery()
    )

    from sqlalchemy.orm import aliased
    mps = aliased(MaxPainSnapshot, subq)
    rows = db.session.query(mps).filter(subq.c.rn == 1).all()
    return [r.to_dict() for r in rows]
