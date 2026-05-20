"""
Monte Carlo Robustness and Stress-Testing Engine
=================================================
Stress-tests the statistical properties of a trade return series under
randomness and adverse market conditions.

The engine operates on net_pnl_pct values extracted from SimulatedTrade
objects.  It does NOT re-run the full portfolio simulator for each iteration;
instead it applies a simplified compounding model that isolates the pure
statistical behaviour of trade returns without position management noise.

This separation is intentional: the Monte Carlo layer answers "are the
expectancy statistics robust?" while the portfolio engine answers "how do
risk controls affect deployment?"

Design Principles
-----------------
No Fake Precision
    Position sizes and capital values are approximations.  The output is a
    DISTRIBUTION of outcomes, not a single point estimate.  Confidence
    intervals are always reported alongside medians.

Sequence Risk First
    Many methods (random_order, block_bootstrap, drawdown_clustering) focus
    on sequence risk — the danger that the same trades, in a different order,
    produce very different outcomes.  This is the most commonly underestimated
    risk in backtesting.

Conservative Ruin Definition
    Ruin is triggered when equity falls to (100 - ruin_threshold_pct)% of
    starting capital.  Default: 50%, meaning a 50% drawdown = ruin.  The path
    halts at the ruin event, avoiding phantom recovery.

Resampling Methods
------------------
bootstrap
    IID sample with replacement.  Fastest, assumes trades are independent.
    Standard for estimating parameter uncertainty.

random_order
    Same trades, random sequence.  Isolates PURE sequence risk with no
    distributional change.  If results differ widely, the original ordering
    is carrying hidden information.

block_bootstrap
    Sample overlapping blocks of size block_size.  Preserves short-range
    autocorrelation (e.g. trending periods, loss streaks).

regime_shuffle
    Shuffle trade order WITHIN each regime bucket.  Tests whether the specific
    within-regime sequence matters while preserving regime composition.

Stress Scenarios
----------------
consecutive_losses    Front-load worst N trades (maximum sequence risk).
vol_shock_1_5x        Stretch P&L distribution 1.5× around its mean.
vol_shock_2x          Stretch P&L distribution 2× around its mean.
slippage_3x           Triple the per-trade round-trip cost.
drawdown_clustering   Sort ALL losses before ALL wins (worst-case ordering).
correlated_downside   Amplify all losing trade P&Ls by 1.5× (correlated crash).
liquidity_deterioration  Add 0.9% extra round-trip cost (10× slippage degradation).
regime_concentration  Use only the dominant regime's trades (regime filter stress).

Public API
----------
    extract_pnl_regimes(trades)
        -> tuple[list[float], list[str]]   # (pnls, regime_labels)

    run_monte_carlo(trades, params, symbol, window)
        -> MonteCarloSummary

    run_stress_tests(trades, mc_params, symbol, window)
        -> list[StressScenarioResult]
"""

from __future__ import annotations

import logging
import math
import random
import statistics
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Optional

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

VALID_MC_METHODS = {"bootstrap", "random_order", "block_bootstrap", "regime_shuffle"}

_MIN_TRADES_FOR_MC      = 5       # refuse to run below this
_MIN_SIMS_WARNING       = 200     # warn if fewer simulations requested
_DEFAULT_N_STRESS_SIMS  = 500     # lighter MC for each stress scenario

# Warning thresholds
_FRAGILE_P25_RETURN     = 0.0     # 25th-pct return < 0 → fragile
_HIGH_TAIL_DD_PCT       = 30.0    # 95th-pct max DD > 30% → high tail risk
_HIGH_ES_LOSS_PCT       = -15.0   # CVaR < −15% → high tail risk
_POOR_RECOVERY_TRADES   = 20      # median recovery > 20 → poor profile
_REGIME_SENSITIVITY     = 0.30    # |expectancy change| > 30% → excessive
_HIGH_RUIN_PCT          = 5.0     # ruin probability > 5% → warning


# ---------------------------------------------------------------------------
# Parameter dataclass
# ---------------------------------------------------------------------------

