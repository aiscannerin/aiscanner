"""
Trade Simulation Engine
=======================
Simulates realistic trade outcomes from validated max pain signals
using the forward return data produced by max_pain_replay_service.

Design principles
-----------------
No survivorship bias
    ALL signals are counted in the denominator.  Signals without
    forward price data are recorded as 'no_data' and excluded from
    P&L statistics but included in sample size totals.

Discrete price checks
    Exits are verified at the four available horizon prices
    (15m, 1h, 4h, 1d).  Intrabar stop/target touches are NOT
    modeled — this is a documented limitation emitted as a warning.
    We check prices in temporal order and exit at the first horizon
    where a condition is met.

Conservative stop fills
    When a stop or target is triggered we assume the fill is at the
    stop/target level exactly.  Gap-through risk (filling worse than
    the stop) is not modeled and is flagged in warnings.

Fixed-cost friction
    Total round-trip cost = 2 × slippage_pct + transaction_cost_pct.
    Slippage is applied symmetrically on entry and exit.

MAE / MFE estimation
    True intraday MAE/MFE requires tick data.  Here we use the
    minimum/maximum of the available horizon prices up to and
    including the exit horizon as an approximation.

Trade types
-----------
mean_reversion
    Trade toward max pain — the natural max pain signal.
    Bullish signal (spot < max_pain) → LONG.
    Bearish signal (spot > max_pain) → SHORT.
    Target = max_pain (or fixed target_pct if supplied).

continuation
    Trade AWAY from max pain — a momentum bet.
    Bullish signal → SHORT (spot continues to fall).
    Bearish signal → LONG (spot continues to rise).
    Requires an explicit target_pct; defaults to the signal's
    own distance_pct if omitted.

long / short
    Directional overrides — always enter the specified side
    regardless of signal direction.

Exit conditions (checked in temporal order)
-------------------------------------------
1. target_hit  — future_spot crosses the target level
2. stop_hit    — future_spot crosses the stop level
3. time_stop   — exit at holding_horizon future_spot (no hit)
4. no_data     — no forward price data at holding_horizon

Public API
----------
    simulate_trades(symbol, window, params, ...)  -> list[SimulatedTrade]
    compute_expectancy(symbol, window, params, ...) -> ExpectancyReport
    build_expectancy_report(trades, params, symbol, window) -> ExpectancyReport
"""

from __future__ import annotations

import logging
import math
import statistics
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Optional

from app.services.max_pain_replay_service import (
    ReplayPoint,
    load_replay,
    HORIZONS,
)

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

#: Horizons in temporal order — used for sequential exit checking.
HORIZONS_ORDERED: list[str] = ["15m", "1h", "4h", "1d"]

#: Valid trade types.
VALID_TRADE_TYPES = {"mean_reversion", "continuation", "long", "short"}

#: Warning thresholds.
_MIN_SAMPLE_WARN    = 30    # below this → insufficient_sample warning
_UNSTABLE_RATIO     = 3.0   # std / |expectancy| above this → unstable_expectancy
_HIGH_NO_DATA_RATE  = 0.30  # > 30% no-data → high_no_data_rate warning
_MIN_STOP_PCT       = 0.10  # below this → unrealistic_stop warning
_MIN_TARGET_PCT     = 0.10  # below this → unrealistic_target warning


# ---------------------------------------------------------------------------
# Parameter type
# ---------------------------------------------------------------------------

