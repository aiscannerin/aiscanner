"""
Max Pain Validation Service
=============================
Computes statistical validation of stored max pain signals using
the replay data produced by max_pain_replay_service.

Statistical rigour
------------------
* All statistics are computed from real stored data only.
* Binomial significance test (normal approximation) is applied to hit_rate.
* Small-sample warnings are raised for N < 30.
* No accuracy is fabricated or inflated.
* Each regime is an independent sub-population — no cherry-picking.

Formula references
------------------
Expectancy = hit_rate * avg_win_pct - (1 - hit_rate) * avg_loss_pct
  where win = convergent_pct when hit=True, loss = |convergent_pct| when hit=False

Binomial p-value (two-tailed, H₀: hit_rate = 0.5):
  z = (hits - n * 0.5) / sqrt(n * 0.25)
  p = erfc(|z| / sqrt(2))   [using math.erfc]

Confidence score (0–1):
  Combines sample size adequacy, hit_rate magnitude, and p-value significance.
  Explicitly NOT a prediction accuracy — it reflects how much we can trust the
  computed hit_rate given the data available.

Public API
----------
    compute_symbol_validation(symbol, expiry, window, min_distance_pct)
        -> ValidationReport

    compute_summary_validation(symbols, window, min_distance_pct)
        -> dict
"""

from __future__ import annotations

import logging
import math
import statistics
from dataclasses import dataclass, field
from typing import Optional

from app.services.max_pain_replay_service import (
    ReplayPoint,
    load_replay,
    HORIZONS,
)
from app.services.regime_classifier import infer_static_regime

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Thresholds
# ---------------------------------------------------------------------------

_MIN_SAMPLE_WARN    = 30    # below this, add "insufficient_data" warning
_MIN_SAMPLE_COMPUTE = 5     # below this, refuse to compute (not meaningful)
_SIG_LEVEL          = 0.05  # p-value threshold for "statistically significant"

# IV regime thresholds (%)
_IV_HIGH  = 20.0
_IV_LOW   = 12.0

# Distance regime thresholds
_DIST_HIGH = 4.0
_DIST_MOD  = 2.0

# PCR extremes
_PCR_BULL = 1.3
_PCR_BEAR = 0.8

# Expiry proximity
_EXPIRY_WEEK_DAYS = 5


# ---------------------------------------------------------------------------
# Pure statistics utilities (stdlib only — no numpy/scipy)
# ---------------------------------------------------------------------------

def _mean(values: list[float]) -> Optional[float]:
    if not values:
        return None
    return statistics.mean(values)


def _stdev(values: list[float]) -> Optional[float]:
    if len(values) < 2:
        return None
    return statistics.pstdev(values)   # population stdev (we have all data)


def _percentile(values: list[float], pct: float) -> Optional[float]:
    """Compute percentile using nearest-rank method."""
    if not values:
        return None
    s = sorted(values)
    idx = max(0, math.ceil(pct / 100.0 * len(s)) - 1)
    return s[idx]


def _binomial_p_value(hits: int, n: int) -> Optional[float]:
    """
    Two-tailed binomial p-value for H₀: p = 0.5.
    Uses normal approximation: valid for n >= 10.
    Returns None if n < 10.
    """
    if n < 10:
        return None
    p0  = 0.5
    # z-score with continuity correction
    z   = (abs(hits - n * p0) - 0.5) / math.sqrt(n * p0 * (1 - p0))
    # erfc(x) = 2 * P(Z > x*sqrt(2)) for Z ~ N(0,1)
    p   = math.erfc(z / math.sqrt(2))
    return round(min(1.0, p), 4)


