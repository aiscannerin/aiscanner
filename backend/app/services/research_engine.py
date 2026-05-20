"""
Quantitative Research Workbench Engine
=======================================
Systematically explores and compares signal quality across features,
symbols, regimes, and time periods.

The engine operates on SimulatedTrade objects (already-simulated signal
outcomes) and applies statistical analysis to identify robust edges,
stable relationships, and potential false discoveries.

Design Principles
-----------------
No Prediction
    Feature correlations and conditional expectancy are descriptive
    statistics, not forecasts.  No model is fitted, no parameters
    optimised.

Empirical Validity
    Every metric requires a minimum sample size before being reported.
    Results below the threshold generate warnings instead of being
    silently omitted.

Stability First
    A 55% win rate that replicates across time halves and regimes is
    more valuable than an 80% win rate from a 20-trade cluster.
    Stability scores weight relationships that actually hold out-of-sample.

False Discovery Awareness
    Multiple-comparison warnings fire when many features are tested
    on small samples.  Redundant features (|r| > 0.70) are flagged so
    the researcher does not double-count correlated signals.

Features Analysed
-----------------
Continuous
    signal_dist_pct  — distance from spot to max pain (%)
    pcr              — put-call ratio (OI-weighted)
    avg_iv           — average implied volatility (%)
    days_to_expiry   — calendar days to option expiry

Categorical
    direction        — bullish | bearish
    regime           — inferred market regime (via infer_static_regime)
    vol_state        — high_iv | normal_iv | low_iv
    expiry_proximity — near (<7 days) | far (>=7 days)
    symbol           — cross-sectional comparison anchor

Note on missing features
    Wall migration velocity and OI drift velocity require time-series
    OI data at the intraday tick level, which is not captured in
    SimulatedTrade records.  These are noted as future enhancements
    pending tick-level OI capture.

Public API
----------
    extract_feature_records(trades_per_symbol)
        -> list[FeatureRecord]

    run_feature_analysis(records, window, n_buckets=4)
        -> FeatureAnalysisResult

    run_correlation_analysis(records, window)
        -> CorrelationResult

    run_stability_analysis(records, window, roll_window=20)
        -> StabilityResult

    run_rankings(records, window)
        -> RankingsResult
"""

from __future__ import annotations

import logging
import math
import statistics
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Optional

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

CONTINUOUS_FEATURES: list[str] = [
    "signal_dist_pct", "pcr", "avg_iv", "days_to_expiry"
]
CATEGORICAL_FEATURES: list[str] = [
    "direction", "regime", "vol_state", "expiry_proximity"
]
ALL_FEATURES: list[str] = CONTINUOUS_FEATURES + CATEGORICAL_FEATURES

# IV thresholds for vol_state classification
_IV_HIGH = 25.0
_IV_LOW  = 15.0

# Expiry proximity threshold (days)
_EXPIRY_NEAR_DAYS = 7

# Minimum observations before a bucket or group is reported
_MIN_OBS_BUCKET  = 3
_MIN_OBS_FEATURE = 5
_MIN_OBS_SPLIT   = 5   # minimum obs in each split-half for stability

# Warning thresholds
_WARN_LOW_SAMPLE     = 30    # total obs below this → insufficient_sample_size warning
_WARN_REGIME_DEP     = 0.25  # expectancy swing across regimes > this % → regime dependency
_WARN_CORRELATION    = 0.70  # |feature-feature r| > this → redundant features
_WARN_STABILITY      = 0.40  # stability_score below this → unstable
_WARN_NONSTATIONARITY = 0.40  # rolling directional consistency below this → non-stationary
_WARN_OVERFIT_RATIO  = 15    # n_obs < n_features * this → possible overfitting

# Human-readable feature labels
_FEATURE_LABELS: dict[str, str] = {
    "signal_dist_pct":  "Max Pain Distance (%)",
    "pcr":              "Put-Call Ratio",
    "avg_iv":           "Implied Volatility (%)",
    "days_to_expiry":   "Days to Expiry",
    "direction":        "Signal Direction",
    "regime":           "Market Regime",
    "vol_state":        "Volatility State",
    "expiry_proximity": "Expiry Proximity",
    "symbol":           "Symbol",
}


# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------

@dataclass
class FeatureRecord:
    """
    Flat representation of one simulated trade with all research features
    extracted into a single row.  Only trades with valid net_pnl_pct are
    included.
    """
    symbol:           str
    captured_at:      str
    regime:           str
    direction:        str
    vol_state:        str     # "high_iv" | "normal_iv" | "low_iv"
    expiry_proximity: str     # "near" | "far"
    signal_dist_pct:  float
    pcr:              float
    avg_iv:           Optional[float]
    days_to_expiry:   int
    net_pnl_pct:      float
    is_win:           bool


@dataclass
class BucketStats:
    """Performance statistics for one quantile bucket of a continuous feature."""
    label:          str
    range_low:      float
    range_high:     float
    n_obs:          int
    win_rate:       float
    expectancy_pct: float
    std_pct:        float
    sharpe_approx:  Optional[float]   # expectancy / std (no annualisation)

    def to_dict(self) -> dict:
        return {
            "label":          self.label,
            "range_low":      round(self.range_low,  4),
            "range_high":     round(self.range_high, 4),
            "n_obs":          self.n_obs,
            "win_rate":       round(self.win_rate, 4),
            "expectancy_pct": round(self.expectancy_pct, 4),
            "std_pct":        round(self.std_pct, 4),
            "sharpe_approx":  round(self.sharpe_approx, 4) if self.sharpe_approx is not None else None,
        }


@dataclass
class CategoryStats:
    """Performance statistics for one category of a categorical feature."""
    category:       str
    n_obs:          int
    win_rate:       float
    expectancy_pct: float
    std_pct:        float

    def to_dict(self) -> dict:
        return {
            "category":       self.category,
            "n_obs":          self.n_obs,
            "win_rate":       round(self.win_rate, 4),
            "expectancy_pct": round(self.expectancy_pct, 4),
            "std_pct":        round(self.std_pct, 4),
        }