@dataclass
class TradeParams:
    """
    Configurable parameters for a single simulation run.

    Attributes
    ----------
    trade_type
        "mean_reversion" | "continuation" | "long" | "short"
    stop_pct
        Stop distance as % of entry price (always positive).
        Default 1.0 %.
    target_pct
        Fixed target distance as % of entry price.
        None → use max_pain as natural target (mean_reversion only).
    holding_horizon
        Time horizon for time-stop: "15m" | "1h" | "4h" | "1d".
    slippage_pct
        One-way slippage per leg (entry + exit).  Default 0.05 %.
    transaction_cost_pct
        Round-trip brokerage / STT etc.  Default 0.05 %.
    min_distance_pct
        Minimum signal distance % to consider as a tradeable signal.
    """
    trade_type:           str            = "mean_reversion"
    stop_pct:             float          = 1.0
    target_pct:           Optional[float] = None
    holding_horizon:      str            = "1d"
    slippage_pct:         float          = 0.05
    transaction_cost_pct: float          = 0.05
    min_distance_pct:     float          = 1.0

    def validate(self) -> list[str]:
        """Return a list of validation issues (empty = valid)."""
        issues: list[str] = []
        if self.trade_type not in VALID_TRADE_TYPES:
            issues.append(
                f"invalid trade_type '{self.trade_type}'; "
                f"valid: {sorted(VALID_TRADE_TYPES)}"
            )
        if self.stop_pct <= 0:
            issues.append("stop_pct must be positive")
        if self.target_pct is not None and self.target_pct <= 0:
            issues.append("target_pct must be positive when provided")
        if self.holding_horizon not in HORIZONS:
            issues.append(
                f"holding_horizon '{self.holding_horizon}' is not valid; "
                f"choose from {list(HORIZONS.keys())}"
            )
        if self.slippage_pct < 0:
            issues.append("slippage_pct cannot be negative")
        if self.transaction_cost_pct < 0:
            issues.append("transaction_cost_pct cannot be negative")
        return issues

    def to_dict(self) -> dict:
        return {
            "trade_type":           self.trade_type,
            "stop_pct":             self.stop_pct,
            "target_pct":           self.target_pct,
            "holding_horizon":      self.holding_horizon,
            "slippage_pct":         self.slippage_pct,
            "transaction_cost_pct": self.transaction_cost_pct,
            "min_distance_pct":     self.min_distance_pct,
        }

    @property
    def round_trip_cost(self) -> float:
        """Total round-trip cost per trade (both slippage legs + commission)."""
        return 2.0 * self.slippage_pct + self.transaction_cost_pct


# ---------------------------------------------------------------------------
# Result types
# ---------------------------------------------------------------------------

@dataclass
class SimulatedTrade:
    """
    Outcome of one simulated trade from a single signal point.

    P&L values are in percentage terms (not monetary).
    None P&L fields indicate no forward data was available.
    """
    # ── Signal identity ───────────────────────────────────────────────────────
    snapshot_id:      str
    symbol:           str
    captured_at:      str
    signal_spot:      float
    max_pain:         float
    signal_dist_pct:  float
    direction:        str    # "bullish" | "bearish"
    days_to_expiry:   int
    pcr:              float
    avg_iv:           Optional[float]

    # ── Trade setup ───────────────────────────────────────────────────────────
    trade_type:  str
    side:        str    # "long" | "short"
    entry_price: float
    target_price: float
    stop_price:   float

    # ── Exit ─────────────────────────────────────────────────────────────────
    exit_price:   Optional[float]
    exit_horizon: Optional[str]
    exit_reason:  str    # "target" | "stop" | "time_stop" | "no_data"

    # ── P&L (% of entry, after costs) ────────────────────────────────────────
    gross_pnl_pct: Optional[float]   # before slippage/commission
    net_pnl_pct:   Optional[float]   # after full round-trip cost
    is_win:        Optional[bool]    # net_pnl_pct > 0

    # ── Risk metrics ─────────────────────────────────────────────────────────
    mae_pct: Optional[float]   # max adverse excursion (positive = loss magnitude)
    mfe_pct: Optional[float]   # max favorable excursion (positive = gain magnitude)

    def to_dict(self) -> dict:
        return {
            "snapshot_id":     self.snapshot_id,
            "symbol":          self.symbol,
            "captured_at":     self.captured_at,
            "signal_spot":     self.signal_spot,
            "max_pain":        self.max_pain,
            "signal_dist_pct": self.signal_dist_pct,
            "direction":       self.direction,
            "days_to_expiry":  self.days_to_expiry,
            "pcr":             self.pcr,
            "avg_iv":          self.avg_iv,
            "trade_type":      self.trade_type,
            "side":            self.side,
            "entry_price":     self.entry_price,
            "target_price":    self.target_price,
            "stop_price":      self.stop_price,
            "exit_price":      self.exit_price,
            "exit_horizon":    self.exit_horizon,
            "exit_reason":     self.exit_reason,
            "gross_pnl_pct":   self.gross_pnl_pct,
            "net_pnl_pct":     self.net_pnl_pct,
            "is_win":          self.is_win,
            "mae_pct":         self.mae_pct,
            "mfe_pct":         self.mfe_pct,
        }


