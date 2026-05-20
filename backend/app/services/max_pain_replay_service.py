"""
Max Pain Replay Service
========================
Loads historical snapshots chronologically and computes forward returns
at multiple horizons for each signal point.

Design notes
------------
* A "signal" is any snapshot where distance_pct >= min_distance_pct.
* Forward return matching uses binary search over sorted captured_at timestamps.
* "Hit" is defined as strict convergence: the spot moved closer to the
  *signal's* max pain level within the horizon, regardless of whether max
  pain itself moved.  This is the only unambiguous definition — it cannot
  be retrofitted by changing the target after the fact.
* Convergence %: (original_dist - future_dist) / original_dist * 100
  Positive = converged, negative = diverged.
* We never fabricate outcomes: if no forward snapshot exists within the
  tolerance window (e.g. end of data, market closed), the horizon is
  recorded as None and excluded from statistics.

Public API
----------
    load_replay(symbol, expiry, window, min_distance_pct) -> list[ReplayPoint]
    load_replay_window(symbol, start, end, expiry)        -> list[ReplayPoint]
"""

from __future__ import annotations

import bisect
import logging
from dataclasses import dataclass, field, asdict
from datetime import datetime, timedelta, timezone
from typing import Optional

from app.extensions import db
from app.models.max_pain_snapshot import MaxPainSnapshot

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Horizon definitions
# ---------------------------------------------------------------------------

HORIZONS: dict[str, int] = {
    "15m": 15,
    "1h":  60,
    "4h":  240,
    "1d":  390,   # one trading session ≈ 6h 30m = 390 min
}

# How far from the exact target time a snapshot may be and still count
_HORIZON_TOLERANCE_MINUTES: dict[str, int] = {
    "15m": 4,
    "1h":  8,
    "4h":  20,
    "1d":  45,
}


# ---------------------------------------------------------------------------
# Data types
# ---------------------------------------------------------------------------

@dataclass
class HorizonOutcome:
    """Forward outcome at one time horizon."""
    horizon:             str           # "15m" | "1h" | "4h" | "1d"
    minutes:             int
    future_spot:         Optional[float]
    future_captured_at:  Optional[str]
    raw_return_pct:      Optional[float]   # (future - signal) / signal * 100
    convergent_pct:      Optional[float]   # positive = moved toward signal max_pain
    hit:                 Optional[bool]    # True if convergent_pct > 0

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class WallState:
    """OI wall state derived from consecutive snapshots."""
    ce_migrated:     bool  = False   # CE wall strike changed vs prior tick
    pe_migrated:     bool  = False
    ce_direction:    str   = "stable"   # "up" | "down" | "stable"
    pe_direction:    str   = "stable"
    wall_compressed: bool  = False   # CE and PE walls closer than prev tick
    wall_expanded:   bool  = False

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class ReplayPoint:
    """One signal point with attached forward outcomes."""
    # ── Signal snapshot fields ──────────────────────────────────────────────
    snapshot_id:      str
    symbol:           str
    expiry:           str
    captured_at:      str
    spot_price:       float
    max_pain:         float
    distance_pct:     float
    direction:        str        # "bullish" | "bearish" (spot below/above max pain)
    pcr:              float
    pcr_bias:         str
    avg_iv:           Optional[float]
    atm_ce_iv:        Optional[float]
    atm_pe_iv:        Optional[float]
    ce_wall_strike:   Optional[float]
    ce_wall_oi:       Optional[int]
    pe_wall_strike:   Optional[float]
    pe_wall_oi:       Optional[int]
    total_ce_oi:      Optional[int]
    total_pe_oi:      Optional[int]
    reversal_score:   Optional[float]

    # ── Derived signal fields ───────────────────────────────────────────────
    original_distance: float      # abs(spot - max_pain) in price units
    days_to_expiry:    int

    # ── Wall transition (vs prior tick) ────────────────────────────────────
    wall_state: WallState = field(default_factory=WallState)

    # ── Forward outcomes ────────────────────────────────────────────────────
    outcomes: dict[str, HorizonOutcome] = field(default_factory=dict)

    def to_dict(self) -> dict:
        d = {
            "snapshot_id":     self.snapshot_id,
            "symbol":          self.symbol,
            "expiry":          self.expiry,
            "captured_at":     self.captured_at,
            "spot_price":      self.spot_price,
            "max_pain":        self.max_pain,
            "distance_pct":    self.distance_pct,
            "direction":       self.direction,
            "pcr":             self.pcr,
            "pcr_bias":        self.pcr_bias,
            "avg_iv":          self.avg_iv,
            "atm_ce_iv":       self.atm_ce_iv,
            "atm_pe_iv":       self.atm_pe_iv,
            "ce_wall_strike":  self.ce_wall_strike,
            "ce_wall_oi":      self.ce_wall_oi,
            "pe_wall_strike":  self.pe_wall_strike,
            "pe_wall_oi":      self.pe_wall_oi,
            "total_ce_oi":     self.total_ce_oi,
            "total_pe_oi":     self.total_pe_oi,
            "reversal_score":  self.reversal_score,
            "original_distance": self.original_distance,
            "days_to_expiry":  self.days_to_expiry,
            "wall_state":      self.wall_state.to_dict(),
            "outcomes":        {k: v.to_dict() for k, v in self.outcomes.items()},
        }
        return d


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _days_to_expiry(expiry: Optional[str]) -> int:
    """Parse NSE expiry string 'DD-Mon-YYYY' → days remaining (0 if past/unknown)."""
    if not expiry:
        return 0
    try:
        exp_dt = datetime.strptime(expiry, "%d-%b-%Y")
        exp_dt = exp_dt.replace(tzinfo=timezone.utc)
        delta = (exp_dt - datetime.now(timezone.utc)).days
        return max(0, delta)
    except ValueError:
        return 0