@dataclass
class ContinuousFeatureStats:
    """Full analysis of one continuous feature vs net P&L."""
    name:          str
    label:         str
    n_obs:         int
    mean:          float
    std:           float
    pearson_r:     Optional[float]
    spearman_r:    Optional[float]
    eta_squared:   Optional[float]   # variance explained by quantile grouping
    buckets:       list[BucketStats]

    def to_dict(self) -> dict:
        return {
            "name":         self.name,
            "label":        self.label,
            "type":         "continuous",
            "n_obs":        self.n_obs,
            "mean":         round(self.mean, 4),
            "std":          round(self.std, 4),
            "pearson_r":    round(self.pearson_r, 4)   if self.pearson_r   is not None else None,
            "spearman_r":   round(self.spearman_r, 4)  if self.spearman_r  is not None else None,
            "eta_squared":  round(self.eta_squared, 4) if self.eta_squared is not None else None,
            "buckets":      [b.to_dict() for b in self.buckets],
        }


@dataclass
class CategoricalFeatureStats:
    """Full analysis of one categorical feature vs net P&L."""
    name:       str
    label:      str
    n_obs:      int
    categories: list[CategoryStats]
    eta_squared: Optional[float]

    def to_dict(self) -> dict:
        return {
            "name":        self.name,
            "label":       self.label,
            "type":        "categorical",
            "n_obs":       self.n_obs,
            "eta_squared": round(self.eta_squared, 4) if self.eta_squared is not None else None,
            "categories":  [c.to_dict() for c in self.categories],
        }


@dataclass
class CrossSectionalRow:
    """One row in a cross-sectional breakdown."""
    group:          str
    n_obs:          int
    win_rate:       float
    expectancy_pct: float
    std_pct:        float
    best_regime:    Optional[str]   # regime with highest expectancy for this group

    def to_dict(self) -> dict:
        return {
            "group":          self.group,
            "n_obs":          self.n_obs,
            "win_rate":       round(self.win_rate, 4),
            "expectancy_pct": round(self.expectancy_pct, 4),
            "std_pct":        round(self.std_pct, 4),
            "best_regime":    self.best_regime,
        }


@dataclass
class FeatureAnalysisResult:
    """Result of GET /features."""
    symbols:       list[str]
    window:        str
    n_trades:      int
    continuous:    list[ContinuousFeatureStats]
    categorical:   list[CategoricalFeatureStats]
    cross_sections: dict[str, list[CrossSectionalRow]]
    warnings:      list[str]
    generated_at:  str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )

    def to_dict(self) -> dict:
        return {
            "symbols":      self.symbols,
            "window":       self.window,
            "n_trades":     self.n_trades,
            "continuous":   [f.to_dict() for f in self.continuous],
            "categorical":  [f.to_dict() for f in self.categorical],
            "cross_sections": {
                k: [r.to_dict() for r in rows]
                for k, rows in self.cross_sections.items()
            },
            "warnings":     self.warnings,
            "generated_at": self.generated_at,
        }


@dataclass
class CorrelationPair:
    """Pearson and Spearman correlation between a feature and net_pnl_pct."""
    feature:    str
    label:      str
    pearson_r:  Optional[float]
    spearman_r: Optional[float]
    n_obs:      int

    def to_dict(self) -> dict:
        return {
            "feature":    self.feature,
            "label":      self.label,
            "pearson_r":  round(self.pearson_r,  4) if self.pearson_r  is not None else None,
            "spearman_r": round(self.spearman_r, 4) if self.spearman_r is not None else None,
            "n_obs":      self.n_obs,
        }


@dataclass
class FeaturePairCorrelation:
    """Pearson correlation between two continuous features (redundancy check)."""
    feature_a:  str
    feature_b:  str
    pearson_r:  Optional[float]
    n_obs:      int
    redundant:  bool   # |pearson_r| > _WARN_CORRELATION

    def to_dict(self) -> dict:
        return {
            "feature_a":  self.feature_a,
            "feature_b":  self.feature_b,
            "pearson_r":  round(self.pearson_r, 4) if self.pearson_r is not None else None,
            "n_obs":      self.n_obs,
            "redundant":  self.redundant,
        }


@dataclass
class CorrelationResult:
    """Result of GET /correlations."""
    symbols:                  list[str]
    window:                   str
    n_trades:                 int
    feature_pnl_correlations: list[CorrelationPair]
    feature_feature_correlations: list[FeaturePairCorrelation]
    redundant_features:       list[str]
    warnings:                 list[str]
    generated_at:             str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )

    def to_dict(self) -> dict:
        return {
            "symbols":  self.symbols,
            "window":   self.window,
            "n_trades": self.n_trades,
            "feature_pnl_correlations":     [p.to_dict() for p in self.feature_pnl_correlations],
            "feature_feature_correlations": [p.to_dict() for p in self.feature_feature_correlations],
            "redundant_features":           self.redundant_features,
            "warnings":                     self.warnings,
            "generated_at":                 self.generated_at,
        }


@dataclass
class FeatureStabilityRecord:
    """Split-half stability for one feature's relationship with net P&L."""
    feature:              str
    label:                str
    n_obs:                int
    first_half_r:         Optional[float]
    second_half_r:        Optional[float]
    direction_consistent: bool
    magnitude_ratio:      Optional[float]   # min(|r1|,|r2|) / max(|r1|,|r2|)
    stability_score:      float             # 0.0 – 1.0
    is_stable:            bool
    roll_directional_consistency: Optional[float]  # fraction of rolling windows with consistent direction

    def to_dict(self) -> dict:
        return {
            "feature":               self.feature,
            "label":                 self.label,
            "n_obs":                 self.n_obs,
            "first_half_r":          round(self.first_half_r,  4) if self.first_half_r  is not None else None,
            "second_half_r":         round(self.second_half_r, 4) if self.second_half_r is not None else None,
            "direction_consistent":  self.direction_consistent,
            "magnitude_ratio":       round(self.magnitude_ratio, 4) if self.magnitude_ratio is not None else None,
            "stability_score":       round(self.stability_score, 4),
            "is_stable":             self.is_stable,
            "roll_directional_consistency": (
                round(self.roll_directional_consistency, 4)
                if self.roll_directional_consistency is not None else None
            ),
        }