@dataclass
class ExpectancyReport:
    """
    Aggregate expectancy statistics for a simulation run.

    All P&L values are in percentage terms.
    None values indicate insufficient data for computation.
    """
    # ── Identity ──────────────────────────────────────────────────────────────
    symbol:     str
    window:     str
    params:     dict

    # ── Sample sizes ─────────────────────────────────────────────────────────
    total_signals: int    # all replay points (including no_data)
    simulated:     int    # had at least holding_horizon data
    wins:          int
    losses:        int
    no_data:       int    # no forward price data

    # ── Core metrics ─────────────────────────────────────────────────────────
    win_rate:       Optional[float]   # wins / simulated
    avg_win_pct:    Optional[float]   # mean net P&L of winning trades
    avg_loss_pct:   Optional[float]   # mean |net P&L| of losing trades (positive)
    payoff_ratio:   Optional[float]   # avg_win / avg_loss
    expectancy_pct: Optional[float]   # win_rate*avg_win - (1-win_rate)*avg_loss
    expectancy_r:   Optional[float]   # expectancy in units of avg_loss (R-multiples)
    profit_factor:  Optional[float]   # gross_wins / |gross_losses|

    # ── Dispersion ────────────────────────────────────────────────────────────
    std_pnl:      Optional[float]
    max_win_pct:  Optional[float]
    max_loss_pct: Optional[float]   # positive = magnitude of worst loss

    # ── Drawdown & excursion ─────────────────────────────────────────────────
    max_drawdown_pct: Optional[float]   # on equal-weighted cumulative P&L
    avg_mae_pct:      Optional[float]   # average max adverse excursion
    avg_mfe_pct:      Optional[float]   # average max favorable excursion

    # ── Position sizing guidance ─────────────────────────────────────────────
    kelly_fraction:    Optional[float]   # uncapped Kelly criterion (W - (1-W)/RR)
    recommended_kelly: Optional[float]   # fractional Kelly at 0.25× (safer)

    # ── Exit breakdown ───────────────────────────────────────────────────────
    exits_by_reason: dict[str, int]      # {"target": N, "stop": N, …}

    # ── Warnings ─────────────────────────────────────────────────────────────
    warnings: list[str] = field(default_factory=list)

    generated_at: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )

    def to_dict(self) -> dict:
        return {
            "symbol":           self.symbol,
            "window":           self.window,
            "params":           self.params,
            "sample": {
                "total_signals": self.total_signals,
                "simulated":     self.simulated,
                "wins":          self.wins,
                "losses":        self.losses,
                "no_data":       self.no_data,
            },
            "metrics": {
                "win_rate":        self.win_rate,
                "avg_win_pct":     self.avg_win_pct,
                "avg_loss_pct":    self.avg_loss_pct,
                "payoff_ratio":    self.payoff_ratio,
                "expectancy_pct":  self.expectancy_pct,
                "expectancy_r":    self.expectancy_r,
                "profit_factor":   self.profit_factor,
                "std_pnl":         self.std_pnl,
                "max_win_pct":     self.max_win_pct,
                "max_loss_pct":    self.max_loss_pct,
            },
            "risk": {
                "max_drawdown_pct": self.max_drawdown_pct,
                "avg_mae_pct":      self.avg_mae_pct,
                "avg_mfe_pct":      self.avg_mfe_pct,
            },
            "sizing": {
                "kelly_fraction":    self.kelly_fraction,
                "recommended_kelly": self.recommended_kelly,
            },
            "exits_by_reason": self.exits_by_reason,
            "warnings":        self.warnings,
            "generated_at":    self.generated_at,
        }


# ---------------------------------------------------------------------------
# Pure math helpers
# ---------------------------------------------------------------------------

def _safe_mean(xs: list[float]) -> Optional[float]:
    return sum(xs) / len(xs) if xs else None


def _safe_pstdev(xs: list[float]) -> Optional[float]:
    if len(xs) < 2:
        return None
    m = sum(xs) / len(xs)
    v = sum((x - m) ** 2 for x in xs) / len(xs)
    return math.sqrt(v)


