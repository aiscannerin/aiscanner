"""
Market Regime Classifier
========================
Classifies sequences of MaxPainSnapshot objects into discrete market regimes
using rolling-window time-series analysis. All computation uses Python stdlib
only — no numpy, scipy, or external ML libraries.

Regimes (non-exclusive: a snapshot may belong to multiple)
----------------------------------------------------------
trending              Consistent directional spot movement.
                      Detected via high OLS R² and significant drift t-stat.
range_bound           Low drift, mean-reverting returns, tight price range.
                      Detected via low R², negative lag-1 ACF, narrow range.
volatility_expansion  IV and/or realised vol rising in the window.
                      Detected via positive OLS slope on avg_iv series.
volatility_compression IV and/or realised vol falling.
                      Detected via negative OLS slope on avg_iv series.
expiry_pinning        DTE ≤ 5, spot close to max pain, balanced OI.
                      Computed from current snapshot state only.
exhaustion            High distance_pct, but distance no longer growing.
                      Detected via large distance + near-zero/negative slope.
momentum_continuation Distance growing, PCR aligned with signal direction.
                      Detected via rising distance slope + confirming PCR.

Classification approach
-----------------------
Each regime has an independent scorer returning (score ∈ [0,1], metrics).
Primary regime = argmax over scores.
Secondary regimes = all regimes with score ≥ SECONDARY_THRESHOLD.
Confidence = primary_score × data_quality_factor
data_quality_factor = min(1.0, n_window / IDEAL_WINDOW)

Temporal regimes (trending, range_bound, vol_expansion, vol_compression,
exhaustion, momentum_continuation) require at least MIN_WINDOW snapshots
in the rolling window. With fewer snapshots only expiry_pinning is
classified (from current state alone) and confidence is capped.

Mathematical references
-----------------------
R²    — coefficient of determination for OLS fit to spot prices.
        Measures directional linearity of price movement.
ACF₁  — lag-1 autocorrelation of log returns.
        Negative values indicate mean-reversion.
t-stat — |μ| / (σ / √n) tests H₀: drift = 0 for log returns.
IV slope — OLS slope on avg_iv series, normalised by mean IV.

Public API
----------
    classify_snapshot(snap, window)        -> RegimeClassification
    classify_sequence(snaps, lookback)     -> list[RegimeClassification]
    infer_static_regime(point)             -> str
"""

from __future__ import annotations

import math
import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Optional, Any

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

MIN_WINDOW         = 5    # minimum snapshots for temporal regime detection
IDEAL_WINDOW       = 15   # window size at which data_quality_factor = 1.0
SECONDARY_THRESHOLD = 0.45  # score above this → listed as secondary regime

# Trending
_TREND_R2_LOW  = 0.30   # R² below this → no trend component
_TREND_R2_HIGH = 0.80   # R² above this → full trend component
_TREND_T_LOW   = 1.0    # t-stat below → no drift component
_TREND_T_HIGH  = 3.0    # t-stat above → full drift component

# Range-bound: tight range threshold relative to mean spot
_RANGE_PCT_TIGHT = 0.004  # 0.4%: very tight → range_score = 1.0
_RANGE_PCT_WIDE  = 0.020  # 2.0%: wide       → range_score = 0.0

# Volatility: IV % change needed for full score
_VOL_CHANGE_FULL_PCT = 8.0   # ±8% IV change across window → score 1.0
_VOL_CHANGE_MIN_PCT  = 0.5   # ±0.5% → score just above 0

# Expiry pinning
_PIN_MAX_DTE   = 7    # DTE above this → score = 0
_PIN_FULL_DTE  = 0    # DTE = 0 → full DTE component
_PIN_MAX_DIST  = 2.0  # distance_pct above → dist component = 0
_PIN_PCR_BAND  = 0.5  # PCR deviation from 1.0 beyond which → pcr component = 0

# Exhaustion
_EXH_DIST_MIN  = 2.5  # distance_pct below → exhaustion score = 0
_EXH_DIST_FULL = 6.0  # distance_pct above → full dist component

# Momentum continuation
_MOM_DIST_MIN  = 1.5  # distance_pct below → momentum score = 0
_MOM_DIST_FULL = 4.0  # distance_pct above → full dist component

# PCR alignment thresholds
_PCR_BULL    = 1.3
_PCR_BEAR    = 0.8
_PCR_NEUTRAL = 1.0