@dataclass
class MonteCarloParams:
    """
    Parameters for a Monte Carlo simulation run.

    Attributes
    ----------
    n_simulations
        Number of simulation paths.  Minimum meaningful: 200.  Default 1 000.
    method
        Resampling method: "bootstrap" | "random_order" |
        "block_bootstrap" | "regime_shuffle".
    position_size_pct
        Fixed position size as % of equity per trade.  Used for compounding
        in the simplified path model.  Default 2.0%.
    initial_capital
        Starting equity for path simulation.  Default ₹1 000 000.
    ruin_threshold_pct
        Equity drop that counts as ruin (% of initial capital).  Default 50%.
        A path that loses 50% from start → labelled "ruined".
    block_size
        Block length for block_bootstrap.  Default 5.
    seed
        Optional RNG seed for reproducibility.  None → non-deterministic.
    """
    n_simulations:      int            = 1_000
    method:             str            = "bootstrap"
    position_size_pct:  float          = 2.0
    initial_capital:    float          = 1_000_000.0
    ruin_threshold_pct: float          = 50.0
    block_size:         int            = 5
    seed:               Optional[int]  = None

    def validate(self) -> list[str]:
        issues: list[str] = []
        if self.method not in VALID_MC_METHODS:
            issues.append(
                f"invalid method '{self.method}'; "
                f"choose from {sorted(VALID_MC_METHODS)}"
            )
        if self.n_simulations < 1:
            issues.append("n_simulations must be >= 1")
        if self.n_simulations > 10_000:
            issues.append("n_simulations must be <= 10 000")
        if self.position_size_pct <= 0:
            issues.append("position_size_pct must be positive")
        if self.initial_capital <= 0:
            issues.append("initial_capital must be positive")
        if not (1.0 <= self.ruin_threshold_pct <= 99.0):
            issues.append("ruin_threshold_pct must be in [1, 99]")
        if self.block_size < 2:
            issues.append("block_size must be >= 2")
        return issues

    def to_dict(self) -> dict:
        return {
            "n_simulations":      self.n_simulations,
            "method":             self.method,
            "position_size_pct":  self.position_size_pct,
            "initial_capital":    self.initial_capital,
            "ruin_threshold_pct": self.ruin_threshold_pct,
            "block_size":         self.block_size,
            "seed":               self.seed,
        }


# ---------------------------------------------------------------------------
# Result dataclasses
# ---------------------------------------------------------------------------

@dataclass
class SinglePathResult:
    """Outcome of one simulated equity path."""
    final_equity:       float
    total_return_pct:   float
    max_drawdown_pct:   float
    ruined:             bool
    recovery_durations: list[int]   # trades from each peak to next full recovery


@dataclass
class MonteCarloSummary:
    """Aggregate statistics across all simulation paths."""
    # Identity
    symbol:   str
    window:   str
    method:   str
    n_sims:   int
    n_trades: int   # trades in input dataset (after no_data filter)

    # Return distribution percentiles
    return_p5:  float
    return_p25: float
    return_p50: float
    return_p75: float
    return_p95: float

    # Max-drawdown distribution (higher = worse)
    max_dd_p5:  float   # best-case max DD across paths
    max_dd_p25: float
    max_dd_p50: float
    max_dd_p75: float
    max_dd_p95: float   # worst-case max DD across paths

    # Tail risk
    var_pct:                float   # 5th-pct return (VaR at 95% confidence)
    expected_shortfall_pct: float   # CVaR = mean of worst 5% returns
    capital_at_risk_pct:    float   # |var_pct| as a positive loss magnitude

    # Ruin
    probability_of_ruin: float
    ruin_threshold_pct:  float

    # Recovery (trades from peak to new high, across all paths)
    median_recovery_trades: Optional[float]
    p95_recovery_trades:    Optional[float]

    # Extremes
    worst_case_return_pct:   float
    worst_case_drawdown_pct: float
    best_case_return_pct:    float

    # Survival probability (not ruined)
    survival_probability: float

    # Warnings
    warnings:     list[str] = field(default_factory=list)
    generated_at: str       = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )

    def to_dict(self) -> dict:
        def _r(v, n=4):
            return round(v, n) if v is not None else None

        return {
            "symbol":   self.symbol,
            "window":   self.window,
            "method":   self.method,
            "n_sims":   self.n_sims,
            "n_trades": self.n_trades,
            "distribution": {
                "returns": {
                    "p5":  _r(self.return_p5),
                    "p25": _r(self.return_p25),
                    "p50": _r(self.return_p50),
                    "p75": _r(self.return_p75),
                    "p95": _r(self.return_p95),
                },
                "max_drawdowns": {
                    "p5":  _r(self.max_dd_p5),
                    "p25": _r(self.max_dd_p25),
                    "p50": _r(self.max_dd_p50),
                    "p75": _r(self.max_dd_p75),
                    "p95": _r(self.max_dd_p95),
                },
            },
            "tail_risk": {
                "var_pct":                _r(self.var_pct),
                "expected_shortfall_pct": _r(self.expected_shortfall_pct),
                "capital_at_risk_pct":    _r(self.capital_at_risk_pct),
            },
            "ruin": {
                "probability":     _r(self.probability_of_ruin),
                "threshold_pct":   self.ruin_threshold_pct,
                "survival_probability": _r(self.survival_probability),
            },
            "recovery": {
                "median_trades": _r(self.median_recovery_trades, 1),
                "p95_trades":    _r(self.p95_recovery_trades,    1),
            },
            "extremes": {
                "worst_return_pct":   _r(self.worst_case_return_pct),
                "worst_drawdown_pct": _r(self.worst_case_drawdown_pct),
                "best_return_pct":    _r(self.best_case_return_pct),
            },
            "warnings":     self.warnings,
            "generated_at": self.generated_at,
        }