def _confidence_score(n: int, hit_rate: float, p_value: Optional[float]) -> float:
    """
    Composite confidence score 0.0–1.0.
    Reflects how reliable the computed hit_rate is, NOT predictive accuracy.

    Components:
      Sample size contribution (0.0–0.5):
        n >= 100 → 0.5
        n >= 50  → 0.4
        n >= 30  → 0.3
        n >= 15  → 0.2
        n <  15  → 0.1
      Effect size contribution (0.0–0.3):
        |hit_rate - 0.5| >= 0.20 → 0.3
        |hit_rate - 0.5| >= 0.10 → 0.2
        otherwise → 0.0
      Significance contribution (0.0–0.2):
        p < 0.01 → 0.2
        p < 0.05 → 0.1
        otherwise → 0.0
    """
    # Sample size
    if n >= 100:   sc = 0.5
    elif n >= 50:  sc = 0.4
    elif n >= 30:  sc = 0.3
    elif n >= 15:  sc = 0.2
    else:          sc = 0.1

    # Effect size
    effect = abs(hit_rate - 0.5)
    if effect >= 0.20:  ec = 0.3
    elif effect >= 0.10: ec = 0.2
    else:                ec = 0.0

    # Significance
    if p_value is None:   sig = 0.0
    elif p_value < 0.01:  sig = 0.2
    elif p_value < 0.05:  sig = 0.1
    else:                 sig = 0.0

    return round(min(1.0, sc + ec + sig), 3)


# ---------------------------------------------------------------------------
# Core statistics builder
# ---------------------------------------------------------------------------

@dataclass
class HorizonStats:
    """Validation statistics for one time horizon."""
    horizon:          str
    sample_size:      int
    available:        int               # signals with a resolved forward outcome
    hit_count:        int
    miss_count:       int
    hit_rate:         Optional[float]
    avg_convergent_pct: Optional[float]  # mean convergence when hit
    avg_divergent_pct:  Optional[float]  # mean divergence when miss (as positive)
    avg_raw_return_pct: Optional[float]  # raw (unsigned) spot return
    std_convergent_pct: Optional[float]
    max_convergent_pct: Optional[float]  # best case convergence
    p95_convergent_pct: Optional[float]
    expectancy_pct:    Optional[float]   # hit_rate * avg_win - (1-hr) * avg_loss
    p_value:           Optional[float]
    confidence_score:  float
    is_significant:    bool
    warnings:          list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "horizon":             self.horizon,
            "sample_size":         self.sample_size,
            "available":           self.available,
            "hit_count":           self.hit_count,
            "miss_count":          self.miss_count,
            "hit_rate":            self.hit_rate,
            "avg_convergent_pct":  self.avg_convergent_pct,
            "avg_divergent_pct":   self.avg_divergent_pct,
            "avg_raw_return_pct":  self.avg_raw_return_pct,
            "std_convergent_pct":  self.std_convergent_pct,
            "max_convergent_pct":  self.max_convergent_pct,
            "p95_convergent_pct":  self.p95_convergent_pct,
            "expectancy_pct":      self.expectancy_pct,
            "p_value":             self.p_value,
            "confidence_score":    self.confidence_score,
            "is_significant":      self.is_significant,
            "warnings":            self.warnings,
        }


@dataclass
class RegimeBreakdown:
    """Per-regime validation stats for one horizon."""
    regime:    str
    count:     int
    stats:     Optional[HorizonStats]

    def to_dict(self) -> dict:
        return {
            "regime": self.regime,
            "count":  self.count,
            "stats":  self.stats.to_dict() if self.stats else None,
        }


@dataclass
class OIWallAnalysis:
    """Aggregate OI wall behaviour stats."""
    total_ticks:            int
    ce_migration_count:     int
    pe_migration_count:     int
    ce_migration_rate:      Optional[float]
    pe_migration_rate:      Optional[float]
    wall_compression_count: int
    wall_expansion_count:   int

    def to_dict(self) -> dict:
        return {
            "total_ticks":            self.total_ticks,
            "ce_migration_count":     self.ce_migration_count,
            "pe_migration_count":     self.pe_migration_count,
            "ce_migration_rate":      self.ce_migration_rate,
            "pe_migration_rate":      self.pe_migration_rate,
            "wall_compression_count": self.wall_compression_count,
            "wall_expansion_count":   self.wall_expansion_count,
        }


@dataclass
class ValidationReport:
    """Full validation report for one symbol × window."""
    symbol:           str
    window:           str
    expiry:           Optional[str]
    total_signals:    int
    min_distance_pct: float
    signal_stats: dict        # basic signal distribution stats
    horizons:     dict[str, HorizonStats]
    regimes:      dict[str, dict[str, RegimeBreakdown]]   # horizon → regime → stats
    oi_wall:      OIWallAnalysis
    generated_at: str

    def to_dict(self) -> dict:
        return {
            "symbol":          self.symbol,
            "window":          self.window,
            "expiry":          self.expiry,
            "total_signals":   self.total_signals,
            "min_distance_pct": self.min_distance_pct,
            "signal_stats":    self.signal_stats,
            "horizons":        {h: s.to_dict() for h, s in self.horizons.items()},
            "regimes":         {
                h: {r: rb.to_dict() for r, rb in rd.items()}
                for h, rd in self.regimes.items()
            },
            "oi_wall":         self.oi_wall.to_dict(),
            "generated_at":    self.generated_at,
        }