# Realised vol: 5-minute bars annualisation factor
_BARS_PER_YEAR = 252 * 78   # ≈ 19 656 five-minute bars per year


# ---------------------------------------------------------------------------
# Result type
# ---------------------------------------------------------------------------

@dataclass
class RegimeClassification:
    """
    Regime classification for one snapshot within a rolling context window.

    Attributes
    ----------
    snapshot_id      : UUID of the MaxPainSnapshot (as string).
    symbol           : NSE symbol.
    captured_at      : ISO-format timestamp of the snapshot.
    regime           : Primary regime label (highest scorer).
    confidence       : 0.0–1.0 — reliability of the classification.
    secondary_regimes: All regimes with score ≥ SECONDARY_THRESHOLD.
    scores           : Raw scorer output per regime (for transparency).
    metrics          : Supporting time-series metrics used in scoring.
    warnings         : Issues that may lower confidence or reliability.
    n_window         : Number of snapshots in the rolling context window.
    """
    snapshot_id:       str
    symbol:            str
    captured_at:       str
    regime:            str
    confidence:        float
    secondary_regimes: list[str]         = field(default_factory=list)
    scores:            dict[str, float]  = field(default_factory=dict)
    metrics:           dict              = field(default_factory=dict)
    warnings:          list[str]         = field(default_factory=list)
    n_window:          int               = 1

    def to_dict(self) -> dict:
        return {
            "snapshot_id":       self.snapshot_id,
            "symbol":            self.symbol,
            "captured_at":       self.captured_at,
            "regime":            self.regime,
            "confidence":        self.confidence,
            "secondary_regimes": self.secondary_regimes,
            "scores":            self.scores,
            "metrics":           self.metrics,
            "warnings":          self.warnings,
            "n_window":          self.n_window,
        }


# ---------------------------------------------------------------------------
# Pure-math helpers (no external dependencies)
# ---------------------------------------------------------------------------

def _linear_clamp(x: float, x_lo: float, x_hi: float) -> float:
    """Map x linearly from [x_lo, x_hi] → [0, 1], clamped to [0, 1]."""
    if x_hi <= x_lo:
        return 0.0
    return max(0.0, min(1.0, (x - x_lo) / (x_hi - x_lo)))


def _safe_mean(xs: list[float]) -> Optional[float]:
    return sum(xs) / len(xs) if xs else None


def _safe_pstdev(xs: list[float]) -> Optional[float]:
    """Population standard deviation. Returns None for < 2 elements."""
    if len(xs) < 2:
        return None
    m = sum(xs) / len(xs)
    v = sum((x - m) ** 2 for x in xs) / len(xs)
    return math.sqrt(v)


def _log_returns(prices: list[float]) -> list[float]:
    """Natural log returns for a price series. Silently skips non-positive prices."""
    return [
        math.log(prices[i + 1] / prices[i])
        for i in range(len(prices) - 1)
        if prices[i] > 0 and prices[i + 1] > 0
    ]


def _linear_regression(
    xs: list[float], ys: list[float]
) -> tuple[float, float, float]:
    """
    Ordinary least-squares regression: y = slope * x + intercept.

    Returns (slope, intercept, r_squared).
    r_squared is clamped to [0, 1].
    """
    n = len(xs)
    if n < 2:
        return 0.0, (ys[0] if ys else 0.0), 1.0

    sx  = sum(xs);           sy  = sum(ys)
    sxx = sum(x * x for x in xs)
    sxy = sum(x * y for x, y in zip(xs, ys))

    denom = n * sxx - sx * sx
    if abs(denom) < 1e-12:
        return 0.0, sy / n, 1.0   # all x values identical (flat)

    slope     = (n * sxy - sx * sy) / denom
    intercept = (sy - slope * sx) / n

    y_mean = sy / n
    ss_tot = sum((y - y_mean) ** 2 for y in ys)
    if ss_tot < 1e-12:
        return slope, intercept, 1.0   # all y identical → perfect fit

    ss_res = sum((y - (slope * x + intercept)) ** 2 for x, y in zip(xs, ys))
    r_sq   = max(0.0, 1.0 - ss_res / ss_tot)
    return slope, intercept, r_sq


