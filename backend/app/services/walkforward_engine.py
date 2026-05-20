"""
Walk-Forward and Out-of-Sample Validation Engine
=================================================
Evaluates whether signal relationships discovered in-sample survive when
applied to genuinely unseen future data.

The core question this engine answers:
    "Was the edge we found in our training period real, or did we just fit
    noise?  Does it hold when we apply it to the next time window?"

Design Principles
-----------------
Strict Temporal Ordering
    Training data is always strictly earlier in time than test data.
    No shuffling.  No look-ahead.  The split boundary is a hard wall.

No Information Leakage
    Statistics (win rates, feature correlations, threshold calibrations)
    are computed only on training records.  The test set is evaluated
    blindly using the relationships discovered in training.

Honest Uncertainty
    With small folds, confidence intervals are wide.  We report this
    honestly using the t-distribution rather than the normal approximation.

Degradation over Optimism
    In-sample metrics almost always overstate true performance.
    The degradation ratio (OOS / IS) is the primary diagnostic.
    Robustness score (fraction of folds with positive OOS) is the
    most interpretable single number.

Validation Methods
------------------
expanding (default)
    Training window grows with each fold (anchored at t=0).
    Test window walks forward.  Each fold's training includes all
    previous training data.  Standard for time-series cross-validation.

rolling
    Fixed-size training window slides forward.  Earlier data drops out
    of training as time advances.  Tests whether recent patterns are
    more predictive than historical patterns.

anchored
    Alias for expanding — identical computation, semantically clearer
    name for researchers coming from the finance literature.

Fold Structure
--------------
For N records sorted chronologically and n_splits folds:

  Expanding / Anchored:
    initial_train = max(min_train_obs, ⌊N × 0.5⌋)
    test_step     = max(min_test_obs, (N − initial_train) ÷ n_splits)

    Fold 0: train=[0, t0),        test=[t0, t0+step)
    Fold 1: train=[0, t0+step),   test=[t0+step, t0+2×step)
    ...

  Rolling:
    train_size = max(min_train_obs, ⌊N × 0.5⌋)
    test_step  = same as above

    Fold 0: train=[0, train_size),          test=[train_size, train_size+step)
    Fold 1: train=[step, train_size+step),  test=[train_size+step, ...]
    ...

Key Metrics Computed per Fold
------------------------------
IS metrics
    Win rate, expectancy, std, feature-PnL Pearson correlations,
    regime distribution.

OOS metrics
    Same metrics applied to the held-out future period.

Degradation
    expectancy_degradation_pct  = (IS_exp − OOS_exp) / |IS_exp| × 100
    win_rate_delta              = OOS_wr − IS_wr
    feature_correlation_decay   = IS_r − OOS_r  per feature
    regime_drift_tvd            = Total Variation Distance between
                                  IS and OOS regime distributions

Aggregate (across folds)
    mean / std of IS and OOS expectancy
    degradation_ratio           = mean_OOS / mean_IS
    robustness_score            = fraction of folds with OOS_exp > 0
    stability_score             = 1 − std_OOS / (|mean_OOS| + 0.5)
    overfit_score               = max(0, (mean_IS − mean_OOS) / |mean_IS|)
    confidence_interval         = t-distribution CI on OOS fold values

Warnings
--------
severe_overfitting          overfit_score > 0.50
unstable_oos_behavior       CV of OOS expectancy > 2.0
high_parameter_sensitivity  std(degradation_pct) > 50
regime_inconsistency        mean_tvd > 0.30 across folds
insufficient_unseen_data    any fold has < min_test_obs
negative_mean_oos           mean OOS expectancy < 0
signal_decay_detected       majority of folds show IS→OOS correlation sign flip

Public API
----------
    run_walkforward(records, params, symbols, window)
        -> WalkForwardResult

    WalkForwardResult.to_run_dict()      → full fold-by-fold detail
    WalkForwardResult.to_summary_dict()  → aggregate statistics only
    WalkForwardResult.to_stability_dict()→ time-series per fold (for plotting)
"""

from __future__ import annotations

import logging
import math
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Optional

from app.services.research_engine import FeatureRecord, CONTINUOUS_FEATURES

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

VALID_WF_METHODS: set[str] = {"expanding", "rolling", "anchored"}

_MIN_OBS_FOR_CORRELATION = 3    # minimum records to compute a feature correlation
_OVERFIT_SEVERE          = 0.50  # overfit_score above this → severe_overfitting warning
_CV_UNSTABLE             = 2.00  # coefficient of variation above this → unstable OOS
_DEGRAD_STD_HIGH         = 50.0  # std of degradation_pct above this → high sensitivity
_TVD_HIGH                = 0.30  # mean TVD above this → regime_inconsistency
_MIN_TOTAL_OOS           = 10    # total OOS records below this → insufficient warning