def _max_drawdown(pnls: list[float]) -> float:
    """
    Maximum peak-to-trough drawdown on a cumulative equal-weighted P&L series.

    Assumes trades are in chronological order and each contributes
    equally to the running P&L (equal % position sizing).
    """
    if not pnls:
        return 0.0
    cum = 0.0
    peak = 0.0
    max_dd = 0.0
    for p in pnls:
        cum += p
        if cum > peak:
            peak = cum
        dd = peak - cum
        if dd > max_dd:
            max_dd = dd
    return round(max_dd, 4)


# ---------------------------------------------------------------------------
# Trade construction helpers
# ---------------------------------------------------------------------------

def _determine_side(direction: str, trade_type: str) -> str:
    """
    Map (signal direction, trade type) → 'long' or 'short'.

    mean_reversion: trade TOWARD max pain
        bullish (spot < max_pain) → long   (expect convergence upward)
        bearish (spot > max_pain) → short  (expect convergence downward)

    continuation: trade AWAY from max pain (momentum)
        bullish → short  (spot continues to diverge downward)
        bearish → long   (spot continues to diverge upward)

    long / short: always that side, regardless of signal
    """
    if trade_type == "long":
        return "long"
    if trade_type == "short":
        return "short"
    if trade_type == "continuation":
        return "short" if direction == "bullish" else "long"
    # default = mean_reversion
    return "long" if direction == "bullish" else "short"


def _entry_price(spot: float, side: str, slippage_pct: float) -> float:
    """Apply entry slippage to spot price."""
    if side == "long":
        return spot * (1.0 + slippage_pct / 100.0)
    return spot * (1.0 - slippage_pct / 100.0)


def _compute_target(
    side:             str,
    entry:            float,
    max_pain:         float,
    target_pct:       Optional[float],
    signal_dist_pct:  float,
    trade_type:       str,
) -> float:
    """
    Compute the trade target price.

    For mean_reversion without target_pct: target = max_pain (natural level).
    For mean_reversion with target_pct: target = entry ± target_pct%.
    For continuation / directional without target_pct: target = entry ±
      signal_dist_pct% (continuation of the same magnitude move).
    For continuation / directional with target_pct: entry ± target_pct%.
    """
    if trade_type == "mean_reversion" and target_pct is None:
        # Natural convergence target
        return max_pain

    # Fixed percentage target
    pct = target_pct if target_pct is not None else max(signal_dist_pct, 0.5)
    if side == "long":
        return entry * (1.0 + pct / 100.0)
    return entry * (1.0 - pct / 100.0)


def _compute_stop(side: str, entry: float, stop_pct: float) -> float:
    """Stop price at stop_pct% from entry."""
    if side == "long":
        return entry * (1.0 - stop_pct / 100.0)
    return entry * (1.0 + stop_pct / 100.0)


def _gross_pnl(side: str, entry: float, exit_px: float) -> float:
    """Gross P&L in %, before costs."""
    if entry <= 0:
        return 0.0
    if side == "long":
        return (exit_px - entry) / entry * 100.0
    return (entry - exit_px) / entry * 100.0


def _horizons_up_to(holding_horizon: str) -> list[str]:
    """Return horizons to check in temporal order, up to and including holding_horizon."""
    try:
        idx = HORIZONS_ORDERED.index(holding_horizon)
    except ValueError:
        return HORIZONS_ORDERED
    return HORIZONS_ORDERED[: idx + 1]


def _compute_mae_mfe(
    side: str,
    entry: float,
    horizon_prices: list[float],
) -> tuple[Optional[float], Optional[float]]:
    """
    Estimate MAE and MFE from a list of observed horizon prices.

    MAE (positive) = maximum loss observed at any horizon price.
    MFE (positive) = maximum gain observed at any horizon price.

    Both are expressed as % of entry. This is a lower-bound estimate —
    true intraday extremes require tick data.
    """
    if not horizon_prices or entry <= 0:
        return None, None

    pnls = [_gross_pnl(side, entry, p) for p in horizon_prices]
    mae = max(0.0, -min(pnls))     # worst loss (positive)
    mfe = max(0.0,  max(pnls))     # best gain  (positive)

    return round(mae, 4), round(mfe, 4)


# ---------------------------------------------------------------------------
# Core simulation logic
# ---------------------------------------------------------------------------