def _acf1(series: list[float]) -> float:
    """
    Lag-1 sample autocorrelation.
    Returns 0.0 when series is too short or has zero variance.
    Negative values indicate mean-reversion; positive indicate momentum.
    """
    n = len(series)
    if n < 3:
        return 0.0
    m  = sum(series) / n
    c0 = sum((x - m) ** 2 for x in series) / n
    if c0 < 1e-12:
        return 0.0
    c1 = sum((series[i] - m) * (series[i + 1] - m) for i in range(n - 1)) / n
    return max(-1.0, min(1.0, c1 / c0))


def _days_to_expiry(expiry: Optional[str]) -> int:
    """Parse NSE expiry string 'DD-Mon-YYYY' → remaining days (0 if past or unknown)."""
    if not expiry:
        return 0
    try:
        exp_dt = datetime.strptime(expiry, "%d-%b-%Y").replace(tzinfo=timezone.utc)
        return max(0, (exp_dt - datetime.now(timezone.utc)).days)
    except ValueError:
        return 0


# ---------------------------------------------------------------------------
# Individual regime scorers
# ---------------------------------------------------------------------------

def _score_trending(spots: list[float]) -> tuple[float, dict]:
    """
    Score for 'trending' regime.

    Uses OLS R² (directional linearity) and drift t-statistic (non-zero mean
    log return). Both must be elevated for a high trending score.
    """
    n = len(spots)
    if n < MIN_WINDOW:
        return 0.0, {"reason": "insufficient_window"}

    xs = list(range(n))
    _, _, r_sq = _linear_regression(xs, spots)

    log_ret = _log_returns(spots)
    if len(log_ret) < 2:
        return 0.0, {"reason": "insufficient_returns"}

    mu    = _safe_mean(log_ret) or 0.0
    sigma = _safe_pstdev(log_ret) or 0.0

    t_stat = abs(mu) / (sigma / math.sqrt(len(log_ret))) if sigma > 0 else 0.0

    spot_mean  = _safe_mean(spots) or 1.0
    slope_pct  = (spots[-1] - spots[0]) / spot_mean / n * 100  # % change per bar

    r2_component = _linear_clamp(r_sq,   _TREND_R2_LOW, _TREND_R2_HIGH)
    t_component  = _linear_clamp(t_stat, _TREND_T_LOW,  _TREND_T_HIGH)

    score = 0.60 * r2_component + 0.40 * t_component

    rvol = (sigma * math.sqrt(_BARS_PER_YEAR) * 100) if sigma else 0.0

    return round(score, 4), {
        "r_squared":          round(r_sq, 4),
        "drift_pct_per_bar":  round(slope_pct, 5),
        "t_stat":             round(t_stat, 3),
        "realised_vol_ann":   round(rvol, 2),
        "n_bars":             n,
    }


def _score_range_bound(spots: list[float]) -> tuple[float, dict]:
    """
    Score for 'range_bound' regime.

    Low OLS R² (no trend), negative lag-1 autocorrelation (mean-reversion),
    and tight price range relative to the mean.
    """
    n = len(spots)
    if n < MIN_WINDOW:
        return 0.0, {"reason": "insufficient_window"}

    xs = list(range(n))
    _, _, r_sq = _linear_regression(xs, spots)

    log_ret = _log_returns(spots)
    acf     = _acf1(log_ret)

    spot_mean  = _safe_mean(spots) or 1.0
    rng_ratio  = (max(spots) - min(spots)) / spot_mean  # e.g. 0.01 = 1% range

    # R² component: high when trend is absent
    r2_score = _linear_clamp(1.0 - r_sq, 0.20, 0.80)

    # ACF component: scaled so acf=-0.5 → 1.0, acf=0 → 0.5, acf=+0.5 → 0.0
    # acf_score = clamp((0 - acf + 0.5) / 1.0, 0, 1)
    acf_score = max(0.0, min(1.0, (0.5 - acf) / 1.0))

    # Range component: tighter is higher
    range_score = max(0.0, min(1.0, 1.0 - rng_ratio / _RANGE_PCT_WIDE))

    score = 0.40 * r2_score + 0.35 * acf_score + 0.25 * range_score

    return round(score, 4), {
        "r_squared":  round(r_sq, 4),
        "acf_lag1":   round(acf, 4),
        "range_pct":  round(rng_ratio * 100, 3),
    }