@dataclass
class StressScenarioResult:
    """Results of a single stress scenario compared against baseline."""
    scenario:    str
    description: str
    n_trades:    int   # trades available in this scenario (may differ if filtered)

    # Baseline (original unmodified pnl distribution)
    baseline_win_rate:       Optional[float]
    baseline_expectancy_pct: Optional[float]
    baseline_max_dd_p50:     Optional[float]
    baseline_ruin_prob:      float

    # Stressed results
    stressed_win_rate:       Optional[float]
    stressed_expectancy_pct: Optional[float]
    stressed_max_dd_p50:     Optional[float]
    stressed_ruin_prob:      float

    # Deltas (stressed - baseline, or relative % change for expectancy)
    win_rate_delta:       Optional[float]   # absolute change
    expectancy_delta_pct: Optional[float]   # relative % change in expectancy
    max_dd_delta:         Optional[float]   # absolute change in median max DD

    warnings: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        def _r(v, n=4):
            return round(v, n) if v is not None else None

        return {
            "scenario":    self.scenario,
            "description": self.description,
            "n_trades":    self.n_trades,
            "baseline": {
                "win_rate":       _r(self.baseline_win_rate),
                "expectancy_pct": _r(self.baseline_expectancy_pct),
                "max_dd_p50":     _r(self.baseline_max_dd_p50),
                "ruin_prob":      _r(self.baseline_ruin_prob),
            },
            "stressed": {
                "win_rate":       _r(self.stressed_win_rate),
                "expectancy_pct": _r(self.stressed_expectancy_pct),
                "max_dd_p50":     _r(self.stressed_max_dd_p50),
                "ruin_prob":      _r(self.stressed_ruin_prob),
            },
            "delta": {
                "win_rate_delta":       _r(self.win_rate_delta),
                "expectancy_delta_pct": _r(self.expectancy_delta_pct, 2),
                "max_dd_delta":         _r(self.max_dd_delta),
            },
            "warnings": self.warnings,
        }


# ---------------------------------------------------------------------------
# Pure math helpers
# ---------------------------------------------------------------------------

def _safe_mean(xs: list[float]) -> Optional[float]:
    return sum(xs) / len(xs) if xs else None


def _percentile(sorted_vals: list[float], level: float) -> float:
    """Linear interpolation percentile (level in [0, 100])."""
    n = len(sorted_vals)
    if n == 0:
        return 0.0
    if n == 1:
        return sorted_vals[0]
    idx  = (level / 100.0) * (n - 1)
    lo   = int(idx)
    hi   = min(lo + 1, n - 1)
    frac = idx - lo
    return sorted_vals[lo] + frac * (sorted_vals[hi] - sorted_vals[lo])


def _percentiles(values: list[float], levels: list[int]) -> dict[int, float]:
    """Compute multiple percentiles efficiently from unsorted values."""
    sv = sorted(values)
    return {lv: _percentile(sv, lv) for lv in levels}


def _expected_shortfall(returns: list[float], threshold_pct: float = 5.0) -> float:
    """
    CVaR / Expected Shortfall: mean of the worst threshold_pct% of returns.
    Uses a full-population count in the tail so it converges with small samples.
    """
    if not returns:
        return 0.0
    sv     = sorted(returns)
    n_tail = max(1, math.ceil(len(sv) * threshold_pct / 100.0))
    return sum(sv[:n_tail]) / n_tail


# ---------------------------------------------------------------------------
# Single-path simulation
# ---------------------------------------------------------------------------