def _simulate_trade(point: ReplayPoint, params: TradeParams) -> SimulatedTrade:
    """
    Simulate one trade from a single ReplayPoint.

    Checks exit conditions at each horizon in temporal order up to
    holding_horizon.  If no condition is triggered, the trade exits
    at the holding_horizon price (time stop).  If no forward price
    data exists, records exit_reason='no_data'.
    """
    spot     = point.spot_price
    max_pain = point.max_pain

    side   = _determine_side(point.direction, params.trade_type)
    entry  = _entry_price(spot, side, params.slippage_pct)
    target = _compute_target(
        side, entry, max_pain,
        params.target_pct, point.distance_pct, params.trade_type,
    )
    stop = _compute_stop(side, entry, params.stop_pct)

    horizons_to_check = _horizons_up_to(params.holding_horizon)

    exit_price:    Optional[float] = None
    exit_horizon:  Optional[str]   = None
    exit_reason:   str             = "no_data"
    horizon_prices: list[float]    = []   # for MAE/MFE

    for h in horizons_to_check:
        outcome = point.outcomes.get(h)
        if outcome is None or outcome.future_spot is None:
            continue

        future = outcome.future_spot
        horizon_prices.append(future)

        # Check target hit
        if side == "long" and future >= target:
            exit_price   = target
            exit_horizon = h
            exit_reason  = "target"
            break
        if side == "short" and future <= target:
            exit_price   = target
            exit_horizon = h
            exit_reason  = "target"
            break

        # Check stop hit
        if side == "long" and future <= stop:
            exit_price   = stop
            exit_horizon = h
            exit_reason  = "stop"
            break
        if side == "short" and future >= stop:
            exit_price   = stop
            exit_horizon = h
            exit_reason  = "stop"
            break

    # Time stop: if no condition met, use holding_horizon future_spot
    if exit_reason == "no_data":
        holding_outcome = point.outcomes.get(params.holding_horizon)
        if holding_outcome and holding_outcome.future_spot is not None:
            exit_price   = holding_outcome.future_spot
            exit_horizon = params.holding_horizon
            exit_reason  = "time_stop"
            # Ensure holding_horizon price is in list for MAE/MFE
            if exit_price not in horizon_prices:
                horizon_prices.append(exit_price)

    # P&L computation
    gross_pnl: Optional[float] = None
    net_pnl:   Optional[float] = None
    is_win:    Optional[bool]  = None

    if exit_price is not None and entry > 0:
        gross_pnl = round(_gross_pnl(side, entry, exit_price), 4)
        net_pnl   = round(gross_pnl - params.round_trip_cost, 4)
        is_win    = net_pnl > 0

    mae, mfe = _compute_mae_mfe(side, entry, horizon_prices)

    return SimulatedTrade(
        snapshot_id      = point.snapshot_id,
        symbol           = point.symbol,
        captured_at      = point.captured_at,
        signal_spot      = round(spot, 2),
        max_pain         = round(max_pain, 2),
        signal_dist_pct  = round(point.distance_pct, 4),
        direction        = point.direction,
        days_to_expiry   = point.days_to_expiry,
        pcr              = round(point.pcr, 4),
        avg_iv           = round(point.avg_iv, 2) if point.avg_iv else None,
        trade_type       = params.trade_type,
        side             = side,
        entry_price      = round(entry, 2),
        target_price     = round(target, 2),
        stop_price       = round(stop, 2),
        exit_price       = round(exit_price, 2) if exit_price else None,
        exit_horizon     = exit_horizon,
        exit_reason      = exit_reason,
        gross_pnl_pct    = gross_pnl,
        net_pnl_pct      = net_pnl,
        is_win           = is_win,
        mae_pct          = mae,
        mfe_pct          = mfe,
    )


# ---------------------------------------------------------------------------
# Warning generators
# ---------------------------------------------------------------------------