@dataclass
class SignalStabilityRecord:
    """Split-half stability for one (symbol, regime) signal combination."""
    symbol:          str
    regime:          str
    n_obs:           int
    first_half_exp:  Optional[float]
    second_half_exp: Optional[float]
    direction_consistent: bool
    stability_score: float

    def to_dict(self) -> dict:
        return {
            "symbol":          self.symbol,
            "regime":          self.regime,
            "n_obs":           self.n_obs,
            "first_half_expectancy_pct":  round(self.first_half_exp,  4) if self.first_half_exp  is not None else None,
            "second_half_expectancy_pct": round(self.second_half_exp, 4) if self.second_half_exp is not None else None,
            "direction_consistent": self.direction_consistent,
            "stability_score": round(self.stability_score, 4),
        }


@dataclass
class StabilityResult:
    """Result of GET /stability."""
    symbols:          list[str]
    window:           str
    n_trades:         int
    feature_stability: list[FeatureStabilityRecord]
    signal_stability:  list[SignalStabilityRecord]
    most_stable_features:   list[str]
    unstable_features:      list[str]
    warnings:               list[str]
    generated_at:           str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )

    def to_dict(self) -> dict:
        return {
            "symbols":    self.symbols,
            "window":     self.window,
            "n_trades":   self.n_trades,
            "feature_stability": [f.to_dict() for f in self.feature_stability],
            "signal_stability":  [s.to_dict() for s in self.signal_stability],
            "most_stable_features": self.most_stable_features,
            "unstable_features":    self.unstable_features,
            "warnings":             self.warnings,
            "generated_at":         self.generated_at,
        }


@dataclass
class RankingEntry:
    """One row in a ranked list."""
    rank:           int
    symbol:         str
    regime:         str
    n_obs:          int
    win_rate:       float
    expectancy_pct: float
    std_pct:        float
    stability_score: float
    risk_adjusted:  Optional[float]   # expectancy / std

    def to_dict(self) -> dict:
        return {
            "rank":           self.rank,
            "symbol":         self.symbol,
            "regime":         self.regime,
            "n_obs":          self.n_obs,
            "win_rate":       round(self.win_rate, 4),
            "expectancy_pct": round(self.expectancy_pct, 4),
            "std_pct":        round(self.std_pct, 4),
            "stability_score": round(self.stability_score, 4),
            "risk_adjusted":  round(self.risk_adjusted, 4) if self.risk_adjusted is not None else None,
        }


@dataclass
class RankingsResult:
    """Result of GET /rankings."""
    symbols:            list[str]
    window:             str
    n_trades:           int
    by_expectancy:      list[RankingEntry]
    by_stability:       list[RankingEntry]
    by_win_rate:        list[RankingEntry]
    by_risk_adjusted:   list[RankingEntry]
    by_regime:          dict[str, list[RankingEntry]]
    warnings:           list[str]
    generated_at:       str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )

    def to_dict(self) -> dict:
        return {
            "symbols":          self.symbols,
            "window":           self.window,
            "n_trades":         self.n_trades,
            "by_expectancy":    [e.to_dict() for e in self.by_expectancy],
            "by_stability":     [e.to_dict() for e in self.by_stability],
            "by_win_rate":      [e.to_dict() for e in self.by_win_rate],
            "by_risk_adjusted": [e.to_dict() for e in self.by_risk_adjusted],
            "by_regime": {
                regime: [e.to_dict() for e in entries]
                for regime, entries in self.by_regime.items()
            },
            "warnings":     self.warnings,
            "generated_at": self.generated_at,
        }


# ---------------------------------------------------------------------------
# Pure math helpers
# ---------------------------------------------------------------------------

def _safe_mean(xs: list[float]) -> Optional[float]:
    return sum(xs) / len(xs) if xs else None


def _safe_std(xs: list[float]) -> float:
    if len(xs) < 2:
        return 0.0
    mu = sum(xs) / len(xs)
    return math.sqrt(sum((x - mu) ** 2 for x in xs) / len(xs))  # population std


def _pearson(xs: list[float], ys: list[float]) -> Optional[float]:
    """Pearson r between two equal-length lists."""
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


def _rank_list(xs: list[float]) -> list[float]:
    """Return fractional ranks (1-based, averaged ties) for a list."""
    n = len(xs)
    if n == 0:
        return []
    indexed  = sorted(range(n), key=lambda i: xs[i])
    ranks    = [0.0] * n
    i = 0
    while i < n:
        j = i
        while j < n - 1 and xs[indexed[j + 1]] == xs[indexed[j]]:
            j += 1
        avg_rank = (i + j) / 2.0 + 1.0
        for k in range(i, j + 1):
            ranks[indexed[k]] = avg_rank
        i = j + 1
    return ranks


def _spearman(xs: list[float], ys: list[float]) -> Optional[float]:
    """Spearman rank correlation between two equal-length lists."""
    if len(xs) != len(ys) or len(xs) < 2:
        return None
    return _pearson(_rank_list(xs), _rank_list(ys))


def _eta_squared(groups: list[list[float]]) -> Optional[float]:
    """
    Compute η² (eta squared): fraction of total variance explained by grouping.
    η² = SS_between / SS_total = 1 - (SS_within / SS_total)
    Ranges [0, 1]. Returns None if total variance is zero or groups are empty.
    """
    all_vals = [v for g in groups for v in g]
    n_total  = len(all_vals)
    if n_total < 2:
        return None
    grand_mean = sum(all_vals) / n_total
    ss_total   = sum((v - grand_mean) ** 2 for v in all_vals)
    if ss_total < 1e-10:
        return None
    ss_within  = sum(
        sum((v - (sum(g) / len(g))) ** 2 for v in g)
        for g in groups if len(g) > 0
    )
    return max(0.0, min(1.0, 1.0 - ss_within / ss_total))