# t-distribution critical values (two-tailed, 95% confidence)
# Keyed by degrees of freedom (n-1 for n fold-level OOS values)
_T_CRIT_95: dict[int, float] = {
    1: 12.706, 2: 4.303, 3: 3.182, 4: 2.776, 5: 2.571,
    6: 2.447,  7: 2.365, 8: 2.306, 9: 2.262, 10: 2.228,
    12: 2.179, 15: 2.131, 20: 2.086, 30: 2.042, 60: 2.000,
}
_T_CRIT_90: dict[int, float] = {
    1: 6.314, 2: 2.920, 3: 2.353, 4: 2.132, 5: 2.015,
    6: 1.943, 7: 1.895, 8: 1.860, 9: 1.833, 10: 1.812,
    12: 1.782, 15: 1.753, 20: 1.725, 30: 1.697, 60: 1.671,
}
_T_CRIT_99: dict[int, float] = {
    1: 63.657, 2: 9.925, 3: 5.841, 4: 4.604, 5: 4.032,
    6: 3.707,  7: 3.499, 8: 3.355, 9: 3.250, 10: 3.169,
    12: 3.055, 15: 2.947, 20: 2.845, 30: 2.750, 60: 2.660,
}


# ---------------------------------------------------------------------------
# Math helpers (local copies to avoid circular imports)
# ---------------------------------------------------------------------------

def _safe_std(xs: list[float]) -> float:
    """Population standard deviation."""
    if len(xs) < 2:
        return 0.0
    mu = sum(xs) / len(xs)
    return math.sqrt(sum((x - mu) ** 2 for x in xs) / len(xs))


def _sample_std(xs: list[float]) -> float:
    """Sample standard deviation (df corrected)."""
    n = len(xs)
    if n < 2:
        return 0.0
    mu = sum(xs) / n
    return math.sqrt(sum((x - mu) ** 2 for x in xs) / (n - 1))


def _pearson(xs: list[float], ys: list[float]) -> Optional[float]:
    n = len(xs)
    if n < 2 or len(ys) != n:
        return None
    mx = sum(xs) / n
    my = sum(ys) / n
    num = sum((x - mx) * (y - my) for x, y in zip(xs, ys))
    sx  = math.sqrt(sum((x - mx) ** 2 for x in xs))
    sy  = math.sqrt(sum((y - my) ** 2 for y in ys))
    if sx < 1e-10 or sy < 1e-10:
        return None
    return max(-1.0, min(1.0, num / (sx * sy)))


def _tvd(p: dict[str, float], q: dict[str, float]) -> float:
    """Total Variation Distance between two discrete distributions (∈ [0, 1])."""
    all_keys = set(p) | set(q)
    return 0.5 * sum(abs(p.get(k, 0.0) - q.get(k, 0.0)) for k in all_keys)


def _t_critical(df: int, confidence: float) -> float:
    """Look up t-critical value (two-tailed) for common confidence levels."""
    table = (
        _T_CRIT_95 if abs(confidence - 0.95) < 0.01 else
        _T_CRIT_90 if abs(confidence - 0.90) < 0.01 else
        _T_CRIT_99 if abs(confidence - 0.99) < 0.01 else
        _T_CRIT_95
    )
    if df in table:
        return table[df]
    # Interpolate between nearest keys
    keys = sorted(table.keys())
    lo = max((k for k in keys if k <= df), default=keys[0])
    hi = min((k for k in keys if k >= df), default=keys[-1])
    if lo == hi:
        return table[lo]
    frac = (df - lo) / (hi - lo)
    return table[lo] + frac * (table[hi] - table[lo])


def _t_ci(values: list[float], confidence: float) -> tuple[float, float]:
    """Return (lower, upper) t-distribution confidence interval for the mean."""
    n = len(values)
    if n == 0:
        return 0.0, 0.0
    mu = sum(values) / n
    if n == 1:
        return mu, mu
    sd = _sample_std(values)
    se = sd / math.sqrt(n)
    tc = _t_critical(n - 1, confidence)
    return mu - tc * se, mu + tc * se


# ---------------------------------------------------------------------------
# Parameter dataclass
# ---------------------------------------------------------------------------

@dataclass
class WalkForwardParams:
    """
    Parameters controlling walk-forward validation.

    Attributes
    ----------
    method
        "expanding" | "rolling" | "anchored".
    n_splits
        Number of train/test folds (2–20).  Default 5.
    min_train_obs
        Minimum records required in any training window.  Default 10.
    min_test_obs
        Minimum records required in any test window.  Default 5.
    features_to_track
        Continuous feature names to analyse for correlation decay.
        Defaults to all four continuous features.
    confidence_level
        Confidence level for bootstrap/t-distribution CI (default 0.95).
    """
    method:             str        = "expanding"
    n_splits:           int        = 5
    min_train_obs:      int        = 10
    min_test_obs:       int        = 5
    features_to_track:  list[str]  = field(default_factory=lambda: list(CONTINUOUS_FEATURES))
    confidence_level:   float      = 0.95

    def validate(self) -> list[str]:
        issues: list[str] = []
        if self.method not in VALID_WF_METHODS:
            issues.append(
                f"invalid method '{self.method}'; "
                f"choose from {sorted(VALID_WF_METHODS)}"
            )
        if not (2 <= self.n_splits <= 20):
            issues.append("n_splits must be in [2, 20]")
        if self.min_train_obs < 5:
            issues.append("min_train_obs must be >= 5")
        if self.min_test_obs < 3:
            issues.append("min_test_obs must be >= 3")
        for f in self.features_to_track:
            if f not in CONTINUOUS_FEATURES:
                issues.append(
                    f"invalid feature '{f}'; "
                    f"choose from {CONTINUOUS_FEATURES}"
                )
        if not (0.50 <= self.confidence_level <= 0.999):
            issues.append("confidence_level must be in [0.50, 0.999]")
        return issues

    def to_dict(self) -> dict:
        return {
            "method":            self.method,
            "n_splits":          self.n_splits,
            "min_train_obs":     self.min_train_obs,
            "min_test_obs":      self.min_test_obs,
            "features_to_track": self.features_to_track,
            "confidence_level":  self.confidence_level,
        }