def _find_forward(
    times: list[datetime],
    spots: list[float],
    from_idx: int,
    target_minutes: int,
    tolerance_minutes: int,
) -> tuple[Optional[float], Optional[datetime]]:
    """
    Binary-search `times` for the snapshot nearest to
    times[from_idx] + target_minutes, within ±tolerance_minutes.

    Returns (spot_price, captured_at) or (None, None) if not found.
    """
    origin    = times[from_idx]
    target_ts = origin + timedelta(minutes=target_minutes)
    tol       = timedelta(minutes=tolerance_minutes)

    lo = bisect.bisect_left(times, target_ts - tol, lo=from_idx + 1)
    hi = bisect.bisect_right(times, target_ts + tol, lo=lo)

    if lo >= hi:
        return None, None

    # Pick the index closest to target_ts
    best_idx = min(range(lo, hi), key=lambda i: abs(times[i] - target_ts))
    return spots[best_idx], times[best_idx]


def _wall_state(
    snap: MaxPainSnapshot,
    prev: Optional[MaxPainSnapshot],
) -> WallState:
    """Compute wall migration state vs the previous tick."""
    if prev is None:
        return WallState()

    ws = WallState()

    # CE wall migration
    if (snap.ce_wall_strike is not None and prev.ce_wall_strike is not None
            and snap.ce_wall_strike != prev.ce_wall_strike):
        ws.ce_migrated = True
        ws.ce_direction = "up" if snap.ce_wall_strike > prev.ce_wall_strike else "down"

    # PE wall migration
    if (snap.pe_wall_strike is not None and prev.pe_wall_strike is not None
            and snap.pe_wall_strike != prev.pe_wall_strike):
        ws.pe_migrated = True
        ws.pe_direction = "up" if snap.pe_wall_strike > prev.pe_wall_strike else "down"

    # Wall spread (CE wall - PE wall)
    def _spread(s: MaxPainSnapshot) -> Optional[float]:
        if s.ce_wall_strike is not None and s.pe_wall_strike is not None:
            return s.ce_wall_strike - s.pe_wall_strike
        return None

    curr_spread = _spread(snap)
    prev_spread = _spread(prev)
    if curr_spread is not None and prev_spread is not None:
        if curr_spread < prev_spread * 0.95:
            ws.wall_compressed = True
        elif curr_spread > prev_spread * 1.05:
            ws.wall_expanded = True

    return ws


def _build_outcome(
    horizon: str,
    minutes: int,
    signal_spot: float,
    signal_max_pain: float,
    future_spot: Optional[float],
    future_ts: Optional[datetime],
) -> HorizonOutcome:
    """Compute convergence metrics for one horizon."""
    if future_spot is None or signal_spot <= 0:
        return HorizonOutcome(
            horizon=horizon, minutes=minutes,
            future_spot=None, future_captured_at=None,
            raw_return_pct=None, convergent_pct=None, hit=None,
        )

    raw_ret = (future_spot - signal_spot) / signal_spot * 100

    # Convergence: did spot move closer to the signal's max pain?
    original_dist = abs(signal_spot  - signal_max_pain)
    future_dist   = abs(future_spot  - signal_max_pain)

    if original_dist == 0:
        convergent_pct = 0.0
        hit = False
    else:
        # Positive = converged, negative = diverged
        convergent_pct = (original_dist - future_dist) / original_dist * 100
        hit = convergent_pct > 0

    return HorizonOutcome(
        horizon=horizon,
        minutes=minutes,
        future_spot=round(future_spot, 2),
        future_captured_at=future_ts.isoformat() if future_ts else None,
        raw_return_pct=round(raw_ret, 4),
        convergent_pct=round(convergent_pct, 4),
        hit=hit,
    )


# ---------------------------------------------------------------------------
# Core loader
# ---------------------------------------------------------------------------

def _load_snapshots(
    symbol: str,
    start: datetime,
    end: datetime,
    expiry: Optional[str] = None,
) -> list[MaxPainSnapshot]:
    """Fetch all snapshots for symbol between start and end, sorted ascending."""
    q = (
        db.session.query(MaxPainSnapshot)
        .filter(MaxPainSnapshot.symbol == symbol.upper())
        .filter(MaxPainSnapshot.captured_at >= start)
        .filter(MaxPainSnapshot.captured_at <= end)
    )
    if expiry:
        q = q.filter(MaxPainSnapshot.expiry == expiry)
    return q.order_by(MaxPainSnapshot.captured_at.asc()).all()