def _quantile_boundaries(values: list[float], n_buckets: int) -> list[float]:
    """Return n_buckets+1 boundary values (including min and max)."""
    if not values or n_buckets < 1:
        return []
    sv  = sorted(values)
    n   = len(sv)
    boundaries = [sv[0]]
    for i in range(1, n_buckets):
        idx = (i / n_buckets) * (n - 1)
        lo  = int(idx)
        hi  = min(lo + 1, n - 1)
        boundaries.append(sv[lo] + (idx - lo) * (sv[hi] - sv[lo]))
    boundaries.append(sv[-1])
    return boundaries


# ---------------------------------------------------------------------------
# Feature extraction
# ---------------------------------------------------------------------------

def _vol_state(avg_iv: Optional[float]) -> str:
    if avg_iv is None:
        return "normal_iv"
    if avg_iv >= _IV_HIGH:
        return "high_iv"
    if avg_iv <= _IV_LOW:
        return "low_iv"
    return "normal_iv"


def _expiry_proximity(days_to_expiry: int) -> str:
    return "near" if days_to_expiry < _EXPIRY_NEAR_DAYS else "far"


def extract_feature_records(
    trades_per_symbol: dict[str, list],
) -> list[FeatureRecord]:
    """
    Convert a symbol → list[SimulatedTrade] mapping into a flat list of
    FeatureRecord rows.  Only trades with valid net_pnl_pct are included.

    Regime label is inferred via infer_static_regime for each trade.
    """
    from app.services.regime_classifier import infer_static_regime

    records: list[FeatureRecord] = []

    for symbol, trades in trades_per_symbol.items():
        for t in trades:
            if t.net_pnl_pct is None:
                continue

            try:
                regime = infer_static_regime(
                    distance_pct   = t.signal_dist_pct,
                    days_to_expiry = t.days_to_expiry,
                    pcr            = t.pcr,
                    avg_iv         = t.avg_iv,
                    direction      = t.direction,
                )
            except Exception:
                regime = "unknown"

            records.append(FeatureRecord(
                symbol           = symbol,
                captured_at      = t.captured_at,
                regime           = regime,
                direction        = t.direction,
                vol_state        = _vol_state(t.avg_iv),
                expiry_proximity = _expiry_proximity(t.days_to_expiry),
                signal_dist_pct  = t.signal_dist_pct,
                pcr              = t.pcr,
                avg_iv           = t.avg_iv,
                days_to_expiry   = t.days_to_expiry,
                net_pnl_pct      = t.net_pnl_pct,
                is_win           = t.net_pnl_pct > 0,
            ))

    # Sort chronologically for stable split-half analysis
    records.sort(key=lambda r: r.captured_at)
    return records


# ---------------------------------------------------------------------------
# Bucketing helpers
# ---------------------------------------------------------------------------

def _bucket_continuous(
    records:   list[FeatureRecord],
    feature:   str,
    n_buckets: int,
) -> list[BucketStats]:
    """
    Split records into n_buckets quantile groups by feature value,
    compute performance stats in each group.  Skips records with None
    values for the feature (only avg_iv can be None).
    """
    valid = [(getattr(r, feature), r.net_pnl_pct, r.is_win)
             for r in records if getattr(r, feature) is not None]
    if len(valid) < _MIN_OBS_FEATURE:
        return []

    fvals  = [v[0] for v in valid]
    bounds = _quantile_boundaries(fvals, n_buckets)
    if len(bounds) < 2:
        return []

    buckets: list[BucketStats] = []
    for i in range(n_buckets):
        lo = bounds[i]
        hi = bounds[i + 1]
        # Include upper boundary in the last bucket to capture the maximum
        if i == n_buckets - 1:
            group = [(f, p, w) for f, p, w in valid if lo <= f <= hi]
        else:
            group = [(f, p, w) for f, p, w in valid if lo <= f < hi]

        if len(group) < _MIN_OBS_BUCKET:
            continue

        pnls    = [p for _, p, _ in group]
        wins    = sum(1 for _, _, w in group if w)
        n       = len(group)
        exp     = sum(pnls) / n
        std     = _safe_std(pnls)
        sharpe  = exp / std if std > 1e-6 else None
        label   = f"Q{i+1} ({lo:.2f}–{hi:.2f})"

        buckets.append(BucketStats(
            label           = label,
            range_low       = lo,
            range_high      = hi,
            n_obs           = n,
            win_rate        = round(wins / n, 4),
            expectancy_pct  = round(exp, 4),
            std_pct         = round(std, 4),
            sharpe_approx   = round(sharpe, 4) if sharpe is not None else None,
        ))
    return buckets


def _category_stats(
    records: list[FeatureRecord],
    feature: str,
) -> list[CategoryStats]:
    """
    Group records by categorical feature value and compute performance stats.
    """
    groups: dict[str, list[FeatureRecord]] = defaultdict(list)
    for r in records:
        groups[getattr(r, feature)].append(r)

    cats: list[CategoryStats] = []
    for cat, grp in sorted(groups.items()):
        if len(grp) < _MIN_OBS_BUCKET:
            continue
        pnls = [r.net_pnl_pct for r in grp]
        wins = sum(1 for r in grp if r.is_win)
        n    = len(grp)
        cats.append(CategoryStats(
            category       = cat,
            n_obs          = n,
            win_rate       = round(wins / n, 4),
            expectancy_pct = round(sum(pnls) / n, 4),
            std_pct        = round(_safe_std(pnls), 4),
        ))
    return cats


# ---------------------------------------------------------------------------
# Feature analysis
# ---------------------------------------------------------------------------