# ---------------------------------------------------------------------------
# Result dataclasses
# ---------------------------------------------------------------------------

@dataclass
class FoldPeriod:
    """Time boundaries and sizes of one fold's train and test windows."""
    fold_idx:    int
    train_start: str
    train_end:   str
    test_start:  str
    test_end:    str
    n_train:     int
    n_test:      int

    def to_dict(self) -> dict:
        return {
            "fold_idx":    self.fold_idx,
            "train_start": self.train_start,
            "train_end":   self.train_end,
            "test_start":  self.test_start,
            "test_end":    self.test_end,
            "n_train":     self.n_train,
            "n_test":      self.n_test,
        }


@dataclass
class FoldStats:
    """Performance statistics for one fold's IS or OOS window."""
    n_obs:                  int
    win_rate:               Optional[float]
    expectancy_pct:         Optional[float]
    std_pct:                float
    sharpe_approx:          Optional[float]   # expectancy / std
    feature_correlations:   dict[str, Optional[float]]
    regime_distribution:    dict[str, float]

    def to_dict(self) -> dict:
        def _r(v): return round(v, 4) if v is not None else None
        return {
            "n_obs":               self.n_obs,
            "win_rate":            _r(self.win_rate),
            "expectancy_pct":      _r(self.expectancy_pct),
            "std_pct":             _r(self.std_pct),
            "sharpe_approx":       _r(self.sharpe_approx),
            "feature_correlations": {k: _r(v) for k, v in self.feature_correlations.items()},
            "regime_distribution":  {k: _r(v) for k, v in self.regime_distribution.items()},
        }


@dataclass
class FoldDegradation:
    """
    Difference metrics between IS and OOS performance for one fold.

    Positive expectancy_degradation_pct means IS was better than OOS.
    Negative means OOS actually improved (possible data limitation / luck).
    """
    expectancy_degradation_pct: Optional[float]  # (IS − OOS) / |IS| × 100
    win_rate_delta:             Optional[float]  # OOS_wr − IS_wr
    feature_correlation_decay:  dict[str, Optional[float]]  # IS_r − OOS_r per feature
    regime_drift_tvd:           float            # [0, 1]; higher = more drift
    oos_positive:               bool             # OOS expectancy > 0

    def to_dict(self) -> dict:
        def _r(v): return round(v, 4) if v is not None else None
        return {
            "expectancy_degradation_pct": _r(self.expectancy_degradation_pct),
            "win_rate_delta":             _r(self.win_rate_delta),
            "feature_correlation_decay":  {k: _r(v) for k, v in self.feature_correlation_decay.items()},
            "regime_drift_tvd":           _r(self.regime_drift_tvd),
            "oos_positive":               self.oos_positive,
        }


@dataclass
class FoldResult:
    """Complete result for one train/test fold."""
    fold_idx:    int
    period:      FoldPeriod
    is_stats:    FoldStats
    oos_stats:   FoldStats
    degradation: FoldDegradation

    def to_dict(self) -> dict:
        return {
            "fold_idx":    self.fold_idx,
            "period":      self.period.to_dict(),
            "in_sample":   self.is_stats.to_dict(),
            "out_of_sample": self.oos_stats.to_dict(),
            "degradation": self.degradation.to_dict(),
        }


@dataclass
class AggregateStats:
    """Aggregate metrics across all folds."""
    # IS aggregate
    mean_is_expectancy:  float
    std_is_expectancy:   float
    mean_is_win_rate:    float

    # OOS aggregate
    mean_oos_expectancy: float
    std_oos_expectancy:  float
    mean_oos_win_rate:   float

    # Confidence interval on OOS expectancy (t-distribution)
    oos_ci_low:          float
    oos_ci_high:         float

    # Core evaluation metrics
    degradation_ratio:   Optional[float]  # mean_OOS / mean_IS; None if IS ≈ 0
    overfit_score:       float            # max(0, (IS − OOS) / |IS|); ∈ [0, ∞)
    robustness_score:    float            # fraction of folds with OOS_exp > 0; ∈ [0, 1]
    stability_score:     float            # 1 − CV(OOS); ∈ [0, 1]

    # Regime drift summary
    mean_regime_drift_tvd: float
    regime_drift_detected: bool

    # Feature decay summary: mean IS_r, mean OOS_r, mean decay per feature
    feature_decay: dict[str, dict[str, Optional[float]]]

    # Diagnostics
    overfit_detected:         bool
    fold_consistency_score:   float  # same as robustness_score

    def to_dict(self) -> dict:
        def _r(v): return round(v, 4) if v is not None else None
        return {
            "mean_is_expectancy_pct":  _r(self.mean_is_expectancy),
            "std_is_expectancy_pct":   _r(self.std_is_expectancy),
            "mean_is_win_rate":        _r(self.mean_is_win_rate),
            "mean_oos_expectancy_pct": _r(self.mean_oos_expectancy),
            "std_oos_expectancy_pct":  _r(self.std_oos_expectancy),
            "mean_oos_win_rate":       _r(self.mean_oos_win_rate),
            "oos_ci_low_pct":          _r(self.oos_ci_low),
            "oos_ci_high_pct":         _r(self.oos_ci_high),
            "degradation_ratio":       _r(self.degradation_ratio),
            "overfit_score":           _r(self.overfit_score),
            "robustness_score":        _r(self.robustness_score),
            "stability_score":         _r(self.stability_score),
            "mean_regime_drift_tvd":   _r(self.mean_regime_drift_tvd),
            "regime_drift_detected":   self.regime_drift_detected,
            "feature_decay":           {
                f: {k: _r(v) for k, v in d.items()}
                for f, d in self.feature_decay.items()
            },
            "overfit_detected":        self.overfit_detected,
            "fold_consistency_score":  _r(self.fold_consistency_score),
        }