def _run_single_path(
    pnls:               list[float],
    initial_capital:    float,
    position_size_pct:  float,
    ruin_threshold_pct: float,
) -> SinglePathResult:
    """
    Simulate one equity path by applying each pnl in sequence.

    Uses the same proportional compounding formula as the portfolio engine:
        equity += equity × (position_size_pct / 100) × (pnl / 100)

    Halts immediately on ruin.  Tracks peak-to-peak recovery durations.
    """
    equity     = initial_capital
    peak       = initial_capital
    peak_idx   = 0
    ruin_level = initial_capital * (1.0 - ruin_threshold_pct / 100.0)
    max_dd     = 0.0
    ruined     = False
    in_dd      = False
    recovery_durations: list[int] = []

    for i, pnl in enumerate(pnls):
        equity += equity * (position_size_pct / 100.0) * (pnl / 100.0)

        if equity >= peak:
            if in_dd:
                recovery_durations.append(i - peak_idx)
                in_dd = False
            peak     = equity
            peak_idx = i
        else:
            in_dd = True
            if peak > 0:
                dd = (peak - equity) / peak * 100.0
                if dd > max_dd:
                    max_dd = dd

        if equity <= ruin_level:
            ruined = True
            break

    total_return = (equity - initial_capital) / initial_capital * 100.0

    return SinglePathResult(
        final_equity       = equity,
        total_return_pct   = round(total_return, 4),
        max_drawdown_pct   = round(max_dd,       4),
        ruined             = ruined,
        recovery_durations = recovery_durations,
    )


# ---------------------------------------------------------------------------
# Resampling methods
# ---------------------------------------------------------------------------

def _resample_bootstrap(pnls: list[float], rng: random.Random) -> list[float]:
    """IID sample with replacement — independent and identically distributed."""
    return rng.choices(pnls, k=len(pnls))


def _resample_random_order(pnls: list[float], rng: random.Random) -> list[float]:
    """Same set of trades, random sequence — pure sequence risk test."""
    result = list(pnls)
    rng.shuffle(result)
    return result


def _resample_block_bootstrap(
    pnls: list[float], block_size: int, rng: random.Random
) -> list[float]:
    """
    Sample consecutive blocks of length block_size with replacement.
    Preserves local autocorrelation (loss streaks, trending periods).
    """
    n = len(pnls)
    if n == 0:
        return []
    starts = list(range(n))   # every index is a valid block start
    result: list[float] = []
    while len(result) < n:
        s = rng.choice(starts)
        result.extend(pnls[s: s + block_size])
    return result[:n]


def _resample_regime_shuffle(
    pnls:    list[float],
    regimes: list[str],
    rng:     random.Random,
) -> list[float]:
    """
    Shuffle trade order within each regime bucket.
    Preserves regime composition and count; randomises within-regime sequence.
    If pnls and regimes have different lengths, falls back to random_order.
    """
    if len(pnls) != len(regimes):
        return _resample_random_order(pnls, rng)

    # Shuffle each regime bucket independently
    regime_pnls: dict[str, list[float]] = defaultdict(list)
    for p, r in zip(pnls, regimes):
        regime_pnls[r].append(p)
    for bucket in regime_pnls.values():
        rng.shuffle(bucket)

    # Reconstruct in original regime order
    counters: dict[str, int] = {r: 0 for r in regime_pnls}
    result: list[float] = []
    for r in regimes:
        result.append(regime_pnls[r][counters[r]])
        counters[r] += 1
    return result


def _resample(
    pnls:       list[float],
    regimes:    list[str],
    method:     str,
    block_size: int,
    rng:        random.Random,
) -> list[float]:
    """Dispatch to the appropriate resampling method."""
    if method == "bootstrap":
        return _resample_bootstrap(pnls, rng)
    if method == "random_order":
        return _resample_random_order(pnls, rng)
    if method == "block_bootstrap":
        return _resample_block_bootstrap(pnls, block_size, rng)
    if method == "regime_shuffle":
        return _resample_regime_shuffle(pnls, regimes, rng)
    return _resample_bootstrap(pnls, rng)   # safe fallback


# ---------------------------------------------------------------------------
# Stress scenario transformations
# ---------------------------------------------------------------------------

def _apply_vol_shock(pnls: list[float], vol_factor: float) -> list[float]:
    """
    Expand (or compress) the P&L distribution around its mean by vol_factor.
    Preserves the mean exactly; scales all deviations from the mean.
    vol_factor > 1 → wider tails; vol_factor < 1 → narrower distribution.
    """
    if not pnls:
        return []
    mean = sum(pnls) / len(pnls)
    return [mean + (p - mean) * vol_factor for p in pnls]


def _apply_slippage_expansion(
    pnls: list[float], additional_cost_pct: float
) -> list[float]:
    """
    Deduct additional_cost_pct from every trade's net P&L.
    Models increased transaction costs or wider bid-ask spreads.
    """
    return [p - additional_cost_pct for p in pnls]