def _score_vol_expansion(ivs: list[Optional[float]]) -> tuple[float, dict]:
    """
    Score for 'volatility_expansion' regime.

    Measures the OLS slope of the avg_iv series and the first-half vs
    second-half IV comparison. Both need to show rising IV for high score.
    None values are excluded; returns 0.0 if fewer than 5 remain.
    """
    valid = [v for v in ivs if v is not None and v > 0]
    if len(valid) < 5:
        return 0.0, {"reason": "insufficient_iv_data", "n_valid": len(valid)}

    xs = list(range(len(valid)))
    slope, _, r_sq = _linear_regression(xs, valid)
    iv_mean = _safe_mean(valid) or 1.0

    # Normalised slope: fractional change in IV per bar
    norm_slope = slope / iv_mean

    # First-half vs second-half comparison
    mid      = len(valid) // 2
    iv_early = _safe_mean(valid[:mid]) or 1.0
    iv_late  = _safe_mean(valid[mid:]) or iv_early
    iv_change_pct = (iv_late - iv_early) / iv_early * 100

    slope_score  = _linear_clamp(norm_slope,    0.0, 0.006)
    change_score = _linear_clamp(iv_change_pct, _VOL_CHANGE_MIN_PCT, _VOL_CHANGE_FULL_PCT)

    score = 0.50 * slope_score + 0.50 * change_score

    return round(score, 4), {
        "iv_slope_per_bar":   round(norm_slope * 100, 4),
        "iv_change_pct":      round(iv_change_pct, 3),
        "iv_mean":            round(iv_mean, 2),
        "iv_slope_r_squared": round(r_sq, 4),
    }


def _score_vol_compression(ivs: list[Optional[float]]) -> tuple[float, dict]:
    """
    Score for 'volatility_compression' regime.
    Mirror of _score_vol_expansion with sign-reversed logic.
    """
    valid = [v for v in ivs if v is not None and v > 0]
    if len(valid) < 5:
        return 0.0, {"reason": "insufficient_iv_data", "n_valid": len(valid)}

    xs = list(range(len(valid)))
    slope, _, r_sq = _linear_regression(xs, valid)
    iv_mean = _safe_mean(valid) or 1.0

    norm_slope = slope / iv_mean   # negative = compressing

    mid      = len(valid) // 2
    iv_early = _safe_mean(valid[:mid]) or 1.0
    iv_late  = _safe_mean(valid[mid:]) or iv_early
    iv_change_pct = (iv_early - iv_late) / iv_early * 100  # positive when falling

    slope_score  = _linear_clamp(-norm_slope,   0.0, 0.006)
    change_score = _linear_clamp(iv_change_pct, _VOL_CHANGE_MIN_PCT, _VOL_CHANGE_FULL_PCT)

    score = 0.50 * slope_score + 0.50 * change_score

    return round(score, 4), {
        "iv_slope_per_bar":   round(norm_slope * 100, 4),
        "iv_drop_pct":        round(iv_change_pct, 3),
        "iv_mean":            round(iv_mean, 2),
        "iv_slope_r_squared": round(r_sq, 4),
    }


def _score_expiry_pinning(
    dte: int, dist_pct: float, pcr: float
) -> tuple[float, dict]:
    """
    Score for 'expiry_pinning' regime.

    Uses current-state features only (no history needed).
    Pinning occurs when market makers keep spot near max pain close to expiry.

    Requires: DTE ≤ 7, dist_pct < 2%, PCR near 1.0.
    """
    if dte > _PIN_MAX_DTE:
        return 0.0, {"days_to_expiry": dte, "reason": "too_far_from_expiry"}

    # DTE component: 1.0 at DTE = 0, 0.0 at DTE = _PIN_MAX_DTE
    dte_score  = 1.0 - dte / _PIN_MAX_DTE
    # Distance component: 1.0 at dist = 0, 0.0 at dist = _PIN_MAX_DIST
    dist_score = max(0.0, 1.0 - dist_pct / _PIN_MAX_DIST)
    # PCR component: 1.0 when PCR = 1.0, decays by distance from balance
    pcr_score  = max(0.0, 1.0 - abs(pcr - _PCR_NEUTRAL) / _PIN_PCR_BAND)

    score = 0.40 * dte_score + 0.40 * dist_score + 0.20 * pcr_score

    return round(score, 4), {
        "days_to_expiry": dte,
        "distance_pct":   round(dist_pct, 3),
        "pcr":            round(pcr, 3),
        "dte_component":  round(dte_score, 3),
        "dist_component": round(dist_score, 3),
        "pcr_component":  round(pcr_score, 3),
    }