def _generate_param_warnings(params: TradeParams) -> list[str]:
    """Emit warnings for unrealistic trade parameters."""
    warnings: list[str] = []

    if params.stop_pct < _MIN_STOP_PCT:
        warnings.append(
            f"unrealistic_stop: stop_pct={params.stop_pct}% is below {_MIN_STOP_PCT}% — "
            f"likely to be hit by normal market noise in Indian F&O markets"
        )
    if params.target_pct is not None and params.target_pct < _MIN_TARGET_PCT:
        warnings.append(
            f"unrealistic_target: target_pct={params.target_pct}% is below {_MIN_TARGET_PCT}%"
        )

    cost = params.round_trip_cost
    if params.target_pct is not None and params.target_pct <= cost:
        warnings.append(
            f"target_below_cost: target_pct={params.target_pct}% ≤ round_trip_cost={cost:.3f}% — "
            f"expected P&L is negative even on a winning trade"
        )

    if params.trade_type == "continuation" and params.target_pct is None:
        warnings.append(
            "continuation_default_target: no target_pct supplied for continuation trades — "
            "using signal distance_pct as target; consider supplying an explicit target"
        )

    warnings.append(
        "discrete_price_check: exit conditions are verified at 4 horizon closing prices only "
        "(15m / 1h / 4h / 1d). Intrabar touches of stop or target are not modeled."
    )
    warnings.append(
        "stop_fill_assumption: stop losses are assumed to fill exactly at the stop level. "
        "Gap-through risk (filling worse than the stop) is not modeled."
    )

    return warnings


def _generate_result_warnings(
    trades:    list[SimulatedTrade],
    report:    ExpectancyReport,
    params:    TradeParams,
) -> list[str]:
    """Emit warnings based on simulation results."""
    warnings: list[str] = []

    if report.simulated < _MIN_SAMPLE_WARN:
        warnings.append(
            f"insufficient_sample: only {report.simulated} simulated trades — "
            f"statistics are unreliable below {_MIN_SAMPLE_WARN}; "
            f"widen the window or reduce min_distance_pct"
        )

    if report.total_signals > 0:
        no_data_rate = report.no_data / report.total_signals
        if no_data_rate > _HIGH_NO_DATA_RATE:
            warnings.append(
                f"high_no_data_rate: {no_data_rate:.0%} of signals had no forward price "
                f"data at holding_horizon='{params.holding_horizon}' — "
                f"consider a shorter holding horizon"
            )

    if (
        report.expectancy_pct is not None
        and report.std_pnl is not None
        and abs(report.expectancy_pct) > 1e-6
        and report.std_pnl / abs(report.expectancy_pct) > _UNSTABLE_RATIO
    ):
        warnings.append(
            f"unstable_expectancy: std_pnl ({report.std_pnl:.3f}%) is "
            f"{report.std_pnl / abs(report.expectancy_pct):.1f}× the expectancy — "
            f"edge is small relative to variance; a large out-of-sample sample is required"
        )

    # Regime imbalance: check for extreme directional skew
    bullish_count = sum(1 for t in trades if t.direction == "bullish" and t.is_win is not None)
    bearish_count = sum(1 for t in trades if t.direction == "bearish" and t.is_win is not None)
    if report.simulated >= 10:
        skew = abs(bullish_count - bearish_count) / report.simulated
        if skew > 0.80:
            dominant = "bullish" if bullish_count > bearish_count else "bearish"
            warnings.append(
                f"regime_imbalance: {skew:.0%} of simulated trades are '{dominant}' signals — "
                f"statistics may not generalise across market regimes"
            )

    if report.expectancy_pct is not None and report.expectancy_pct < 0:
        warnings.append(
            f"negative_expectancy: mean net P&L is {report.expectancy_pct:.4f}% — "
            f"this parameter set has a negative edge on this dataset"
        )

    return warnings


# ---------------------------------------------------------------------------
# Expectancy computation
# ---------------------------------------------------------------------------