# ---------------------------------------------------------------------------
# Statistics builder
# ---------------------------------------------------------------------------

def _compute_horizon_stats(
    points: list[ReplayPoint],
    horizon: str,
) -> HorizonStats:
    """Compute validation statistics for a set of replay points at one horizon."""
    n = len(points)
    warnings: list[str] = []

    # Collect outcomes
    conv_pcts:  list[float] = []
    raw_rets:   list[float] = []
    hits:       list[bool]  = []

    for p in points:
        o = p.outcomes.get(horizon)
        if o is None or o.hit is None:
            continue
        hits.append(o.hit)
        if o.convergent_pct is not None:
            conv_pcts.append(o.convergent_pct)
        if o.raw_return_pct is not None:
            raw_rets.append(o.raw_return_pct)

    available = len(hits)

    if available < _MIN_SAMPLE_COMPUTE:
        warnings.append(f"insufficient_data: only {available} resolved outcomes at {horizon}")
        return HorizonStats(
            horizon=horizon, sample_size=n, available=available,
            hit_count=0, miss_count=0, hit_rate=None,
            avg_convergent_pct=None, avg_divergent_pct=None, avg_raw_return_pct=None,
            std_convergent_pct=None, max_convergent_pct=None, p95_convergent_pct=None,
            expectancy_pct=None, p_value=None, confidence_score=0.0,
            is_significant=False, warnings=warnings,
        )

    if available < _MIN_SAMPLE_WARN:
        warnings.append(
            f"small_sample: {available} samples at {horizon} — "
            f"statistics are unreliable below {_MIN_SAMPLE_WARN}"
        )

    hit_count  = sum(1 for h in hits if h)
    miss_count = available - hit_count
    hit_rate   = round(hit_count / available, 4)

    # Split convergence by hit / miss
    wins  = [c for c, h in zip(conv_pcts, hits) if h]
    losses = [abs(c) for c, h in zip(conv_pcts, hits) if not h]

    avg_win  = _mean(wins)
    avg_loss = _mean(losses)

    # Expectancy: positive means edge, negative means no edge
    expectancy = None
    if avg_win is not None and avg_loss is not None:
        expectancy = round(hit_rate * avg_win - (1 - hit_rate) * avg_loss, 4)

    p_val = _binomial_p_value(hit_count, available)
    conf  = _confidence_score(available, hit_rate, p_val)

    return HorizonStats(
        horizon=horizon,
        sample_size=n,
        available=available,
        hit_count=hit_count,
        miss_count=miss_count,
        hit_rate=hit_rate,
        avg_convergent_pct=round(_mean(wins), 4)          if wins   else None,
        avg_divergent_pct= round(_mean(losses), 4)        if losses else None,
        avg_raw_return_pct=round(_mean(raw_rets), 4)      if raw_rets else None,
        std_convergent_pct=round(_stdev(conv_pcts), 4)    if len(conv_pcts) >= 2 else None,
        max_convergent_pct=round(max(conv_pcts), 4)       if conv_pcts else None,
        p95_convergent_pct=round(_percentile(conv_pcts, 95), 4) if conv_pcts else None,
        expectancy_pct=expectancy,
        p_value=p_val,
        confidence_score=conf,
        is_significant=(p_val is not None and p_val < _SIG_LEVEL),
        warnings=warnings,
    )


# ---------------------------------------------------------------------------
# Regime classification
# ---------------------------------------------------------------------------