def _score_exhaustion(
    dists:         list[float],
    current_dist:  float,
    current_pcr:   float,
    direction:     str,
) -> tuple[float, dict]:
    """
    Score for 'exhaustion' regime.

    Requires a large current distance_pct, but the distance is no longer
    growing (slope ≤ 0 or decelerating). PCR divergence from signal direction
    provides a confirming signal.

    'Exhaustion' means: the move has extended far but is losing energy.
    """
    # Current distance must be large enough to be meaningful
    dist_score = _linear_clamp(current_dist, _EXH_DIST_MIN, _EXH_DIST_FULL)

    norm_slope = 0.0
    decel_score = 0.3  # neutral when no history
    if len(dists) >= MIN_WINDOW:
        xs = list(range(len(dists)))
        slope, _, _ = _linear_regression(xs, dists)
        mean_dist   = _safe_mean(dists) or 1.0
        norm_slope  = slope / mean_dist
        # High when slope ≤ 0, zero when slope ≥ 0.05
        decel_score = _linear_clamp(-norm_slope, -0.05, 0.05)

    # PCR divergence: bearish direction but PCR > 1 (put heavy) = exhaustion signal
    # Bullish direction but PCR < 1 (call heavy) = exhaustion signal
    if direction == "bearish":
        pcr_div = _linear_clamp(current_pcr - _PCR_NEUTRAL, -0.20, 0.50)
    else:
        pcr_div = _linear_clamp(_PCR_NEUTRAL - current_pcr, -0.20, 0.50)

    score = 0.40 * dist_score + 0.40 * decel_score + 0.20 * pcr_div

    return round(score, 4), {
        "current_distance_pct": round(current_dist, 3),
        "dist_slope_norm":      round(norm_slope, 5),
        "dist_decel_score":     round(decel_score, 3),
        "pcr_divergence_score": round(pcr_div, 3),
        "direction":            direction,
    }


def _score_momentum_continuation(
    dists:        list[float],
    current_dist: float,
    current_pcr:  float,
    direction:    str,
) -> tuple[float, dict]:
    """
    Score for 'momentum_continuation' regime.

    Requires a meaningful distance_pct AND that distance is actively growing,
    AND that PCR confirms the directional bias.

    Opposite of exhaustion: the move still has momentum behind it.
    """
    dist_score = _linear_clamp(current_dist, _MOM_DIST_MIN, _MOM_DIST_FULL)

    norm_slope    = 0.0
    momentum_score = 0.0
    if len(dists) >= MIN_WINDOW:
        xs = list(range(len(dists)))
        slope, _, r_sq = _linear_regression(xs, dists)
        mean_dist   = _safe_mean(dists) or 1.0
        norm_slope  = slope / mean_dist
        # Positive slope = distance growing (aligned with direction)
        growth      = _linear_clamp(norm_slope, 0.0, 0.08)
        momentum_score = growth * min(1.0, r_sq / 0.4)   # penalise noisy growth

    # PCR alignment: bullish direction → PCR > 1 (more puts, bearish hedge) signals continuation
    # bearish direction → PCR < 1 (more calls, bullish positioning) signals continuation
    if direction == "bullish":
        pcr_align = _linear_clamp(current_pcr - _PCR_NEUTRAL, -0.20, 0.40)
    else:
        pcr_align = _linear_clamp(_PCR_NEUTRAL - current_pcr, -0.20, 0.40)

    score = 0.35 * dist_score + 0.40 * momentum_score + 0.25 * pcr_align

    return round(score, 4), {
        "current_distance_pct": round(current_dist, 3),
        "dist_slope_norm":      round(norm_slope, 5),
        "momentum_score":       round(momentum_score, 3),
        "pcr_alignment_score":  round(pcr_align, 3),
        "direction":            direction,
    }


# ---------------------------------------------------------------------------
# Snapshot feature extraction
# ---------------------------------------------------------------------------

def _extract_series(window: list[Any]) -> dict:
    """
    Extract parallel time series from a list of MaxPainSnapshot (or duck-typed)
    objects. All values are sanitised: None / non-positive spot prices are
    excluded where required.
    """
    spots = [
        (s.spot_price or 0.0)
        for s in window
        if (s.spot_price or 0.0) > 0
    ]
    ivs   = [s.avg_iv for s in window]          # may contain None
    dists = [(s.distance_pct or 0.0) for s in window]
    pcrs  = [(s.pcr or 1.0) for s in window]

    return {
        "spots": spots,
        "ivs":   ivs,
        "dists": dists,
        "pcrs":  pcrs,
    }