def build_expectancy_report(
    trades:  list[SimulatedTrade],
    params:  TradeParams,
    symbol:  str,
    window:  str,
) -> ExpectancyReport:
    """
    Aggregate SimulatedTrade results into an ExpectancyReport.

    Args:
        trades: All simulated trades (including no_data trades).
        params: The TradeParams used for this simulation run.
        symbol: NSE symbol.
        window: Lookback window string.

    Returns:
        ExpectancyReport with full statistics and warnings.
    """
    now = datetime.now(timezone.utc).isoformat()

    total      = len(trades)
    simulated  = [t for t in trades if t.is_win is not None]
    no_data_ct = sum(1 for t in trades if t.exit_reason == "no_data")
    wins       = [t for t in simulated if t.is_win]
    losses     = [t for t in simulated if not t.is_win]

    # Exit breakdown
    exits_by_reason: dict[str, int] = {}
    for t in trades:
        exits_by_reason[t.exit_reason] = exits_by_reason.get(t.exit_reason, 0) + 1

    # Core P&L lists
    win_pnls  = [t.net_pnl_pct for t in wins  if t.net_pnl_pct is not None]
    loss_pnls = [t.net_pnl_pct for t in losses if t.net_pnl_pct is not None]
    all_pnls  = [t.net_pnl_pct for t in simulated if t.net_pnl_pct is not None]

    n_sim = len(simulated)

    # Rate and return metrics
    win_rate    = round(len(wins) / n_sim, 4)   if n_sim else None
    avg_win     = _safe_mean(win_pnls)
    avg_loss_raw = _safe_mean(loss_pnls)         # negative number
    avg_loss    = round(abs(avg_loss_raw), 4) if avg_loss_raw is not None else None

    avg_win_r   = round(avg_win,  4) if avg_win  is not None else None

    payoff = round(avg_win / avg_loss, 4) if (avg_win and avg_loss) else None

    # Expectancy — handle all-wins and all-losses edge cases
    expectancy_pct: Optional[float] = None
    if win_rate is not None and all_pnls:
        # Use mean of all net P&Ls directly; equivalent to the WR formula but
        # works even when one side (all wins or all losses) has no avg_win/avg_loss.
        expectancy_pct = round(_safe_mean(all_pnls), 4)

    # Expectancy in R-multiples (R = avg_loss)
    expectancy_r: Optional[float] = None
    if expectancy_pct is not None and avg_loss and avg_loss > 0:
        expectancy_r = round(expectancy_pct / avg_loss, 4)

    # Profit factor = gross wins / |gross losses|
    gross_wins  = sum(t.gross_pnl_pct for t in wins   if t.gross_pnl_pct is not None)
    gross_losses = abs(sum(t.gross_pnl_pct for t in losses if t.gross_pnl_pct is not None))
    profit_factor = round(gross_wins / gross_losses, 4) if gross_losses > 0 else None

    # Dispersion
    std_pnl  = _safe_pstdev(all_pnls)
    max_win  = round(max(win_pnls),  4) if win_pnls  else None
    max_loss = round(abs(min(loss_pnls)), 4) if loss_pnls else None

    # Drawdown (time-ordered)
    max_dd = _max_drawdown(all_pnls) if all_pnls else None

    # MAE / MFE
    maes = [t.mae_pct for t in simulated if t.mae_pct is not None]
    mfes = [t.mfe_pct for t in simulated if t.mfe_pct is not None]
    avg_mae = round(_safe_mean(maes), 4) if maes else None
    avg_mfe = round(_safe_mean(mfes), 4) if mfes else None

    # Kelly criterion  (uncapped — may be > 1 for extreme edges)
    # Kelly = W - (1-W)/RR
    kelly: Optional[float] = None
    rec_kelly: Optional[float] = None
    if win_rate is not None and payoff is not None and payoff > 0:
        kelly = round(win_rate - (1.0 - win_rate) / payoff, 4)
        # Recommend 0.25× Kelly for safety
        rec_kelly = round(max(0.0, kelly) * 0.25, 4)

    report = ExpectancyReport(
        symbol         = symbol,
        window         = window,
        params         = params.to_dict(),
        total_signals  = total,
        simulated      = n_sim,
        wins           = len(wins),
        losses         = len(losses),
        no_data        = no_data_ct,
        win_rate       = win_rate,
        avg_win_pct    = avg_win_r,
        avg_loss_pct   = avg_loss,
        payoff_ratio   = payoff,
        expectancy_pct = expectancy_pct,
        expectancy_r   = expectancy_r,
        profit_factor  = profit_factor,
        std_pnl        = round(std_pnl, 4) if std_pnl is not None else None,
        max_win_pct    = max_win,
        max_loss_pct   = max_loss,
        max_drawdown_pct = max_dd,
        avg_mae_pct    = avg_mae,
        avg_mfe_pct    = avg_mfe,
        kelly_fraction = kelly,
        recommended_kelly = rec_kelly,
        exits_by_reason  = exits_by_reason,
        generated_at   = now,
    )

    # Warnings: parameter-level first, then result-level
    report.warnings = _generate_param_warnings(params) + _generate_result_warnings(
        trades, report, params
    )

    return report


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def simulate_trades(
    symbol:           str,
    params:           TradeParams,
    window:           str           = "30d",
    expiry:           Optional[str] = None,
    regime_filter:    Optional[str] = None,
    expiry_proximity: Optional[str] = None,
    vol_state:        Optional[str] = None,
) -> list[SimulatedTrade]:
    """
    Load replay points and simulate one trade per signal.

    Args:
        symbol:           NSE symbol.
        params:           TradeParams controlling simulation behaviour.
        window:           Lookback window ("1d" | "7d" | "30d" | "90d" | …).
        expiry:           Optional — filter to specific expiry.
        regime_filter:    Optional — filter by _REGIMES key from validation service.
        expiry_proximity: "near" (DTE ≤ 5) | "far" | None.
        vol_state:        "high_iv" | "low_iv" | "normal_iv" | None.

    Returns:
        List of SimulatedTrade objects (all signals, including no_data),
        ordered by captured_at ascending.
    """
    from app.services.max_pain_validation_service import _apply_filters

    points = load_replay(
        symbol           = symbol.upper(),
        expiry           = expiry,
        window           = window,
        min_distance_pct = params.min_distance_pct,
    )

    # Apply optional regime / vol / expiry filters
    points, filter_warnings = _apply_filters(
        points, regime_filter, expiry_proximity, vol_state
    )
    if filter_warnings:
        logger.info(
            "simulate_trades: filter warnings for %s: %s", symbol, filter_warnings
        )

    trades = [_simulate_trade(p, params) for p in points]
    logger.info(
        "simulate_trades: symbol=%s window=%s signals=%d simulated=%d no_data=%d",
        symbol, window, len(points),
        sum(1 for t in trades if t.is_win is not None),
        sum(1 for t in trades if t.exit_reason == "no_data"),
    )
    return trades