def _apply_drawdown_clustering(pnls: list[float]) -> list[float]:
    """
    Front-load all losing trades, back-load all winning trades.
    Maximum possible sequence risk — the absolute worst ordering.
    Losses are sorted worst-first within the front block.
    Wins are sorted best-first within the back block.
    """
    losses = sorted([p for p in pnls if p <= 0.0])          # worst first
    gains  = sorted([p for p in pnls if p >  0.0], reverse=True)  # best first
    return losses + gains


def _apply_consecutive_losses(
    pnls: list[float], n_worst: int, rng: random.Random
) -> list[float]:
    """
    Front-load the N worst individual trades; shuffle the remainder randomly.
    Tests: what if the worst trades all cluster at the start?
    """
    n_worst = min(n_worst, len(pnls))
    sorted_by_pnl = sorted(range(len(pnls)), key=lambda i: pnls[i])
    worst_indices  = set(sorted_by_pnl[:n_worst])

    worst = [pnls[i] for i in range(len(pnls)) if i     in worst_indices]
    rest  = [pnls[i] for i in range(len(pnls)) if i not in worst_indices]
    rng.shuffle(rest)
    return worst + rest


def _apply_correlated_downside(pnls: list[float], shock_factor: float) -> list[float]:
    """
    Amplify all negative trade P&Ls by shock_factor.
    Models correlated position crashes (all shorts/longs move against you together).
    Positive P&Ls are unchanged.
    """
    return [p * shock_factor if p < 0.0 else p for p in pnls]


def _dominant_regime_pnls(
    pnls: list[float], regimes: list[str]
) -> list[float]:
    """
    Return only the P&L values from the single most common regime.
    Tests: what if you only traded one regime and it turned adverse?
    Falls back to all pnls if regimes list is empty.
    """
    if not regimes or len(pnls) != len(regimes):
        return pnls
    counter = Counter(regimes)
    dominant = counter.most_common(1)[0][0]
    return [p for p, r in zip(pnls, regimes) if r == dominant]


# ---------------------------------------------------------------------------
# Baseline statistics helper
# ---------------------------------------------------------------------------

def _compute_baseline_stats(
    pnls:        list[float],
    mc_params:   MonteCarloParams,
    rng:         random.Random,
    n_sims:      int = _DEFAULT_N_STRESS_SIMS,
) -> dict:
    """
    Compute baseline win rate, expectancy, and MC-derived max_dd_p50 / ruin_prob.
    """
    if not pnls:
        return {
            "win_rate":       None,
            "expectancy_pct": None,
            "max_dd_p50":     None,
            "ruin_prob":      0.0,
        }

    wins = [p for p in pnls if p > 0.0]
    win_rate  = len(wins) / len(pnls)
    expectancy = sum(pnls) / len(pnls)

    paths = [
        _run_single_path(
            rng.choices(pnls, k=len(pnls)),
            mc_params.initial_capital,
            mc_params.position_size_pct,
            mc_params.ruin_threshold_pct,
        )
        for _ in range(n_sims)
    ]
    dds    = sorted(p.max_drawdown_pct for p in paths)
    ruined = sum(1 for p in paths if p.ruined)

    return {
        "win_rate":       round(win_rate,   4),
        "expectancy_pct": round(expectancy, 4),
        "max_dd_p50":     round(_percentile(dds, 50.0), 4),
        "ruin_prob":      round(ruined / n_sims,        4),
    }


def _run_stressed_scenario_stats(
    stressed_pnls: list[float],
    mc_params:     MonteCarloParams,
    rng:           random.Random,
    n_sims:        int = _DEFAULT_N_STRESS_SIMS,
) -> dict:
    """Same as _compute_baseline_stats but on a stressed pnl set."""
    return _compute_baseline_stats(stressed_pnls, mc_params, rng, n_sims)


# ---------------------------------------------------------------------------
# Warning generators
# ---------------------------------------------------------------------------