_REGIMES = {
    # ── Expiry proximity ──────────────────────────────────────────────────────
    "expiry_week":       lambda p: p.days_to_expiry <= _EXPIRY_WEEK_DAYS,
    "non_expiry_week":   lambda p: p.days_to_expiry >  _EXPIRY_WEEK_DAYS,

    # ── Volatility state ─────────────────────────────────────────────────────
    "high_iv":           lambda p: (p.avg_iv or 0) >= _IV_HIGH,
    "low_iv":            lambda p: 0 < (p.avg_iv or 0) <= _IV_LOW,
    "normal_iv":         lambda p: _IV_LOW < (p.avg_iv or 0) < _IV_HIGH,

    # ── Distance from max pain ────────────────────────────────────────────────
    "high_distance":     lambda p: p.distance_pct >= _DIST_HIGH,
    "moderate_distance": lambda p: _DIST_MOD <= p.distance_pct < _DIST_HIGH,
    "low_distance":      lambda p: p.distance_pct < _DIST_MOD,

    # ── PCR bias ─────────────────────────────────────────────────────────────
    "pcr_bullish":       lambda p: p.pcr >= _PCR_BULL,
    "pcr_bearish":       lambda p: p.pcr <= _PCR_BEAR,
    "pcr_neutral":       lambda p: _PCR_BEAR < p.pcr < _PCR_BULL,

    # ── Signal direction ──────────────────────────────────────────────────────
    "bullish_signal":    lambda p: p.direction == "bullish",
    "bearish_signal":    lambda p: p.direction == "bearish",

    # ── OI wall state ─────────────────────────────────────────────────────────
    "wall_migrating":    lambda p: p.wall_state.ce_migrated or p.wall_state.pe_migrated,
    "wall_stable":       lambda p: not p.wall_state.ce_migrated and not p.wall_state.pe_migrated,
    "wall_compressing":  lambda p: p.wall_state.wall_compressed,

    # ── Static regime proxies (no rolling window — current-state only) ────────
    # These approximate temporal regimes from single-point features.
    "expiry_pinning":       lambda p: p.days_to_expiry <= 3 and p.distance_pct < 1.5,
    "high_extension":       lambda p: p.distance_pct >= 4.0,
    "moderate_extension":   lambda p: 2.0 <= p.distance_pct < 4.0,
    "pcr_divergent":        lambda p: (
        (p.direction == "bearish" and p.pcr > _PCR_BULL) or
        (p.direction == "bullish" and p.pcr < _PCR_BEAR)
    ),
    "pcr_aligned":          lambda p: (
        (p.direction == "bullish" and p.pcr >= _PCR_BULL) or
        (p.direction == "bearish" and p.pcr <= _PCR_BEAR)
    ),
}


def _segment_regimes(points: list[ReplayPoint]) -> dict[str, list[ReplayPoint]]:
    """Partition points into regime buckets (non-exclusive)."""
    buckets: dict[str, list[ReplayPoint]] = {r: [] for r in _REGIMES}
    for p in points:
        for regime, test in _REGIMES.items():
            try:
                if test(p):
                    buckets[regime].append(p)
            except Exception:
                pass
    return buckets


# ---------------------------------------------------------------------------
# OI wall analysis
# ---------------------------------------------------------------------------

def _oi_wall_analysis(points: list[ReplayPoint]) -> OIWallAnalysis:
    n  = len(points)
    ce = sum(1 for p in points if p.wall_state.ce_migrated)
    pe = sum(1 for p in points if p.wall_state.pe_migrated)
    wc = sum(1 for p in points if p.wall_state.wall_compressed)
    we = sum(1 for p in points if p.wall_state.wall_expanded)
    return OIWallAnalysis(
        total_ticks=n,
        ce_migration_count=ce,
        pe_migration_count=pe,
        ce_migration_rate=round(ce / n, 4) if n else None,
        pe_migration_rate=round(pe / n, 4) if n else None,
        wall_compression_count=wc,
        wall_expansion_count=we,
    )


# ---------------------------------------------------------------------------
# Signal distribution summary
# ---------------------------------------------------------------------------