def _snapshots_to_replay(
    all_snaps: list[MaxPainSnapshot],
    min_distance_pct: float = 0.0,
) -> list[ReplayPoint]:
    """
    Convert a sorted list of snapshots into ReplayPoint objects.

    The full snapshot list is used for forward matching even if only
    signals with distance_pct >= min_distance_pct are included in the
    output.  This ensures forward returns are correct for all signals.
    """
    if not all_snaps:
        return []

    # Build parallel time / spot arrays for binary search
    times: list[datetime] = [s.captured_at for s in all_snaps]
    spots: list[float]    = [s.spot_price or 0.0 for s in all_snaps]

    points: list[ReplayPoint] = []

    for idx, snap in enumerate(all_snaps):
        # Filter by minimum distance
        dist = snap.distance_pct or 0.0
        if dist < min_distance_pct:
            continue

        spot     = snap.spot_price or 0.0
        max_pain = snap.max_pain   or 0.0
        if spot <= 0 or max_pain <= 0:
            continue

        # Direction: spot above max_pain = expect bearish reversion
        direction = "bearish" if spot > max_pain else "bullish"

        # Wall state vs prior tick
        prev_snap = all_snaps[idx - 1] if idx > 0 else None
        ws = _wall_state(snap, prev_snap)

        # Build ReplayPoint
        rp = ReplayPoint(
            snapshot_id      = str(snap.id),
            symbol           = snap.symbol,
            expiry           = snap.expiry or "",
            captured_at      = snap.captured_at.isoformat(),
            spot_price       = spot,
            max_pain         = max_pain,
            distance_pct     = dist,
            direction        = direction,
            pcr              = snap.pcr or 0.0,
            pcr_bias         = snap.pcr_bias or "neutral",
            avg_iv           = snap.avg_iv,
            atm_ce_iv        = snap.atm_ce_iv,
            atm_pe_iv        = snap.atm_pe_iv,
            ce_wall_strike   = snap.ce_wall_strike,
            ce_wall_oi       = snap.ce_wall_oi,
            pe_wall_strike   = snap.pe_wall_strike,
            pe_wall_oi       = snap.pe_wall_oi,
            total_ce_oi      = snap.total_ce_oi,
            total_pe_oi      = snap.total_pe_oi,
            reversal_score   = snap.reversal_score,
            original_distance = abs(spot - max_pain),
            days_to_expiry   = _days_to_expiry(snap.expiry),
            wall_state       = ws,
        )

        # Attach forward outcomes for each horizon
        for label, mins in HORIZONS.items():
            tol = _HORIZON_TOLERANCE_MINUTES[label]
            future_spot, future_ts = _find_forward(times, spots, idx, mins, tol)
            rp.outcomes[label] = _build_outcome(
                horizon=label, minutes=mins,
                signal_spot=spot, signal_max_pain=max_pain,
                future_spot=future_spot, future_ts=future_ts,
            )

        points.append(rp)

    return points


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

_WINDOW_MAP: dict[str, timedelta] = {
    "1h":  timedelta(hours=1),
    "4h":  timedelta(hours=4),
    "1d":  timedelta(days=1),
    "3d":  timedelta(days=3),
    "7d":  timedelta(days=7),
    "30d": timedelta(days=30),
    "90d": timedelta(days=90),
}


def load_replay(
    symbol: str,
    expiry: Optional[str] = None,
    window: str = "30d",
    min_distance_pct: float = 0.0,
) -> list[ReplayPoint]:
    """
    Load and annotate all signal points for symbol within the window.

    Args:
        symbol:           NSE symbol (case-insensitive).
        expiry:           Optional — filter to a specific expiry.
        window:           Lookback period: "1h"|"4h"|"1d"|"3d"|"7d"|"30d"|"90d".
        min_distance_pct: Only return signals where distance_pct >= this value.

    Returns:
        List of ReplayPoint objects ordered by captured_at ascending.
        Each point includes forward outcomes at 15m, 1h, 4h, 1d horizons.
    """
    delta = _WINDOW_MAP.get(window, timedelta(days=30))
    now   = datetime.now(timezone.utc)
    # Extend end by 1d so that the last signal has room for 1d forward outcome
    start = now - delta
    end   = now + timedelta(days=1)

    all_snaps = _load_snapshots(symbol.upper(), start, end, expiry)
    logger.info(
        "Replay load: symbol=%s window=%s expiry=%s total_snaps=%d",
        symbol, window, expiry, len(all_snaps),
    )
    return _snapshots_to_replay(all_snaps, min_distance_pct=min_distance_pct)


def load_replay_window(
    symbol: str,
    start: datetime,
    end: datetime,
    expiry: Optional[str] = None,
    min_distance_pct: float = 0.0,
) -> list[ReplayPoint]:
    """
    Load replay data for an explicit datetime range.
    Useful for backtesting a specific market period.
    """
    all_snaps = _load_snapshots(symbol.upper(), start, end, expiry)
    return _snapshots_to_replay(all_snaps, min_distance_pct=min_distance_pct)