@dataclass
class StabilityTimeSeries:
    """
    Time-series view across folds for trend detection and plotting.
    Each list has one entry per fold in chronological order.
    """
    fold_indices:           list[int]
    oos_expectancy_series:  list[Optional[float]]
    oos_win_rate_series:    list[Optional[float]]
    regime_drift_series:    list[float]
    feature_correlation_is: dict[str, list[Optional[float]]]  # IS per fold
    feature_correlation_oos: dict[str, list[Optional[float]]]  # OOS per fold
    decay_series:           dict[str, list[Optional[float]]]   # IS_r − OOS_r per fold

    # Trend in OOS expectancy (positive = improving, negative = decaying)
    expectancy_trend:        Optional[float]  # OLS slope on fold_index vs OOS_exp
    expectancy_trend_direction: str           # "improving" | "decaying" | "stable"

    def to_dict(self) -> dict:
        def _r(v): return round(v, 4) if v is not None else None
        def _rl(lst): return [_r(v) for v in lst]
        return {
            "fold_indices":            self.fold_indices,
            "oos_expectancy_series":   _rl(self.oos_expectancy_series),
            "oos_win_rate_series":     _rl(self.oos_win_rate_series),
            "regime_drift_series":     _rl(self.regime_drift_series),
            "feature_correlation_is":  {f: _rl(v) for f, v in self.feature_correlation_is.items()},
            "feature_correlation_oos": {f: _rl(v) for f, v in self.feature_correlation_oos.items()},
            "decay_series":            {f: _rl(v) for f, v in self.decay_series.items()},
            "expectancy_trend":        _r(self.expectancy_trend),
            "expectancy_trend_direction": self.expectancy_trend_direction,
        }


@dataclass
class WalkForwardResult:
    """Complete walk-forward validation result."""
    symbols:      list[str]
    window:       str
    params:       WalkForwardParams
    n_total_obs:  int
    n_folds:      int
    folds:        list[FoldResult]
    aggregate:    AggregateStats
    stability_ts: StabilityTimeSeries
    warnings:     list[str]
    generated_at: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )

    def to_run_dict(self) -> dict:
        """Full detail: all folds + aggregate + diagnostics."""
        return {
            "symbols":       self.symbols,
            "window":        self.window,
            "params":        self.params.to_dict(),
            "n_total_obs":   self.n_total_obs,
            "n_folds":       self.n_folds,
            "folds":         [f.to_dict() for f in self.folds],
            "aggregate":     self.aggregate.to_dict(),
            "warnings":      self.warnings,
            "generated_at":  self.generated_at,
        }

    def to_summary_dict(self) -> dict:
        """Aggregate statistics only — lightweight response."""
        return {
            "symbols":      self.symbols,
            "window":       self.window,
            "params":       self.params.to_dict(),
            "n_total_obs":  self.n_total_obs,
            "n_folds":      self.n_folds,
            "aggregate":    self.aggregate.to_dict(),
            "warnings":     self.warnings,
            "generated_at": self.generated_at,
        }

    def to_stability_dict(self) -> dict:
        """Time-series view per fold — intended for trend plotting."""
        return {
            "symbols":      self.symbols,
            "window":       self.window,
            "params":       self.params.to_dict(),
            "n_total_obs":  self.n_total_obs,
            "n_folds":      self.n_folds,
            "stability":    self.stability_ts.to_dict(),
            "aggregate": {
                "robustness_score":        round(self.aggregate.robustness_score, 4),
                "stability_score":         round(self.aggregate.stability_score, 4),
                "overfit_detected":        self.aggregate.overfit_detected,
                "regime_drift_detected":   self.aggregate.regime_drift_detected,
                "mean_oos_expectancy_pct": round(self.aggregate.mean_oos_expectancy, 4),
            },
            "warnings":     self.warnings,
            "generated_at": self.generated_at,
        }


# ---------------------------------------------------------------------------
# Fold generation
# ---------------------------------------------------------------------------