def _signal_stats(points: list[ReplayPoint]) -> dict:
    if not points:
        return {}

    dists = [p.distance_pct for p in points]
    pcrs  = [p.pcr          for p in points if p.pcr > 0]
    ivs   = [p.avg_iv       for p in points if p.avg_iv]
    dtes  = [p.days_to_expiry for p in points]

    return {
        "count":                 len(points),
        "bullish_signals":       sum(1 for p in points if p.direction == "bullish"),
        "bearish_signals":       sum(1 for p in points if p.direction == "bearish"),
        "distance_pct": {
            "mean":  round(_mean(dists), 3) if dists else None,
            "min":   round(min(dists), 3)   if dists else None,
            "max":   round(max(dists), 3)   if dists else None,
            "stdev": round(_stdev(dists), 3) if dists else None,
            "p25":   round(_percentile(dists, 25), 3) if dists else None,
            "p75":   round(_percentile(dists, 75), 3) if dists else None,
        },
        "pcr": {
            "mean":  round(_mean(pcrs), 3) if pcrs else None,
            "min":   round(min(pcrs), 3)   if pcrs else None,
            "max":   round(max(pcrs), 3)   if pcrs else None,
        },
        "avg_iv": {
            "mean":  round(_mean(ivs), 2)   if ivs else None,
            "min":   round(min(ivs), 2)     if ivs else None,
            "max":   round(max(ivs), 2)     if ivs else None,
        },
        "days_to_expiry": {
            "mean":          round(_mean(dtes), 1) if dtes else None,
            "expiry_week_pct": round(
                sum(1 for d in dtes if d <= _EXPIRY_WEEK_DAYS) / len(dtes), 3
            ) if dtes else None,
        },
    }


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

_EXPIRY_PROXIMITY_MAP = {
    "near": lambda p: p.days_to_expiry <= _EXPIRY_WEEK_DAYS,
    "far":  lambda p: p.days_to_expiry >  _EXPIRY_WEEK_DAYS,
}

_VOL_STATE_MAP = {
    "high_iv":   lambda p: (p.avg_iv or 0) >= _IV_HIGH,
    "low_iv":    lambda p: 0 < (p.avg_iv or 0) <= _IV_LOW,
    "normal_iv": lambda p: _IV_LOW < (p.avg_iv or 0) < _IV_HIGH,
}


def _apply_filters(
    points:           list[ReplayPoint],
    regime_filter:    Optional[str],
    expiry_proximity: Optional[str],
    vol_state:        Optional[str],
) -> tuple[list[ReplayPoint], list[str]]:
    """
    Apply zero or more named filters to a list of ReplayPoints.

    Returns (filtered_points, active_filter_descriptions).
    Emits a warning string for each filter with an insufficient result set.
    """
    filtered = points
    active   : list[str] = []
    warnings : list[str] = []

    if expiry_proximity and expiry_proximity in _EXPIRY_PROXIMITY_MAP:
        fn       = _EXPIRY_PROXIMITY_MAP[expiry_proximity]
        filtered = [p for p in filtered if fn(p)]
        active.append(f"expiry_proximity={expiry_proximity}")

    if vol_state and vol_state in _VOL_STATE_MAP:
        fn       = _VOL_STATE_MAP[vol_state]
        filtered = [p for p in filtered if fn(p)]
        active.append(f"vol_state={vol_state}")

    if regime_filter and regime_filter in _REGIMES:
        fn       = _REGIMES[regime_filter]
        filtered = [p for p in filtered if _safe_regime_test(fn, p)]
        active.append(f"regime={regime_filter}")
    elif regime_filter:
        warnings.append(
            f"unknown_regime_filter: '{regime_filter}' — "
            f"valid values: {sorted(_REGIMES.keys())}"
        )

    if active and len(filtered) < _MIN_SAMPLE_WARN:
        warnings.append(
            f"small_filtered_sample: filters [{', '.join(active)}] "
            f"left only {len(filtered)} signals — statistics may be unreliable"
        )

    return filtered, warnings


def _safe_regime_test(fn, point: ReplayPoint) -> bool:
    """Call a regime lambda, returning False on any exception."""
    try:
        return bool(fn(point))
    except Exception:
        return False