def _analyse_continuous(
    records:   list[FeatureRecord],
    feature:   str,
    n_buckets: int,
) -> ContinuousFeatureStats:
    valid_f   = [getattr(r, feature) for r in records if getattr(r, feature) is not None]
    valid_p   = [r.net_pnl_pct       for r in records if getattr(r, feature) is not None]
    n_obs     = len(valid_f)
    mean_f    = sum(valid_f) / n_obs if n_obs > 0 else 0.0
    std_f     = _safe_std(valid_f)

    pearson   = _pearson(valid_f, valid_p)   if n_obs >= _MIN_OBS_FEATURE else None
    spearman  = _spearman(valid_f, valid_p)  if n_obs >= _MIN_OBS_FEATURE else None

    buckets   = _bucket_continuous(records, feature, n_buckets)
    eta_sq    = _eta_squared([
        [valid_p[i] for i in range(n_obs)
         if bounds_lo <= valid_f[i] < bounds_hi]
        for bounds_lo, bounds_hi in (
            [(b.range_low, b.range_high) for b in buckets]
            if buckets else []
        )
    ]) if buckets else None

    # Recompute eta_squared properly from bucket groups
    if buckets and n_obs >= _MIN_OBS_FEATURE:
        bucket_groups: list[list[float]] = []
        for b in buckets:
            grp = [valid_p[i] for i in range(n_obs)
                   if b.range_low <= valid_f[i] <= b.range_high]
            if grp:
                bucket_groups.append(grp)
        eta_sq = _eta_squared(bucket_groups) if bucket_groups else None
    else:
        eta_sq = None

    return ContinuousFeatureStats(
        name        = feature,
        label       = _FEATURE_LABELS.get(feature, feature),
        n_obs       = n_obs,
        mean        = round(mean_f, 4),
        std         = round(std_f, 4),
        pearson_r   = round(pearson,  4) if pearson  is not None else None,
        spearman_r  = round(spearman, 4) if spearman is not None else None,
        eta_squared = round(eta_sq,   4) if eta_sq   is not None else None,
        buckets     = buckets,
    )


def _analyse_categorical(
    records: list[FeatureRecord],
    feature: str,
) -> CategoricalFeatureStats:
    cats   = _category_stats(records, feature)
    groups = [[r.net_pnl_pct for r in records
               if getattr(r, feature) == c.category]
              for c in cats]
    eta_sq = _eta_squared(groups) if len(groups) >= 2 else None

    return CategoricalFeatureStats(
        name        = feature,
        label       = _FEATURE_LABELS.get(feature, feature),
        n_obs       = len(records),
        eta_squared = round(eta_sq, 4) if eta_sq is not None else None,
        categories  = cats,
    )


def _cross_sections(
    records: list[FeatureRecord],
) -> dict[str, list[CrossSectionalRow]]:
    """Build cross-sectional breakdowns by symbol, direction, vol_state, expiry_proximity."""
    result: dict[str, list[CrossSectionalRow]] = {}

    for dim in ("symbol", "direction", "vol_state", "expiry_proximity"):
        groups: dict[str, list[FeatureRecord]] = defaultdict(list)
        for r in records:
            groups[getattr(r, dim)].append(r)

        rows: list[CrossSectionalRow] = []
        for group_val, grp in sorted(groups.items()):
            if len(grp) < _MIN_OBS_BUCKET:
                continue
            pnls = [r.net_pnl_pct for r in grp]
            wins = sum(1 for r in grp if r.is_win)
            n    = len(grp)

            # Best regime for this group
            regime_exp: dict[str, float] = {}
            regime_n:   dict[str, int]   = {}
            for r in grp:
                regime_exp[r.regime] = regime_exp.get(r.regime, 0.0) + r.net_pnl_pct
                regime_n[r.regime]   = regime_n.get(r.regime, 0) + 1
            best_regime = None
            if regime_n:
                best_regime = max(regime_exp.keys(),
                                  key=lambda rg: (regime_exp[rg] / regime_n[rg])
                                  if regime_n[rg] >= _MIN_OBS_BUCKET else -999)

            rows.append(CrossSectionalRow(
                group          = group_val,
                n_obs          = n,
                win_rate       = round(wins / n, 4),
                expectancy_pct = round(sum(pnls) / n, 4),
                std_pct        = round(_safe_std(pnls), 4),
                best_regime    = best_regime,
            ))

        result[dim] = rows
    return result


# ---------------------------------------------------------------------------
# Correlation analysis
# ---------------------------------------------------------------------------

def _feature_pnl_correlations(records: list[FeatureRecord]) -> list[CorrelationPair]:
    pairs: list[CorrelationPair] = []
    pnls = [r.net_pnl_pct for r in records]

    for feat in CONTINUOUS_FEATURES:
        fvals = [getattr(r, feat) for r in records if getattr(r, feat) is not None]
        p_for = [r.net_pnl_pct    for r in records if getattr(r, feat) is not None]
        n     = len(fvals)
        pearson  = _pearson(fvals, p_for)  if n >= _MIN_OBS_FEATURE else None
        spearman = _spearman(fvals, p_for) if n >= _MIN_OBS_FEATURE else None
        pairs.append(CorrelationPair(
            feature    = feat,
            label      = _FEATURE_LABELS.get(feat, feat),
            pearson_r  = round(pearson,  4) if pearson  is not None else None,
            spearman_r = round(spearman, 4) if spearman is not None else None,
            n_obs      = n,
        ))

    # Categorical features: point-biserial (Pearson between dummy 0/1 and pnl)
    for feat in CATEGORICAL_FEATURES:
        categories = sorted(set(getattr(r, feat) for r in records))
        for cat in categories:
            dummy = [1.0 if getattr(r, feat) == cat else 0.0 for r in records]
            n     = len(dummy)
            pearson  = _pearson(dummy, pnls) if n >= _MIN_OBS_FEATURE else None
            spearman = _spearman(dummy, pnls) if n >= _MIN_OBS_FEATURE else None
            pairs.append(CorrelationPair(
                feature    = f"{feat}={cat}",
                label      = f"{_FEATURE_LABELS.get(feat, feat)} = {cat}",
                pearson_r  = round(pearson,  4) if pearson  is not None else None,
                spearman_r = round(spearman, 4) if spearman is not None else None,
                n_obs      = n,
            ))

    return pairs