def _make_folds(
    records:  list[FeatureRecord],
    params:   WalkForwardParams,
) -> list[tuple[list[FeatureRecord], list[FeatureRecord]]]:
    """
    Split records into (train, test) pairs strictly by time order.

    Records must already be sorted chronologically (extract_feature_records
    guarantees this).

    Returns
    -------
    List of (train_records, test_records) tuples.  May be shorter than
    params.n_splits if the dataset is too small for all folds.

    Raises
    ------
    ValueError
        If the dataset is too small to produce even one valid fold.
    """
    N = len(records)
    min_needed = params.min_train_obs + params.min_test_obs
    if N < min_needed:
        raise ValueError(
            f"only {N} records; need >= {min_needed} "
            f"(min_train={params.min_train_obs} + min_test={params.min_test_obs})"
        )

    # Initial training window: 50% of data, at least min_train_obs
    initial_train = max(params.min_train_obs, N // 2)
    remaining     = N - initial_train

    # test_step: how many records each test window covers
    test_step = max(params.min_test_obs, remaining // params.n_splits)

    folds: list[tuple[list[FeatureRecord], list[FeatureRecord]]] = []

    if params.method in ("expanding", "anchored"):
        for i in range(params.n_splits):
            train_end  = initial_train + i * test_step
            test_start = train_end
            # Last fold absorbs any remainder
            test_end = (
                min(test_start + test_step, N)
                if i < params.n_splits - 1
                else N
            )
            if train_end >= N or test_end <= test_start:
                break
            if (test_end - test_start) < params.min_test_obs:
                break
            if (train_end) < params.min_train_obs:
                continue
            folds.append((records[:train_end], records[test_start:test_end]))

    elif params.method == "rolling":
        train_size = initial_train
        for i in range(params.n_splits):
            train_start = i * test_step
            train_end   = train_start + train_size
            test_start  = train_end
            test_end = (
                min(test_start + test_step, N)
                if i < params.n_splits - 1
                else N
            )
            if train_end > N or test_end <= test_start:
                break
            if (test_end - test_start) < params.min_test_obs:
                break
            if (train_end - train_start) < params.min_train_obs:
                break
            folds.append((records[train_start:train_end], records[test_start:test_end]))

    if not folds:
        raise ValueError(
            f"could not construct any valid folds with {N} records and "
            f"n_splits={params.n_splits}, min_train={params.min_train_obs}, "
            f"min_test={params.min_test_obs}; reduce n_splits or min_obs"
        )

    return folds


# ---------------------------------------------------------------------------
# Fold evaluation
# ---------------------------------------------------------------------------

def _compute_stats(
    records:           list[FeatureRecord],
    features_to_track: list[str],
) -> FoldStats:
    """Compute performance statistics for a single window of records."""
    if not records:
        return FoldStats(
            n_obs               = 0,
            win_rate            = None,
            expectancy_pct      = None,
            std_pct             = 0.0,
            sharpe_approx       = None,
            feature_correlations= {f: None for f in features_to_track},
            regime_distribution = {},
        )

    pnls = [r.net_pnl_pct for r in records]
    n    = len(records)
    mu   = sum(pnls) / n
    std  = _safe_std(pnls)
    wr   = sum(1 for r in records if r.is_win) / n
    shr  = mu / std if std > 1e-6 else None

    # Feature-PnL Pearson correlations
    feat_corrs: dict[str, Optional[float]] = {}
    for feat in features_to_track:
        paired = [
            (getattr(r, feat), r.net_pnl_pct)
            for r in records
            if getattr(r, feat) is not None
        ]
        if len(paired) >= _MIN_OBS_FOR_CORRELATION:
            feat_corrs[feat] = _pearson(
                [p[0] for p in paired],
                [p[1] for p in paired],
            )
        else:
            feat_corrs[feat] = None

    # Regime distribution (proportions)
    regime_counts: dict[str, int] = {}
    for r in records:
        regime_counts[r.regime] = regime_counts.get(r.regime, 0) + 1
    regime_dist = {rg: cnt / n for rg, cnt in regime_counts.items()}

    return FoldStats(
        n_obs               = n,
        win_rate            = round(wr, 4),
        expectancy_pct      = round(mu, 4),
        std_pct             = round(std, 4),
        sharpe_approx       = round(shr, 4) if shr is not None else None,
        feature_correlations= {k: round(v, 4) if v is not None else None for k, v in feat_corrs.items()},
        regime_distribution = {k: round(v, 4) for k, v in regime_dist.items()},
    )


def _compute_degradation(
    fold_idx:          int,
    is_stats:          FoldStats,
    oos_stats:         FoldStats,
    features_to_track: list[str],
) -> FoldDegradation:
    """Compute degradation metrics between IS and OOS performance."""
    is_exp  = is_stats.expectancy_pct
    oos_exp = oos_stats.expectancy_pct

    # Expectancy degradation: (IS − OOS) / |IS|
    exp_degradation: Optional[float] = None
    if is_exp is not None and oos_exp is not None and abs(is_exp) > 1e-9:
        exp_degradation = (is_exp - oos_exp) / abs(is_exp) * 100.0

    # Win rate delta: OOS − IS
    wr_delta: Optional[float] = None
    if is_stats.win_rate is not None and oos_stats.win_rate is not None:
        wr_delta = oos_stats.win_rate - is_stats.win_rate

    # Feature correlation decay: IS_r − OOS_r per feature
    corr_decay: dict[str, Optional[float]] = {}
    for feat in features_to_track:
        is_r  = is_stats.feature_correlations.get(feat)
        oos_r = oos_stats.feature_correlations.get(feat)
        if is_r is not None and oos_r is not None:
            corr_decay[feat] = round(is_r - oos_r, 4)
        else:
            corr_decay[feat] = None

    # Regime drift: Total Variation Distance
    tvd = _tvd(is_stats.regime_distribution, oos_stats.regime_distribution)

    oos_positive = (oos_exp is not None and oos_exp > 0.0)

    return FoldDegradation(
        expectancy_degradation_pct = round(exp_degradation, 4) if exp_degradation is not None else None,
        win_rate_delta             = round(wr_delta, 4) if wr_delta is not None else None,
        feature_correlation_decay  = corr_decay,
        regime_drift_tvd           = round(tvd, 4),
        oos_positive               = oos_positive,
    )


def _evaluate_fold(
    fold_idx:          int,
    train:             list[FeatureRecord],
    test:              list[FeatureRecord],
    features_to_track: list[str],
) -> FoldResult:
    """Evaluate one fold: compute IS/OOS stats and degradation."""
    is_stats  = _compute_stats(train, features_to_track)
    oos_stats = _compute_stats(test,  features_to_track)
    degradation = _compute_degradation(fold_idx, is_stats, oos_stats, features_to_track)

    def _ts(recs: list[FeatureRecord]) -> str:
        return recs[0].captured_at if recs else ""

    def _te(recs: list[FeatureRecord]) -> str:
        return recs[-1].captured_at if recs else ""

    period = FoldPeriod(
        fold_idx    = fold_idx,
        train_start = _ts(train),
        train_end   = _te(train),
        test_start  = _ts(test),
        test_end    = _te(test),
        n_train     = len(train),
        n_test      = len(test),
    )

    return FoldResult(
        fold_idx    = fold_idx,
        period      = period,
        is_stats    = is_stats,
        oos_stats   = oos_stats,
        degradation = degradation,
    )


# ---------------------------------------------------------------------------
# Aggregation
# ---------------------------------------------------------------------------

def _ols_slope(xs: list[float], ys: list[float]) -> Optional[float]:
    """Simple OLS slope for trend detection (no intercept needed)."""
    n = len(xs)
    if n < 2 or len(ys) != n:
        return None
    mx = sum(xs) / n
    my = sum(ys) / n
    num = sum((x - mx) * (y - my) for x, y in zip(xs, ys))
    den = sum((x - mx) ** 2 for x in xs)
    return num / den if abs(den) > 1e-10 else None


def _aggregate_folds(
    folds:             list[FoldResult],
    features_to_track: list[str],
    confidence_level:  float,
) -> tuple[AggregateStats, StabilityTimeSeries]:
    """Compute aggregate statistics and stability time series across all folds."""

    is_exps  = [f.is_stats.expectancy_pct  for f in folds if f.is_stats.expectancy_pct  is not None]
    oos_exps = [f.oos_stats.expectancy_pct for f in folds if f.oos_stats.expectancy_pct is not None]
    is_wrs   = [f.is_stats.win_rate        for f in folds if f.is_stats.win_rate         is not None]
    oos_wrs  = [f.oos_stats.win_rate       for f in folds if f.oos_stats.win_rate        is not None]
    tvds     = [f.degradation.regime_drift_tvd for f in folds]
    degrad_pcts = [
        f.degradation.expectancy_degradation_pct
        for f in folds
        if f.degradation.expectancy_degradation_pct is not None
    ]

    def _mean(xs): return sum(xs) / len(xs) if xs else 0.0

    mean_is  = _mean(is_exps)
    std_is   = _safe_std(is_exps)
    mean_oos = _mean(oos_exps)
    std_oos  = _safe_std(oos_exps)
    mean_wr_is  = _mean(is_wrs)
    mean_wr_oos = _mean(oos_wrs)
    mean_tvd    = _mean(tvds)

    ci_lo, ci_hi = _t_ci(oos_exps, confidence_level) if oos_exps else (0.0, 0.0)

    # Degradation ratio: mean_OOS / mean_IS
    degradation_ratio: Optional[float] = None
    if abs(mean_is) > 1e-9:
        degradation_ratio = round(mean_oos / mean_is, 4)

    # Overfit score: max(0, (IS − OOS) / |IS|)
    overfit_score = 0.0
    if abs(mean_is) > 1e-9:
        overfit_score = max(0.0, (mean_is - mean_oos) / abs(mean_is))

    # Robustness: fraction of folds with OOS > 0
    robustness = sum(1 for f in folds if f.degradation.oos_positive) / len(folds)

    # Stability: 1 − std_OOS / (|mean_OOS| + 0.5) clamped to [0, 1]
    stability = max(0.0, min(1.0, 1.0 - std_oos / (abs(mean_oos) + 0.5)))

    regime_drift_detected = mean_tvd > _TVD_HIGH

    # Feature decay summary per feature
    feat_decay: dict[str, dict[str, Optional[float]]] = {}
    for feat in features_to_track:
        is_rs  = [f.is_stats.feature_correlations.get(feat)
                  for f in folds
                  if f.is_stats.feature_correlations.get(feat) is not None]
        oos_rs = [f.oos_stats.feature_correlations.get(feat)
                  for f in folds
                  if f.oos_stats.feature_correlations.get(feat) is not None]
        decays = [f.degradation.feature_correlation_decay.get(feat)
                  for f in folds
                  if f.degradation.feature_correlation_decay.get(feat) is not None]

        feat_decay[feat] = {
            "mean_is_r":    round(_mean(is_rs), 4) if is_rs else None,
            "mean_oos_r":   round(_mean(oos_rs), 4) if oos_rs else None,
            "mean_decay":   round(_mean(decays), 4) if decays else None,
            "sign_flip_rate": (
                round(
                    sum(1 for ir, or_ in zip(is_rs, oos_rs)
                        if ir is not None and or_ is not None
                        and (ir >= 0) != (or_ >= 0))
                    / max(len(is_rs), 1),
                    4,
                )
                if is_rs and oos_rs else None
            ),
        }

    aggregate = AggregateStats(
        mean_is_expectancy     = round(mean_is,  4),
        std_is_expectancy      = round(std_is,   4),
        mean_is_win_rate       = round(mean_wr_is, 4),
        mean_oos_expectancy    = round(mean_oos, 4),
        std_oos_expectancy     = round(std_oos,  4),
        mean_oos_win_rate      = round(mean_wr_oos, 4),
        oos_ci_low             = round(ci_lo, 4),
        oos_ci_high            = round(ci_hi, 4),
        degradation_ratio      = degradation_ratio,
        overfit_score          = round(overfit_score, 4),
        robustness_score       = round(robustness, 4),
        stability_score        = round(stability, 4),
        mean_regime_drift_tvd  = round(mean_tvd, 4),
        regime_drift_detected  = regime_drift_detected,
        feature_decay          = feat_decay,
        overfit_detected       = overfit_score > _OVERFIT_SEVERE,
        fold_consistency_score = round(robustness, 4),
    )

    # --- Stability time series ---
    fold_indices    = [f.fold_idx for f in folds]
    oos_exp_series  = [f.oos_stats.expectancy_pct for f in folds]
    oos_wr_series   = [f.oos_stats.win_rate        for f in folds]
    drift_series    = [f.degradation.regime_drift_tvd for f in folds]

    feat_is_series:  dict[str, list[Optional[float]]] = {
        feat: [f.is_stats.feature_correlations.get(feat)  for f in folds]
        for feat in features_to_track
    }
    feat_oos_series: dict[str, list[Optional[float]]] = {
        feat: [f.oos_stats.feature_correlations.get(feat) for f in folds]
        for feat in features_to_track
    }
    decay_series: dict[str, list[Optional[float]]] = {
        feat: [f.degradation.feature_correlation_decay.get(feat) for f in folds]
        for feat in features_to_track
    }

    # Trend in OOS expectancy: OLS slope vs fold index
    valid_idx  = [i for i, v in enumerate(oos_exp_series) if v is not None]
    valid_exps = [oos_exp_series[i] for i in valid_idx]
    exp_trend  = _ols_slope(
        [float(fold_indices[i]) for i in valid_idx],
        valid_exps,
    ) if len(valid_idx) >= 2 else None

    if exp_trend is None:
        trend_dir = "stable"
    elif exp_trend > 0.01:
        trend_dir = "improving"
    elif exp_trend < -0.01:
        trend_dir = "decaying"
    else:
        trend_dir = "stable"

    stability_ts = StabilityTimeSeries(
        fold_indices             = fold_indices,
        oos_expectancy_series    = oos_exp_series,
        oos_win_rate_series      = oos_wr_series,
        regime_drift_series      = drift_series,
        feature_correlation_is   = feat_is_series,
        feature_correlation_oos  = feat_oos_series,
        decay_series             = decay_series,
        expectancy_trend         = round(exp_trend, 6) if exp_trend is not None else None,
        expectancy_trend_direction = trend_dir,
    )

    return aggregate, stability_ts


# ---------------------------------------------------------------------------
# Warning generation
# ---------------------------------------------------------------------------

def _generate_warnings(
    folds:      list[FoldResult],
    aggregate:  AggregateStats,
    params:     WalkForwardParams,
) -> list[str]:
    warnings: list[str] = []

    # Insufficient unseen data
    total_oos = sum(f.period.n_test for f in folds)
    if total_oos < _MIN_TOTAL_OOS:
        warnings.append(
            f"insufficient_unseen_data: total OOS records = {total_oos} "
            f"(< {_MIN_TOTAL_OOS}); results have very high variance — "
            f"extend the window or add symbols"
        )

    small_test_folds = [f.fold_idx for f in folds if f.period.n_test < params.min_test_obs]
    if small_test_folds:
        warnings.append(
            f"insufficient_unseen_data: folds {small_test_folds} have fewer "
            f"than {params.min_test_obs} test records — reduce n_splits or "
            f"increase the data window"
        )

    # Severe overfitting
    if aggregate.overfit_detected:
        warnings.append(
            f"severe_overfitting: overfit_score = {aggregate.overfit_score:.2f} "
            f"(mean IS = {aggregate.mean_is_expectancy:.3f}%, "
            f"mean OOS = {aggregate.mean_oos_expectancy:.3f}%) — "
            f"the strategy is fitting training noise, not a real edge"
        )

    # Negative mean OOS
    if aggregate.mean_oos_expectancy < 0:
        warnings.append(
            f"negative_mean_oos: average OOS expectancy is "
            f"{aggregate.mean_oos_expectancy:.3f}% — the strategy loses money "
            f"on unseen data; the in-sample edge does not generalise"
        )

    # Unstable OOS behavior
    oos_exps = [f.oos_stats.expectancy_pct for f in folds if f.oos_stats.expectancy_pct is not None]
    if oos_exps and abs(aggregate.mean_oos_expectancy) > 1e-9:
        cv = aggregate.std_oos_expectancy / abs(aggregate.mean_oos_expectancy)
        if cv > _CV_UNSTABLE:
            warnings.append(
                f"unstable_oos_behavior: coefficient of variation of OOS "
                f"expectancy = {cv:.1f}x — performance is highly variable "
                f"across time periods; do not rely on this edge"
            )

    # High parameter sensitivity (variance in degradation across folds)
    degrad_pcts = [
        f.degradation.expectancy_degradation_pct
        for f in folds
        if f.degradation.expectancy_degradation_pct is not None
    ]
    if len(degrad_pcts) >= 2:
        std_degrad = _safe_std(degrad_pcts)
        if std_degrad > _DEGRAD_STD_HIGH:
            warnings.append(
                f"high_parameter_sensitivity: std of expectancy degradation "
                f"across folds = {std_degrad:.1f}% — performance degrades "
                f"inconsistently; the edge may be threshold-sensitive"
            )

    # Regime inconsistency
    if aggregate.regime_drift_detected:
        warnings.append(
            f"regime_inconsistency: mean regime TVD = {aggregate.mean_regime_drift_tvd:.3f} "
            f"(> {_TVD_HIGH}) — the regime distribution shifts significantly "
            f"between training and test periods; IS relationships may not "
            f"transfer across regime changes"
        )

    # Signal decay (feature correlation sign flip in majority of folds)
    for feat, decay_info in aggregate.feature_decay.items():
        flip_rate = decay_info.get("sign_flip_rate")
        if flip_rate is not None and flip_rate > 0.5:
            warnings.append(
                f"signal_decay_detected: feature '{feat}' shows IS→OOS "
                f"correlation sign flip in {flip_rate:.0%} of folds — "
                f"the feature-PnL relationship is non-stationary and "
                f"should not be used as a signal filter"
            )

    return warnings


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def run_walkforward(
    records: list[FeatureRecord],
    params:  WalkForwardParams,
    symbols: list[str],
    window:  str,
) -> WalkForwardResult:
    """
    Run walk-forward validation on a chronologically sorted list of FeatureRecords.

    Args:
        records : FeatureRecord list from research_engine.extract_feature_records().
                  Must be sorted by captured_at (guaranteed by extract_feature_records).
        params  : WalkForwardParams controlling method, n_splits, min obs, etc.
        symbols : Symbol list (for labelling).
        window  : Lookback window string (for labelling).

    Returns:
        WalkForwardResult with per-fold details, aggregate statistics, and warnings.

    Raises:
        ValueError if records is empty or too small to form any valid fold.
    """
    if not records:
        raise ValueError(
            "no usable trade records; widen the window or reduce filters"
        )

    issues = params.validate()
    if issues:
        raise ValueError(f"invalid WalkForwardParams: {'; '.join(issues)}")

    # Generate folds (may raise ValueError if insufficient data)
    fold_pairs = _make_folds(records, params)

    # Evaluate each fold
    fold_results: list[FoldResult] = []
    for i, (train, test) in enumerate(fold_pairs):
        try:
            result = _evaluate_fold(i, train, test, params.features_to_track)
            fold_results.append(result)
        except Exception as exc:
            logger.warning("fold %d evaluation failed: %s", i, exc)

    if not fold_results:
        raise ValueError("all folds failed evaluation; check data quality")

    # Aggregate
    aggregate, stability_ts = _aggregate_folds(
        fold_results, params.features_to_track, params.confidence_level
    )

    warnings = _generate_warnings(fold_results, aggregate, params)

    logger.info(
        "run_walkforward: symbols=%s window=%s method=%s n_folds=%d "
        "mean_oos=%.3f%% robustness=%.2f overfit=%.2f",
        symbols, window, params.method, len(fold_results),
        aggregate.mean_oos_expectancy,
        aggregate.robustness_score,
        aggregate.overfit_score,
    )

    return WalkForwardResult(
        symbols      = symbols,
        window       = window,
        params       = params,
        n_total_obs  = len(records),
        n_folds      = len(fold_results),
        folds        = fold_results,
        aggregate    = aggregate,
        stability_ts = stability_ts,
        warnings     = warnings,
    )