def _generate_mc_warnings(
    summary: MonteCarloSummary,
    params:  MonteCarloParams,
) -> list[str]:
    """Generate robustness warnings from simulation results."""
    warnings: list[str] = []

    if params.n_simulations < _MIN_SIMS_WARNING:
        warnings.append(
            f"insufficient_simulations: only {params.n_simulations} paths — "
            f"statistics unreliable below {_MIN_SIMS_WARNING}; "
            f"use n_simulations >= {_MIN_SIMS_WARNING}"
        )

    if summary.return_p25 < _FRAGILE_P25_RETURN:
        warnings.append(
            f"fragile_expectancy: 25th-percentile path return is "
            f"{summary.return_p25:.2f}% — bottom quartile outcomes are losses; "
            f"the edge is not robust to resampling"
        )

    if summary.max_dd_p95 > _HIGH_TAIL_DD_PCT:
        warnings.append(
            f"high_tail_risk_drawdown: 95th-percentile max drawdown is "
            f"{summary.max_dd_p95:.1f}% — worst-case paths exceed "
            f"the {_HIGH_TAIL_DD_PCT:.0f}% danger threshold"
        )

    if summary.expected_shortfall_pct < _HIGH_ES_LOSS_PCT:
        warnings.append(
            f"high_tail_risk_shortfall: expected shortfall (CVaR) is "
            f"{summary.expected_shortfall_pct:.2f}% — average of worst-5%% "
            f"paths loses more than {abs(_HIGH_ES_LOSS_PCT):.0f}%"
        )

    if summary.probability_of_ruin > _HIGH_RUIN_PCT / 100.0:
        warnings.append(
            f"high_ruin_probability: {summary.probability_of_ruin:.1%} of paths "
            f"hit the {summary.ruin_threshold_pct:.0f}% ruin threshold — "
            f"probability of ruin exceeds {_HIGH_RUIN_PCT:.0f}%"
        )

    if (
        summary.median_recovery_trades is not None
        and summary.median_recovery_trades > _POOR_RECOVERY_TRADES
    ):
        warnings.append(
            f"poor_recovery_profile: median drawdown recovery takes "
            f"{summary.median_recovery_trades:.0f} trades — a long recovery "
            f"period increases ruin risk from a new adverse sequence"
        )

    return warnings


def _generate_stress_warnings(
    result:  StressScenarioResult,
    params:  MonteCarloParams,
) -> list[str]:
    """Warnings for a single stress scenario result."""
    warnings: list[str] = []

    if result.stressed_expectancy_pct is not None and result.stressed_expectancy_pct < 0:
        warnings.append(
            f"negative_expectancy_under_stress: '{result.scenario}' stress "
            f"produces negative expectancy ({result.stressed_expectancy_pct:.3f}%)"
        )

    if result.stressed_ruin_prob > _HIGH_RUIN_PCT / 100.0:
        warnings.append(
            f"high_ruin_under_stress: '{result.scenario}' raises ruin probability "
            f"to {result.stressed_ruin_prob:.1%}"
        )

    if (
        result.expectancy_delta_pct is not None
        and abs(result.expectancy_delta_pct) > _REGIME_SENSITIVITY * 100
    ):
        warnings.append(
            f"excessive_regime_sensitivity: '{result.scenario}' changes expectancy "
            f"by {result.expectancy_delta_pct:.1f}% — strategy is highly sensitive "
            f"to this condition"
        )

    return warnings


# ---------------------------------------------------------------------------
# Core aggregate computation
# ---------------------------------------------------------------------------

def _aggregate_paths(
    path_results: list[SinglePathResult],
    params:       MonteCarloParams,
    symbol:       str,
    window:       str,
    n_trades:     int,
) -> MonteCarloSummary:
    """Build a MonteCarloSummary from a list of SinglePathResult objects."""
    returns = [r.total_return_pct   for r in path_results]
    dds     = [r.max_drawdown_pct   for r in path_results]
    ruined  = [r.ruined             for r in path_results]

    # Flatten all recovery durations across paths
    all_recoveries = [d for r in path_results for d in r.recovery_durations]

    n = len(returns)

    ret_p  = _percentiles(returns, [5, 25, 50, 75, 95])
    dd_p   = _percentiles(dds,     [5, 25, 50, 75, 95])

    var_pct = ret_p[5]                            # 5th pct return = VaR
    es_pct  = _expected_shortfall(returns, 5.0)   # CVaR

    ruin_prob    = sum(ruined) / n if n > 0 else 0.0
    survival     = 1.0 - ruin_prob

    sorted_rec   = sorted(all_recoveries)
    med_recovery = _percentile(sorted_rec, 50.0) if sorted_rec else None
    p95_recovery = _percentile(sorted_rec, 95.0) if sorted_rec else None

    summary = MonteCarloSummary(
        symbol   = symbol,
        window   = window,
        method   = params.method,
        n_sims   = n,
        n_trades = n_trades,

        return_p5  = ret_p[5],
        return_p25 = ret_p[25],
        return_p50 = ret_p[50],
        return_p75 = ret_p[75],
        return_p95 = ret_p[95],

        max_dd_p5  = dd_p[5],
        max_dd_p25 = dd_p[25],
        max_dd_p50 = dd_p[50],
        max_dd_p75 = dd_p[75],
        max_dd_p95 = dd_p[95],

        var_pct                = var_pct,
        expected_shortfall_pct = es_pct,
        capital_at_risk_pct    = abs(min(var_pct, 0.0)),

        probability_of_ruin  = round(ruin_prob,   4),
        ruin_threshold_pct   = params.ruin_threshold_pct,
        survival_probability = round(survival,    4),

        median_recovery_trades = round(med_recovery, 1) if med_recovery is not None else None,
        p95_recovery_trades    = round(p95_recovery, 1) if p95_recovery is not None else None,

        worst_case_return_pct   = min(returns) if returns else 0.0,
        worst_case_drawdown_pct = max(dds)     if dds     else 0.0,
        best_case_return_pct    = max(returns) if returns else 0.0,
    )

    summary.warnings = _generate_mc_warnings(summary, params)
    return summary