def _feature_feature_correlations(records: list[FeatureRecord]) -> list[FeaturePairCorrelation]:
    """Pairwise Pearson correlations between all continuous features."""
    pairs: list[FeaturePairCorrelation] = []
    feats = CONTINUOUS_FEATURES

    for i in range(len(feats)):
        for j in range(i + 1, len(feats)):
            fa, fb = feats[i], feats[j]
            # Use only records where both features are non-None
            ab = [(getattr(r, fa), getattr(r, fb)) for r in records
                  if getattr(r, fa) is not None and getattr(r, fb) is not None]
            if not ab:
                continue
            a_vals = [x[0] for x in ab]
            b_vals = [x[1] for x in ab]
            r = _pearson(a_vals, b_vals)
            redundant = abs(r) > _WARN_CORRELATION if r is not None else False
            pairs.append(FeaturePairCorrelation(
                feature_a = fa,
                feature_b = fb,
                pearson_r = round(r, 4) if r is not None else None,
                n_obs     = len(ab),
                redundant = redundant,
            ))

    return pairs


# ---------------------------------------------------------------------------
# Stability analysis
# ---------------------------------------------------------------------------

def _split_half_feature_stability(
    records:    list[FeatureRecord],
    feature:    str,
    roll_window: int,
) -> FeatureStabilityRecord:
    """
    Split records chronologically in half; compute Pearson r between feature
    and net_pnl_pct in each half.  Assess directional and magnitude stability.
    """
    label = _FEATURE_LABELS.get(feature, feature)

    valid = [(getattr(r, feature), r.net_pnl_pct)
             for r in records if getattr(r, feature) is not None]
    n = len(valid)

    if n < 2 * _MIN_OBS_SPLIT:
        return FeatureStabilityRecord(
            feature=feature, label=label, n_obs=n,
            first_half_r=None, second_half_r=None,
            direction_consistent=False, magnitude_ratio=None,
            stability_score=0.0, is_stable=False,
            roll_directional_consistency=None,
        )

    mid = n // 2
    h1_f = [v[0] for v in valid[:mid]]
    h1_p = [v[1] for v in valid[:mid]]
    h2_f = [v[0] for v in valid[mid:]]
    h2_p = [v[1] for v in valid[mid:]]

    r1 = _pearson(h1_f, h1_p)
    r2 = _pearson(h2_f, h2_p)

    if r1 is None or r2 is None:
        dir_consistent = False
        mag_ratio      = None
        stab_score     = 0.0
    else:
        dir_consistent = (r1 >= 0) == (r2 >= 0)
        if abs(r1) > 1e-6 and abs(r2) > 1e-6:
            mag_ratio = min(abs(r1), abs(r2)) / max(abs(r1), abs(r2))
        else:
            mag_ratio = None
        stab_score = (mag_ratio if mag_ratio is not None else 0.0) if dir_consistent else 0.0

    # Rolling directional consistency
    roll_dc: Optional[float] = None
    if n >= roll_window + _MIN_OBS_SPLIT:
        window_rs: list[float] = []
        for start in range(0, n - roll_window + 1, max(1, roll_window // 2)):
            end   = start + roll_window
            wf    = [valid[k][0] for k in range(start, end)]
            wp    = [valid[k][1] for k in range(start, end)]
            wr    = _pearson(wf, wp)
            if wr is not None:
                window_rs.append(wr)
        if len(window_rs) >= 2:
            # Fraction of windows with the same sign as the majority
            n_pos = sum(1 for rr in window_rs if rr >= 0)
            n_neg = len(window_rs) - n_pos
            majority_count = max(n_pos, n_neg)
            roll_dc = majority_count / len(window_rs)

    is_stable = stab_score >= _WARN_STABILITY

    return FeatureStabilityRecord(
        feature=feature, label=label, n_obs=n,
        first_half_r  = round(r1, 4) if r1 is not None else None,
        second_half_r = round(r2, 4) if r2 is not None else None,
        direction_consistent = dir_consistent,
        magnitude_ratio      = round(mag_ratio, 4) if mag_ratio is not None else None,
        stability_score      = round(stab_score, 4),
        is_stable            = is_stable,
        roll_directional_consistency = round(roll_dc, 4) if roll_dc is not None else None,
    )


def _signal_stability(records: list[FeatureRecord]) -> list[SignalStabilityRecord]:
    """
    Split-half stability for each (symbol, regime) combination.
    Only computed for groups with >= 2 * _MIN_OBS_SPLIT records.
    """
    groups: dict[tuple, list[FeatureRecord]] = defaultdict(list)
    for r in records:
        groups[(r.symbol, r.regime)].append(r)

    results: list[SignalStabilityRecord] = []
    for (sym, regime), grp in sorted(groups.items()):
        n = len(grp)
        if n < 2 * _MIN_OBS_SPLIT:
            continue
        mid = n // 2
        h1  = grp[:mid]
        h2  = grp[mid:]

        exp1 = sum(r.net_pnl_pct for r in h1) / len(h1) if h1 else None
        exp2 = sum(r.net_pnl_pct for r in h2) / len(h2) if h2 else None

        if exp1 is None or exp2 is None:
            dir_ok  = False
            stab    = 0.0
        else:
            dir_ok = (exp1 >= 0) == (exp2 >= 0)
            if abs(exp1) > 1e-6 and abs(exp2) > 1e-6:
                mag = min(abs(exp1), abs(exp2)) / max(abs(exp1), abs(exp2))
            else:
                mag = 0.0
            stab = mag if dir_ok else 0.0

        results.append(SignalStabilityRecord(
            symbol           = sym,
            regime           = regime,
            n_obs            = n,
            first_half_exp   = round(exp1, 4) if exp1 is not None else None,
            second_half_exp  = round(exp2, 4) if exp2 is not None else None,
            direction_consistent = dir_ok,
            stability_score  = round(stab, 4),
        ))

    results.sort(key=lambda s: s.stability_score, reverse=True)
    return results


# ---------------------------------------------------------------------------
# Rankings
# ---------------------------------------------------------------------------

def _build_ranking_entries(
    records:  list[FeatureRecord],
    sig_stab: list[SignalStabilityRecord],
) -> list[RankingEntry]:
    """
    Build one RankingEntry per (symbol, regime) group.
    Stability scores are joined from signal stability results.
    """
    stab_map: dict[tuple, float] = {
        (s.symbol, s.regime): s.stability_score
        for s in sig_stab
    }

    groups: dict[tuple, list[FeatureRecord]] = defaultdict(list)
    for r in records:
        groups[(r.symbol, r.regime)].append(r)

    entries: list[RankingEntry] = []
    for (sym, regime), grp in groups.items():
        if len(grp) < _MIN_OBS_BUCKET:
            continue
        pnls    = [r.net_pnl_pct for r in grp]
        wins    = sum(1 for r in grp if r.is_win)
        n       = len(grp)
        exp     = sum(pnls) / n
        std     = _safe_std(pnls)
        wr      = wins / n
        stab    = stab_map.get((sym, regime), 0.0)
        risk_adj = exp / std if std > 1e-6 else None

        entries.append(RankingEntry(
            rank           = 0,          # filled after sorting
            symbol         = sym,
            regime         = regime,
            n_obs          = n,
            win_rate       = round(wr, 4),
            expectancy_pct = round(exp, 4),
            std_pct        = round(std, 4),
            stability_score= round(stab, 4),
            risk_adjusted  = round(risk_adj, 4) if risk_adj is not None else None,
        ))
    return entries


def _rank_entries(entries: list[RankingEntry], key, reverse=True) -> list[RankingEntry]:
    """Sort and assign sequential rank numbers."""
    def _sort_key(e: RankingEntry):
        v = key(e)
        return v if v is not None else (-1e9 if reverse else 1e9)

    sorted_entries = sorted(entries, key=_sort_key, reverse=reverse)
    for i, e in enumerate(sorted_entries):
        e.rank = i + 1
    return sorted_entries


# ---------------------------------------------------------------------------
# Warning generation
# ---------------------------------------------------------------------------

def _research_warnings(
    records:         list[FeatureRecord],
    feature_stats:   list,
    feat_stability:  list[FeatureStabilityRecord],
    feat_feature_corrs: list[FeaturePairCorrelation],
) -> list[str]:
    warnings: list[str] = []
    n = len(records)

    # Insufficient sample
    if n < _WARN_LOW_SAMPLE:
        warnings.append(
            f"insufficient_sample_size: only {n} trades — most metrics are "
            f"unreliable below {_WARN_LOW_SAMPLE}; widen window or add symbols"
        )

    # Possible overfitting: too many features tested on small sample
    n_features = len(ALL_FEATURES)
    if n > 0 and n < n_features * _WARN_OVERFIT_RATIO:
        warnings.append(
            f"possible_overfitting: {n_features} features tested on {n} trades "
            f"(ratio {n/n_features:.1f}:1; recommend >= {_WARN_OVERFIT_RATIO}:1); "
            f"treat feature rankings as exploratory only"
        )

    # Unstable features
    unstable = [f.feature for f in feat_stability if not f.is_stable and f.n_obs >= 2 * _MIN_OBS_SPLIT]
    if unstable:
        warnings.append(
            f"unstable_relationships: features {unstable} do not replicate "
            f"across split-halves — their predictive patterns may be data artefacts"
        )

    # Non-stationary (low rolling directional consistency)
    nonstat = [
        f.feature for f in feat_stability
        if f.roll_directional_consistency is not None
        and f.roll_directional_consistency < _WARN_NONSTATIONARITY
    ]
    if nonstat:
        warnings.append(
            f"non_stationary_behavior: features {nonstat} show directional "
            f"inconsistency across rolling windows — the feature-PnL relationship "
            f"switches sign over time"
        )

    # High regime dependency
    regime_pnls: dict[str, list[float]] = defaultdict(list)
    for r in records:
        regime_pnls[r.regime].append(r.net_pnl_pct)
    regime_means = {
        rg: sum(v) / len(v)
        for rg, v in regime_pnls.items()
        if len(v) >= _MIN_OBS_BUCKET
    }
    if len(regime_means) >= 2:
        best  = max(regime_means.values())
        worst = min(regime_means.values())
        swing = best - worst
        if swing > _WARN_REGIME_DEP:
            warnings.append(
                f"high_regime_dependency: expectancy swings {swing:.2f}% across regimes "
                f"(best: {best:.2f}%, worst: {worst:.2f}%) — performance is heavily "
                f"regime-conditional; always filter by regime before deploying"
            )

    # Redundant features
    redundant_pairs = [(p.feature_a, p.feature_b) for p in feat_feature_corrs if p.redundant]
    if redundant_pairs:
        warnings.append(
            f"redundant_features: feature pairs {redundant_pairs} have |Pearson r| > "
            f"{_WARN_CORRELATION} — they carry overlapping information; "
            f"use only one from each pair for independent analysis"
        )

    return warnings


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def run_feature_analysis(
    records:   list[FeatureRecord],
    symbols:   list[str],
    window:    str,
    n_buckets: int = 4,
) -> FeatureAnalysisResult:
    """
    Analyse each feature's conditional relationship with net P&L.

    Args:
        records   : FeatureRecord list from extract_feature_records().
        symbols   : Symbol list for labelling.
        window    : Lookback window string.
        n_buckets : Quantile buckets for continuous features (default 4 = quartiles).

    Returns:
        FeatureAnalysisResult with per-feature stats, cross-sections, and warnings.

    Raises:
        ValueError if records is empty.
    """
    if not records:
        raise ValueError("no usable trades; widen the window or reduce filters")

    n_buckets = max(2, min(n_buckets, 10))

    continuous  = [_analyse_continuous(records, f, n_buckets) for f in CONTINUOUS_FEATURES]
    categorical = [_analyse_categorical(records, f) for f in CATEGORICAL_FEATURES]
    cross       = _cross_sections(records)

    feat_stab = [
        _split_half_feature_stability(records, f, roll_window=20)
        for f in CONTINUOUS_FEATURES
    ]
    ff_corrs  = _feature_feature_correlations(records)
    warns     = _research_warnings(records, continuous + categorical, feat_stab, ff_corrs)

    return FeatureAnalysisResult(
        symbols       = symbols,
        window        = window,
        n_trades      = len(records),
        continuous    = continuous,
        categorical   = categorical,
        cross_sections = cross,
        warnings      = warns,
    )


def run_correlation_analysis(
    records: list[FeatureRecord],
    symbols: list[str],
    window:  str,
) -> CorrelationResult:
    """
    Compute feature-PnL and feature-feature correlations.

    Returns:
        CorrelationResult including point-biserial correlations for categorical
        features, Pearson+Spearman for continuous features, and redundancy flags.
    """
    if not records:
        raise ValueError("no usable trades; widen the window or reduce filters")

    fp_corrs = _feature_pnl_correlations(records)
    ff_corrs = _feature_feature_correlations(records)
    redundant = sorted({
        name
        for p in ff_corrs if p.redundant
        for name in (p.feature_a, p.feature_b)
    })

    feat_stab = [
        _split_half_feature_stability(records, f, roll_window=20)
        for f in CONTINUOUS_FEATURES
    ]
    warns = _research_warnings(records, [], feat_stab, ff_corrs)

    return CorrelationResult(
        symbols                       = symbols,
        window                        = window,
        n_trades                      = len(records),
        feature_pnl_correlations      = fp_corrs,
        feature_feature_correlations  = ff_corrs,
        redundant_features            = redundant,
        warnings                      = warns,
    )


def run_stability_analysis(
    records:     list[FeatureRecord],
    symbols:     list[str],
    window:      str,
    roll_window: int = 20,
) -> StabilityResult:
    """
    Assess how consistently each feature's signal-PnL relationship holds
    across time periods and (symbol, regime) groupings.

    Args:
        records     : FeatureRecord list.
        roll_window : Size of rolling window for directional consistency (trades).

    Returns:
        StabilityResult with per-feature and per-signal stability records.
    """
    if not records:
        raise ValueError("no usable trades; widen the window or reduce filters")

    roll_window = max(5, roll_window)

    feat_stab = [
        _split_half_feature_stability(records, f, roll_window)
        for f in CONTINUOUS_FEATURES
    ]
    sig_stab = _signal_stability(records)

    most_stable = [f.feature for f in feat_stab if f.is_stable]
    unstable    = [f.feature for f in feat_stab
                   if not f.is_stable and f.n_obs >= 2 * _MIN_OBS_SPLIT]

    ff_corrs = _feature_feature_correlations(records)
    warns    = _research_warnings(records, [], feat_stab, ff_corrs)

    return StabilityResult(
        symbols               = symbols,
        window                = window,
        n_trades              = len(records),
        feature_stability     = feat_stab,
        signal_stability      = sig_stab,
        most_stable_features  = most_stable,
        unstable_features     = unstable,
        warnings              = warns,
    )


def run_rankings(
    records: list[FeatureRecord],
    symbols: list[str],
    window:  str,
) -> RankingsResult:
    """
    Rank all (symbol, regime) signal combinations by expectancy, stability,
    win rate, and risk-adjusted return.  Also ranks within each regime.

    Returns:
        RankingsResult with four sorted ranking lists and per-regime rankings.
    """
    if not records:
        raise ValueError("no usable trades; widen the window or reduce filters")

    sig_stab = _signal_stability(records)
    entries  = _build_ranking_entries(records, sig_stab)

    if not entries:
        raise ValueError(
            "no (symbol, regime) group has enough trades "
            f"(>= {_MIN_OBS_BUCKET}) to rank"
        )

    by_exp    = _rank_entries([RankingEntry(**e.__dict__) for e in entries],
                               key=lambda e: e.expectancy_pct)
    by_stab   = _rank_entries([RankingEntry(**e.__dict__) for e in entries],
                               key=lambda e: e.stability_score)
    by_wr     = _rank_entries([RankingEntry(**e.__dict__) for e in entries],
                               key=lambda e: e.win_rate)
    by_ra     = _rank_entries([RankingEntry(**e.__dict__) for e in entries],
                               key=lambda e: e.risk_adjusted)

    # Per-regime rankings
    by_regime: dict[str, list[RankingEntry]] = {}
    regimes = sorted(set(e.regime for e in entries))
    for regime in regimes:
        regime_entries = [RankingEntry(**e.__dict__) for e in entries if e.regime == regime]
        if regime_entries:
            by_regime[regime] = _rank_entries(regime_entries, key=lambda e: e.expectancy_pct)

    ff_corrs  = _feature_feature_correlations(records)
    feat_stab = [
        _split_half_feature_stability(records, f, roll_window=20)
        for f in CONTINUOUS_FEATURES
    ]
    warns = _research_warnings(records, [], feat_stab, ff_corrs)

    return RankingsResult(
        symbols         = symbols,
        window          = window,
        n_trades        = len(records),
        by_expectancy   = by_exp,
        by_stability    = by_stab,
        by_win_rate     = by_wr,
        by_risk_adjusted= by_ra,
        by_regime       = by_regime,
        warnings        = warns,
    )