def compute_symbol_validation(
    symbol:           str,
    expiry:           Optional[str] = None,
    window:           str           = "30d",
    min_distance_pct: float         = 0.0,
    regime_filter:    Optional[str] = None,
    expiry_proximity: Optional[str] = None,
    vol_state:        Optional[str] = None,
) -> ValidationReport:
    """
    Full validation report for one symbol.

    Args:
        symbol:           NSE symbol.
        expiry:           Optional expiry filter.
        window:           Lookback window (e.g. "30d", "7d").
        min_distance_pct: Minimum distance % to include as a signal.
        regime_filter:    Optional — filter signals by regime label.
                          Any key in _REGIMES is valid (e.g. "expiry_week",
                          "high_iv", "expiry_pinning", "pcr_aligned", …).
        expiry_proximity: "near" (DTE ≤ 5) | "far" (DTE > 5) | None (all).
        vol_state:        "high_iv" | "low_iv" | "normal_iv" | None (all).

    Returns:
        ValidationReport with per-horizon stats, regime breakdown, OI wall analysis.
        When filters are active, all statistics apply only to the filtered subset.
        The report includes the active filter set and any filter-related warnings.
    """
    from datetime import datetime, timezone as tz
    now = datetime.now(tz.utc)

    points = load_replay(
        symbol=symbol,
        expiry=expiry,
        window=window,
        min_distance_pct=min_distance_pct,
    )

    # Apply optional filters
    points, filter_warnings = _apply_filters(
        points, regime_filter, expiry_proximity, vol_state
    )

    logger.info(
        "Validation: symbol=%s window=%s signals=%d min_dist=%.1f%% "
        "regime_filter=%s expiry_proximity=%s vol_state=%s",
        symbol, window, len(points), min_distance_pct,
        regime_filter, expiry_proximity, vol_state,
    )

    # Per-horizon statistics (filtered signals)
    horizon_stats: dict[str, HorizonStats] = {
        h: _compute_horizon_stats(points, h) for h in HORIZONS
    }

    # Inject filter warnings into each horizon
    for hs in horizon_stats.values():
        hs.warnings = filter_warnings + hs.warnings

    # Regime breakdown per horizon
    regime_buckets = _segment_regimes(points)
    regimes: dict[str, dict[str, RegimeBreakdown]] = {}
    for h in HORIZONS:
        regimes[h] = {}
        for regime, bucket in regime_buckets.items():
            if not bucket:
                continue
            bucket_stats = (
                _compute_horizon_stats(bucket, h)
                if len(bucket) >= _MIN_SAMPLE_COMPUTE
                else None
            )
            regimes[h][regime] = RegimeBreakdown(
                regime=regime, count=len(bucket), stats=bucket_stats
            )

    return ValidationReport(
        symbol=symbol.upper(),
        window=window,
        expiry=expiry,
        total_signals=len(points),
        min_distance_pct=min_distance_pct,
        signal_stats=_signal_stats(points),
        horizons=horizon_stats,
        regimes=regimes,
        oi_wall=_oi_wall_analysis(points),
        generated_at=now.isoformat(),
    )


def compute_summary_validation(
    symbols: Optional[list[str]] = None,
    window: str = "30d",
    min_distance_pct: float = 2.0,
) -> dict:
    """
    Cross-symbol aggregate validation.
    Pools all signals across symbols and recomputes statistics.

    Returns a summary dict with per-horizon aggregate stats plus a
    per-symbol sample-size table.
    """
    from app.services.max_pain_scanner_service import DEFAULT_FO_UNIVERSE
    from datetime import datetime, timezone as tz
    now = datetime.now(tz.utc)

    target = symbols or DEFAULT_FO_UNIVERSE[:10]   # limit for performance

    all_points: list[ReplayPoint] = []
    per_symbol: dict[str, int] = {}

    for sym in target:
        try:
            pts = load_replay(sym, window=window, min_distance_pct=min_distance_pct)
            all_points.extend(pts)
            per_symbol[sym] = len(pts)
        except Exception as exc:
            logger.warning("Summary validation error for %s: %s", sym, exc)
            per_symbol[sym] = 0

    logger.info(
        "Summary validation: %d symbols, %d total signals (window=%s)",
        len(target), len(all_points), window,
    )

    horizon_stats = {h: _compute_horizon_stats(all_points, h) for h in HORIZONS}
    regime_buckets = _segment_regimes(all_points)

    regime_summary: dict[str, dict] = {}
    for regime, bucket in regime_buckets.items():
        if len(bucket) < _MIN_SAMPLE_COMPUTE:
            continue
        regime_summary[regime] = {
            "count":   len(bucket),
            "horizons": {
                h: _compute_horizon_stats(bucket, h).to_dict() for h in HORIZONS
            },
        }

    return {
        "window":          window,
        "min_distance_pct": min_distance_pct,
        "symbols_analysed": len(target),
        "total_signals":   len(all_points),
        "per_symbol":      per_symbol,
        "horizons":        {h: s.to_dict() for h, s in horizon_stats.items()},
        "regimes":         regime_summary,
        "generated_at":    now.isoformat(),
    }