# ---------------------------------------------------------------------------
# Primary classifier
# ---------------------------------------------------------------------------

_ALL_REGIMES = [
    "trending",
    "range_bound",
    "volatility_expansion",
    "volatility_compression",
    "expiry_pinning",
    "exhaustion",
    "momentum_continuation",
]


def classify_snapshot(
    snap: Any,
    window: list[Any],
) -> RegimeClassification:
    """
    Classify one snapshot given its rolling context window.

    Parameters
    ----------
    snap   : The snapshot being classified (must be last element of window).
    window : List of MaxPainSnapshot objects, oldest-first, including snap.
             Minimum 1 element (just snap itself for state-only regimes).

    Returns
    -------
    RegimeClassification with primary regime, confidence, scores, and metrics.
    """
    warnings: list[str] = []
    n = len(window)

    # Current-state features from the snapshot being classified
    current_dist  = snap.distance_pct or 0.0
    current_pcr   = snap.pcr or 1.0
    direction     = snap.direction or (
        "bearish" if (snap.spot_price or 0) > (snap.max_pain or 0) else "bullish"
    )
    dte = _days_to_expiry(snap.expiry)

    # Time-series features from the rolling window
    series = _extract_series(window)
    spots  = series["spots"]
    ivs    = series["ivs"]
    dists  = series["dists"]

    # ── Temporal regimes ────────────────────────────────────────────────────
    if n < MIN_WINDOW:
        warnings.append(
            f"small_window: only {n} snapshots — temporal regimes have low confidence"
        )
        s_trend   = (0.0, {"reason": "insufficient_window"})
        s_range   = (0.0, {"reason": "insufficient_window"})
        s_vol_exp = (0.0, {"reason": "insufficient_window"})
        s_vol_cmp = (0.0, {"reason": "insufficient_window"})
        s_exh     = (0.0, {"reason": "insufficient_window"})
        s_mom     = (0.0, {"reason": "insufficient_window"})
    else:
        s_trend   = _score_trending(spots)
        s_range   = _score_range_bound(spots)
        s_vol_exp = _score_vol_expansion(ivs)
        s_vol_cmp = _score_vol_compression(ivs)
        s_exh     = _score_exhaustion(dists, current_dist, current_pcr, direction)
        s_mom     = _score_momentum_continuation(dists, current_dist, current_pcr, direction)

    # ── State-only regimes ──────────────────────────────────────────────────
    s_pin = _score_expiry_pinning(dte, current_dist, current_pcr)

    # ── Assemble scores ─────────────────────────────────────────────────────
    raw_scores: dict[str, float] = {
        "trending":              s_trend[0],
        "range_bound":           s_range[0],
        "volatility_expansion":  s_vol_exp[0],
        "volatility_compression": s_vol_cmp[0],
        "expiry_pinning":        s_pin[0],
        "exhaustion":            s_exh[0],
        "momentum_continuation": s_mom[0],
    }

    # Combine sub-metrics (exclude "reason" keys from warnings dict)
    metrics: dict = {}
    for label, (_, m) in zip(_ALL_REGIMES, [
        s_trend, s_range, s_vol_exp, s_vol_cmp, s_pin, s_exh, s_mom
    ]):
        if m and "reason" not in m:
            metrics[label] = m

    # ── Primary regime ───────────────────────────────────────────────────────
    primary = max(raw_scores, key=raw_scores.get)

    # ── Secondary regimes ────────────────────────────────────────────────────
    secondary = [
        r for r, sc in raw_scores.items()
        if sc >= SECONDARY_THRESHOLD and r != primary
    ]

    # ── Confidence ──────────────────────────────────────────────────────────
    primary_score         = raw_scores[primary]
    data_quality          = min(1.0, n / IDEAL_WINDOW)
    confidence            = round(primary_score * data_quality, 4)

    # Low-confidence warning
    if confidence < 0.30:
        warnings.append(
            f"low_confidence: {confidence:.2f} — "
            f"regime assignment is uncertain (primary score {primary_score:.2f}, "
            f"window size {n})"
        )

    # Unstable warning: top two scores are close
    sorted_scores = sorted(raw_scores.values(), reverse=True)
    if len(sorted_scores) >= 2 and sorted_scores[0] - sorted_scores[1] < 0.10:
        runner_up = [r for r, s in raw_scores.items() if s == sorted_scores[1]]
        warnings.append(
            f"unstable_classification: margin between '{primary}' "
            f"({sorted_scores[0]:.2f}) and '{runner_up[0] if runner_up else '?'}' "
            f"({sorted_scores[1]:.2f}) is only {sorted_scores[0]-sorted_scores[1]:.2f}"
        )

    return RegimeClassification(
        snapshot_id       = str(snap.id),
        symbol            = str(snap.symbol or "").upper(),
        captured_at       = (
            snap.captured_at.isoformat()
            if hasattr(snap.captured_at, "isoformat")
            else str(snap.captured_at)
        ),
        regime            = primary,
        confidence        = confidence,
        secondary_regimes = secondary,
        scores            = {k: round(v, 4) for k, v in raw_scores.items()},
        metrics           = metrics,
        warnings          = warnings,
        n_window          = n,
    )