# ---------------------------------------------------------------------------
# Stress test orchestration
# ---------------------------------------------------------------------------

_STRESS_SCENARIO_DEFS: list[dict] = [
    {
        "name":        "consecutive_losses",
        "description": "Worst 10 trades front-loaded (maximum sequence risk)",
        "apply":       lambda pnls, regimes, rng: _apply_consecutive_losses(pnls, 10, rng),
    },
    {
        "name":        "vol_shock_1_5x",
        "description": "P&L distribution stretched 1.5× around its mean (elevated vol regime)",
        "apply":       lambda pnls, regimes, rng: _apply_vol_shock(pnls, 1.5),
    },
    {
        "name":        "vol_shock_2x",
        "description": "P&L distribution doubled around its mean (extreme vol regime)",
        "apply":       lambda pnls, regimes, rng: _apply_vol_shock(pnls, 2.0),
    },
    {
        "name":        "slippage_3x",
        "description": "Round-trip transaction cost tripled (+0.20% per trade)",
        "apply":       lambda pnls, regimes, rng: _apply_slippage_expansion(pnls, 0.20),
    },
    {
        "name":        "drawdown_clustering",
        "description": "All losses sorted before all wins (worst-case ordering)",
        "apply":       lambda pnls, regimes, rng: _apply_drawdown_clustering(pnls),
    },
    {
        "name":        "correlated_downside",
        "description": "All losing trades amplified 1.5× (correlated crash simulation)",
        "apply":       lambda pnls, regimes, rng: _apply_correlated_downside(pnls, 1.5),
    },
    {
        "name":        "liquidity_deterioration",
        "description": "Slippage degrades to 0.5% per leg — adds 0.9% round-trip cost",
        "apply":       lambda pnls, regimes, rng: _apply_slippage_expansion(pnls, 0.90),
    },
    {
        "name":        "regime_concentration",
        "description": "Only dominant-regime trades survive (regime filter stress)",
        "apply":       lambda pnls, regimes, rng: _dominant_regime_pnls(pnls, regimes),
    },
]


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def extract_pnl_regimes(
    trades: list,   # list[SimulatedTrade]
) -> tuple[list[float], list[str]]:
    """
    Extract (net_pnl_pct, regime_label) from a list of SimulatedTrades.
    Excludes no_data trades (where net_pnl_pct is None).
    """
    pnls:    list[float] = []
    regimes: list[str]   = []

    for t in trades:
        if t.net_pnl_pct is None:           # type: ignore[attr-defined]
            continue
        pnls.append(t.net_pnl_pct)          # type: ignore[attr-defined]

        try:
            from app.services.regime_classifier import infer_static_regime
            regime = infer_static_regime(
                distance_pct   = t.signal_dist_pct,    # type: ignore[attr-defined]
                days_to_expiry = t.days_to_expiry,
                pcr            = t.pcr,
                avg_iv         = t.avg_iv,
                direction      = t.direction,
            )
        except Exception:
            regime = "unknown"

        regimes.append(regime)

    return pnls, regimes