def compute_expectancy(
    symbol:           str,
    params:           TradeParams,
    window:           str           = "30d",
    expiry:           Optional[str] = None,
    regime_filter:    Optional[str] = None,
    expiry_proximity: Optional[str] = None,
    vol_state:        Optional[str] = None,
) -> ExpectancyReport:
    """
    Simulate trades and return a full ExpectancyReport.

    This is the primary entry point for expectancy analysis.
    """
    trades = simulate_trades(
        symbol           = symbol,
        params           = params,
        window           = window,
        expiry           = expiry,
        regime_filter    = regime_filter,
        expiry_proximity = expiry_proximity,
        vol_state        = vol_state,
    )
    return build_expectancy_report(trades, params, symbol.upper(), window)


def compute_regime_breakdown(
    trades:    list[SimulatedTrade],
    params:    TradeParams,
    symbol:    str,
    window:    str,
) -> dict[str, dict]:
    """
    Break down expectancy by regime labels computed from trade features.

    Uses static single-point regime inference (no rolling window).
    Returns a dict mapping regime label → ExpectancyReport-like dict.
    """
    from app.services.regime_classifier import infer_static_regime

    buckets: dict[str, list[SimulatedTrade]] = {}

    for trade in trades:
        label = infer_static_regime(
            distance_pct    = trade.signal_dist_pct,
            days_to_expiry  = trade.days_to_expiry,
            pcr             = trade.pcr,
            avg_iv          = trade.avg_iv,
            direction       = trade.direction,
        )
        buckets.setdefault(label, []).append(trade)

    result: dict[str, dict] = {}
    for label, bucket in buckets.items():
        if len(bucket) < 5:  # too small to report
            continue
        rep = build_expectancy_report(bucket, params, symbol, window)
        result[label] = {
            "count":          len(bucket),
            "win_rate":       rep.win_rate,
            "expectancy_pct": rep.expectancy_pct,
            "payoff_ratio":   rep.payoff_ratio,
            "avg_mae_pct":    rep.avg_mae_pct,
            "warnings":       [w for w in rep.warnings if "discrete_price" not in w
                               and "stop_fill" not in w],
        }

    return result