def classify_sequence(
    snaps: list[Any],
    lookback: int = IDEAL_WINDOW,
) -> list[RegimeClassification]:
    """
    Classify every snapshot in a temporally sorted list.

    Each snapshot is classified using a rolling window of up to `lookback`
    prior snapshots (inclusive). The window grows from the start of the list
    until it reaches `lookback`, then slides forward.

    Parameters
    ----------
    snaps    : MaxPainSnapshot objects sorted ascending by captured_at.
    lookback : Maximum rolling window size. Default: IDEAL_WINDOW (15).

    Returns
    -------
    List of RegimeClassification objects, one per input snapshot,
    in the same order.
    """
    results: list[RegimeClassification] = []
    for i, snap in enumerate(snaps):
        start  = max(0, i - lookback + 1)
        window = snaps[start: i + 1]
        try:
            results.append(classify_snapshot(snap, window))
        except Exception as exc:
            logger.warning(
                "Regime classification failed for snapshot %s: %s",
                getattr(snap, "id", "?"), exc,
            )
            # Emit a fallback classification so the sequence is complete
            results.append(RegimeClassification(
                snapshot_id = str(getattr(snap, "id", "")),
                symbol      = str(getattr(snap, "symbol", "")).upper(),
                captured_at = str(getattr(snap, "captured_at", "")),
                regime      = "unknown",
                confidence  = 0.0,
                warnings    = [f"classification_error: {exc}"],
                n_window    = len(window),
            ))
    return results


# ---------------------------------------------------------------------------
# Static single-point regime inference (for validation filtering)
# ---------------------------------------------------------------------------

def infer_static_regime(
    distance_pct: float,
    days_to_expiry: int,
    pcr: float,
    avg_iv: Optional[float],
    direction: str,
    iv_high_threshold: float = 20.0,
    iv_low_threshold: float  = 12.0,
) -> str:
    """
    Infer regime label from static features of a single signal point.
    No rolling window — uses only current-state metrics.

    Used by the validation service to filter replay points by regime-like
    characteristics when no stored RegimeSnapshot is available.

    Returns one of:
      "expiry_pinning"        DTE ≤ 3 and distance < 1.5%
      "high_extension"        distance >= 4.0%
      "moderate_extension"    2.0% <= distance < 4.0%
      "low_extension"         distance < 2.0% (not pinning)
      "pcr_divergent"         PCR contradicts signal direction
      "pcr_aligned"           PCR confirms signal direction
      "normal"                catch-all
    """
    iv = avg_iv or 0.0

    if days_to_expiry <= 3 and distance_pct < 1.5:
        return "expiry_pinning"
    if distance_pct >= 4.0:
        return "high_extension"
    if distance_pct >= 2.0:
        return "moderate_extension"

    # PCR divergence check
    if direction == "bearish" and pcr > _PCR_BULL:
        return "pcr_divergent"
    if direction == "bullish" and pcr < _PCR_BEAR:
        return "pcr_divergent"

    # PCR confirmation check
    if direction == "bullish" and pcr >= _PCR_BULL:
        return "pcr_aligned"
    if direction == "bearish" and pcr <= _PCR_BEAR:
        return "pcr_aligned"

    return "normal"