def run_monte_carlo(
    trades:  list,              # list[SimulatedTrade]
    params:  MonteCarloParams,
    symbol:  str,
    window:  str,
) -> MonteCarloSummary:
    """
    Run a Monte Carlo simulation on the trade return series.

    Args:
        trades : SimulatedTrade list from trade_simulator.simulate_trades().
        params : MonteCarloParams controlling resampling and path simulation.
        symbol : NSE symbol (for labelling).
        window : Lookback window string (for labelling).

    Returns:
        MonteCarloSummary with distribution, tail risk, ruin, and recovery stats.

    Raises:
        ValueError if fewer than _MIN_TRADES_FOR_MC usable trades are present.
    """
    pnls, regimes = extract_pnl_regimes(trades)

    if len(pnls) < _MIN_TRADES_FOR_MC:
        raise ValueError(
            f"only {len(pnls)} usable trades (need >= {_MIN_TRADES_FOR_MC}); "
            f"widen the window or reduce min_distance_pct"
        )

    rng = random.Random(params.seed)

    path_results: list[SinglePathResult] = []
    for _ in range(params.n_simulations):
        sampled = _resample(pnls, regimes, params.method, params.block_size, rng)
        result  = _run_single_path(
            sampled,
            params.initial_capital,
            params.position_size_pct,
            params.ruin_threshold_pct,
        )
        path_results.append(result)

    logger.info(
        "run_monte_carlo: symbol=%s window=%s method=%s n_sims=%d n_trades=%d "
        "ruin_prob=%.2f%%",
        symbol, window, params.method, params.n_simulations, len(pnls),
        sum(1 for r in path_results if r.ruined) / len(path_results) * 100,
    )

    return _aggregate_paths(path_results, params, symbol, window, len(pnls))


def run_stress_tests(
    trades:    list,              # list[SimulatedTrade]
    mc_params: MonteCarloParams,
    symbol:    str,
    window:    str,
) -> list[StressScenarioResult]:
    """
    Run all predefined stress scenarios and return comparison results.

    Each scenario modifies the pnl series, then runs a light Monte Carlo
    (up to 500 paths) to estimate ruin probability and drawdown distribution.
    Baseline statistics are computed once and shared.

    Args:
        trades    : SimulatedTrade list.
        mc_params : Parameters (initial_capital, position_size_pct, ruin_threshold_pct).
        symbol    : NSE symbol (for logging).
        window    : Lookback window string.

    Returns:
        List of StressScenarioResult objects, one per scenario.
    """
    pnls, regimes = extract_pnl_regimes(trades)

    if not pnls:
        return []

    # Use a seeded RNG for reproducibility (same seed across all scenarios for fair comparison)
    rng = random.Random(mc_params.seed if mc_params.seed is not None else 42)

    n_stress_sims = min(mc_params.n_simulations, _DEFAULT_N_STRESS_SIMS)

    # Compute baseline once
    baseline = _compute_baseline_stats(pnls, mc_params, rng, n_stress_sims)

    results: list[StressScenarioResult] = []

    for defn in _STRESS_SCENARIO_DEFS:
        name  = defn["name"]
        desc  = defn["description"]
        apply = defn["apply"]

        try:
            stressed_pnls = apply(pnls, regimes, rng)
        except Exception as exc:
            logger.warning("stress scenario '%s' apply failed: %s", name, exc)
            stressed_pnls = pnls   # safe fallback: use original

        if not stressed_pnls:
            # e.g. regime_concentration on single-regime dataset
            stressed_pnls = pnls

        stressed = _run_stressed_scenario_stats(stressed_pnls, mc_params, rng, n_stress_sims)

        # Deltas
        b_exp = baseline["expectancy_pct"]
        s_exp = stressed["expectancy_pct"]
        b_wr  = baseline["win_rate"]
        s_wr  = stressed["win_rate"]
        b_dd  = baseline["max_dd_p50"]
        s_dd  = stressed["max_dd_p50"]

        exp_delta_pct = None
        if b_exp is not None and s_exp is not None and abs(b_exp) > 1e-9:
            exp_delta_pct = round((s_exp - b_exp) / abs(b_exp) * 100.0, 2)

        wr_delta  = round(s_wr - b_wr,   4) if (s_wr  is not None and b_wr  is not None) else None
        dd_delta  = round(s_dd - b_dd,   4) if (s_dd  is not None and b_dd  is not None) else None

        sr = StressScenarioResult(
            scenario    = name,
            description = desc,
            n_trades    = len(stressed_pnls),

            baseline_win_rate       = b_wr,
            baseline_expectancy_pct = b_exp,
            baseline_max_dd_p50     = b_dd,
            baseline_ruin_prob      = baseline["ruin_prob"],

            stressed_win_rate       = s_wr,
            stressed_expectancy_pct = s_exp,
            stressed_max_dd_p50     = s_dd,
            stressed_ruin_prob      = stressed["ruin_prob"],

            win_rate_delta       = wr_delta,
            expectancy_delta_pct = exp_delta_pct,
            max_dd_delta         = dd_delta,
        )
        sr.warnings = _generate_stress_warnings(sr, mc_params)
        results.append(sr)

        logger.debug(
            "stress '%s': n=%d exp=%.3f ruin=%.2f%%",
            name, len(stressed_pnls), s_exp or 0.0, (stressed["ruin_prob"] or 0.0) * 100,
        )

    return results
