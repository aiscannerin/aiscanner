"""
Portfolio and Risk Management Engine
=====================================
Simulates portfolio-level capital deployment across a sequence of already-
simulated trades (produced by the trade simulator).  Applies position sizing,
risk controls, and computes portfolio-level performance metrics.

Design Principles
-----------------
Compounding
    Each trade sizes off CURRENT equity (after all closed P&Ls).  Reinvestment
    is implicit — a winner grows the base for subsequent sizing.

No Double-Counting
    Open positions are tracked but their unrealised P&L is NOT added to equity
    until the position closes.  This prevents phantom equity inflation during
    concurrent positions.

Conservative Sizing
    A trade is either entered at the computed size or SKIPPED entirely when a
    hard risk limit is breached.  There is no partial sizing.  The skip reason
    is always recorded.

Risk Controls Hierarchy (evaluated in order)
    1. Circuit breaker  – drawdown from peak ≥ threshold → halt ALL trading
    2. Daily loss limit – today's realised loss ≥ limit   → halt FOR THE DAY
    3. Concurrent limit – open positions ≥ limit           → skip this trade
    4. Correlated limit – same symbol open ≥ limit         → skip this trade
    5. Exposure budget  – total exposure ≥ limit           → skip this trade
    6. Regime limit     – regime exposure ≥ limit          → skip this trade

No-Data Trades
    Trades with exit_reason='no_data' are always skipped with skip_reason='no_data'.
    They are counted in total_signals but never contribute to P&L.

Costs and Slippage
    Already embedded in net_pnl_pct from the trade simulator.  The portfolio
    engine applies no additional friction.

Sizing Methods
--------------
fixed_fractional
    position_size_pct = min(risk_per_trade_pct / stop_pct, max_position_size_pct)
    Risks exactly risk_per_trade_pct% of current equity when stopped out.

volatility_adjusted
    Scales the fixed-fractional size by (target_vol_pct / realized_vol), where
    realized_vol is the population std-dev of the last vol_lookback_trades
    net_pnl_pct values.  Reduces size in high-vol regimes, increases (capped)
    in low-vol.  Falls back to fixed_fractional when fewer than 5 samples are
    available.

Metrics
-------
Sharpe ratio       : mean(equity_returns) / std(equity_returns) * √(trades_per_year)
Sortino ratio      : mean(equity_returns) / downside_dev(equity_returns) * √(trades_per_year)
Calmar ratio       : annualised_return / max_drawdown_pct
Recovery factor    : total_return_pct / max_drawdown_pct
Profit factor      : sum(gross_dollar_wins) / |sum(gross_dollar_losses)|
Expectancy/unit risk : expectancy_on_equity / avg_loss_on_equity

Public API
----------
    run_portfolio_simulation(trades, params, trade_params, symbols, window)
        -> tuple[list[PortfolioTrade], list[EquityCurvePoint]]

    compute_portfolio_metrics(trades, params, trade_params, symbols, window)
        -> PortfolioMetrics

    simulate_portfolio(symbols, params, trade_params, window, **filter_kwargs)
        -> tuple[list[PortfolioTrade], list[EquityCurvePoint], PortfolioMetrics]
"""

from __future__ import annotations

import logging
import math
import statistics
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone
from typing import Optional, TYPE_CHECKING

if TYPE_CHECKING:  # avoid circular import; runtime import done inside functions
    from app.services.trade_simulator import SimulatedTrade, TradeParams

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_HORIZON_DURATIONS: dict[str, timedelta] = {
    "15m": timedelta(minutes=15),
    "1h":  timedelta(hours=1),
    "4h":  timedelta(hours=4),
    "1d":  timedelta(days=1),
}

_ROLL_WINDOW_SIZE          = 20     # default rolling-window trade count
_MIN_TRADES_FOR_RATIOS     = 10     # minimum trades to compute Sharpe/Sortino
_MIN_CIRCUIT_BREAKER_PCT   = 5.0    # floor for circuit_breaker_drawdown_pct

# Warning thresholds
_OVERCONCENTRATION_PCT     = 60.0   # >60% capital in one regime
_EXCESSIVE_LEVERAGE_PCT    = 100.0  # peak exposure > 100% of equity
_HIGH_SKIP_RATE            = 0.40   # >40% signals skipped

VALID_SIZING_METHODS = {"fixed_fractional", "volatility_adjusted"}


# ---------------------------------------------------------------------------
# Parameter dataclass
# ---------------------------------------------------------------------------

@dataclass
class PortfolioParams:
    """
    Parameters controlling capital deployment, sizing, and risk controls.

    Attributes
    ----------
    sizing_method
        "fixed_fractional" | "volatility_adjusted"
    risk_per_trade_pct
        Percent of current equity to risk if the stop is hit.  Default 2%.
    max_position_size_pct
        Hard cap on a single position size as % of equity.  Default 20%.
    max_portfolio_exposure_pct
        Maximum total open exposure (sum of position sizes) as % of equity.
        Default 60%.
    concurrent_position_limit
        Maximum number of simultaneously open positions.  Default 5.
    max_correlated_positions
        Maximum open positions in the same symbol (correlation proxy).  Default 2.
    daily_loss_limit_pct
        If today's realised loss exceeds this % of day-start equity, halt for
        the day.  Default 5%.
    regime_exposure_limit_pct
        Maximum exposure in any single static regime (% of equity).  Default 40%.
    circuit_breaker_drawdown_pct
        Halt all trading permanently if drawdown from equity peak exceeds this %.
        Default 20%; minimum 5%.
    initial_capital
        Starting capital in ₹.  Default ₹10 lakh.
    target_vol_pct
        Target per-trade volatility for vol-adjusted sizing.  Default 1%.
    vol_lookback_trades
        Number of recent trades to estimate realised volatility.  Default 20.
    """
    sizing_method:              str   = "fixed_fractional"
    risk_per_trade_pct:         float = 2.0
    max_position_size_pct:      float = 20.0
    max_portfolio_exposure_pct: float = 60.0
    concurrent_position_limit:  int   = 5
    max_correlated_positions:   int   = 2
    daily_loss_limit_pct:       float = 5.0
    regime_exposure_limit_pct:  float = 40.0
    circuit_breaker_drawdown_pct: float = 20.0
    initial_capital:            float = 1_000_000.0
    target_vol_pct:             float = 1.0
    vol_lookback_trades:        int   = 20

    def validate(self) -> list[str]:
        """Return list of validation issues (empty = valid)."""
        issues: list[str] = []
        if self.sizing_method not in VALID_SIZING_METHODS:
            issues.append(
                f"invalid sizing_method '{self.sizing_method}'; "
                f"choose from {sorted(VALID_SIZING_METHODS)}"
            )
        if not (0 < self.risk_per_trade_pct <= 20):
            issues.append("risk_per_trade_pct must be in (0, 20]")
        if not (0 < self.max_position_size_pct <= 300):
            issues.append("max_position_size_pct must be in (0, 300]")
        if not (0 < self.max_portfolio_exposure_pct <= 500):
            issues.append("max_portfolio_exposure_pct must be in (0, 500]")
        if self.concurrent_position_limit < 1:
            issues.append("concurrent_position_limit must be >= 1")
        if self.max_correlated_positions < 1:
            issues.append("max_correlated_positions must be >= 1")
        if self.daily_loss_limit_pct <= 0:
            issues.append("daily_loss_limit_pct must be positive")
        if self.regime_exposure_limit_pct <= 0:
            issues.append("regime_exposure_limit_pct must be positive")
        if self.circuit_breaker_drawdown_pct < _MIN_CIRCUIT_BREAKER_PCT:
            issues.append(
                f"circuit_breaker_drawdown_pct must be >= {_MIN_CIRCUIT_BREAKER_PCT}%"
            )
        if self.initial_capital <= 0:
            issues.append("initial_capital must be positive")
        if self.target_vol_pct <= 0:
            issues.append("target_vol_pct must be positive")
        if self.vol_lookback_trades < 5:
            issues.append("vol_lookback_trades must be >= 5")
        return issues

    def to_dict(self) -> dict:
        return {
            "sizing_method":              self.sizing_method,
            "risk_per_trade_pct":         self.risk_per_trade_pct,
            "max_position_size_pct":      self.max_position_size_pct,
            "max_portfolio_exposure_pct": self.max_portfolio_exposure_pct,
            "concurrent_position_limit":  self.concurrent_position_limit,
            "max_correlated_positions":   self.max_correlated_positions,
            "daily_loss_limit_pct":       self.daily_loss_limit_pct,
            "regime_exposure_limit_pct":  self.regime_exposure_limit_pct,
            "circuit_breaker_drawdown_pct": self.circuit_breaker_drawdown_pct,
            "initial_capital":            self.initial_capital,
            "target_vol_pct":             self.target_vol_pct,
            "vol_lookback_trades":        self.vol_lookback_trades,
        }


# ---------------------------------------------------------------------------
# Result dataclasses
# ---------------------------------------------------------------------------

@dataclass
class PortfolioTrade:
    """
    A SimulatedTrade decorated with portfolio-level sizing and execution context.

    Both entered and skipped trades are represented.  For skipped trades,
    dollar_pnl and pnl_on_equity are None and skipped=True.
    """
    # Original trade (duck-typed to avoid circular import at module level)
    trade:             object            # SimulatedTrade
    entry_dt:          datetime
    exit_dt:           datetime
    regime:            str

    # Sizing & P&L
    position_size_pct: float             # % of equity at entry (0 if skipped)
    capital_at_entry:  float             # equity value at time of entry
    dollar_pnl:        Optional[float]   # None if skipped or no_data
    pnl_on_equity:     Optional[float]   # dollar_pnl / capital_at_entry * 100

    # Execution status
    skipped:     bool           = False
    skip_reason: Optional[str]  = None   # "no_data" | "circuit_breaker" | …

    def to_dict(self) -> dict:
        t = self.trade
        return {
            "snapshot_id":       t.snapshot_id,       # type: ignore[attr-defined]
            "symbol":            t.symbol,
            "captured_at":       t.captured_at,
            "exit_horizon":      t.exit_horizon,
            "exit_reason":       t.exit_reason,
            "direction":         t.direction,
            "side":              t.side,
            "regime":            self.regime,
            "entry_price":       t.entry_price,
            "exit_price":        t.exit_price,
            "signal_dist_pct":   t.signal_dist_pct,
            "net_pnl_pct":       t.net_pnl_pct,
            "position_size_pct": round(self.position_size_pct, 4),
            "capital_at_entry":  round(self.capital_at_entry, 2),
            "dollar_pnl":        round(self.dollar_pnl, 2)     if self.dollar_pnl     is not None else None,
            "pnl_on_equity":     round(self.pnl_on_equity, 6)  if self.pnl_on_equity  is not None else None,
            "skipped":           self.skipped,
            "skip_reason":       self.skip_reason,
        }


@dataclass
class EquityCurvePoint:
    """Single event on the equity curve — emitted at every trade open and close."""
    timestamp:           str
    equity:              float
    drawdown_pct:        float
    open_positions:      int
    exposure_pct:        float
    daily_pnl:           float
    event:               str             # "open" | "close"
    symbol:              Optional[str]   = None
    trade_pnl_on_equity: Optional[float] = None   # only set on "close" events

    def to_dict(self) -> dict:
        return {
            "timestamp":            self.timestamp,
            "equity":               round(self.equity, 2),
            "drawdown_pct":         round(self.drawdown_pct, 4),
            "open_positions":       self.open_positions,
            "exposure_pct":         round(self.exposure_pct, 4),
            "daily_pnl":            round(self.daily_pnl, 2),
            "event":                self.event,
            "symbol":               self.symbol,
            "trade_pnl_on_equity":  round(self.trade_pnl_on_equity, 6) if self.trade_pnl_on_equity is not None else None,
        }


@dataclass
class RollingMetrics:
    """Rolling performance metrics over the last N closed trades."""
    window_size:    int
    trade_index:    int              # index of the last trade in this window
    equity:         float
    win_rate:       Optional[float]
    expectancy_pct: Optional[float]  # avg pnl_on_equity in the window

    def to_dict(self) -> dict:
        return {
            "window_size":    self.window_size,
            "trade_index":    self.trade_index,
            "equity":         round(self.equity, 2),
            "win_rate":       round(self.win_rate, 4)       if self.win_rate       is not None else None,
            "expectancy_pct": round(self.expectancy_pct, 6) if self.expectancy_pct is not None else None,
        }


@dataclass
class PortfolioMetrics:
    """Aggregate portfolio-level performance metrics."""
    # Identity
    symbols:          list[str]
    window:           str
    trade_params:     dict
    portfolio_params: dict

    # Capital
    initial_capital:       float
    final_capital:         float
    total_return_pct:      float
    annualized_return_pct: Optional[float]

    # Risk-adjusted ratios
    sharpe_ratio:  Optional[float]
    sortino_ratio: Optional[float]
    calmar_ratio:  Optional[float]

    # Drawdown
    max_drawdown_pct:      float
    avg_drawdown_pct:      Optional[float]
    max_drawdown_duration: Optional[int]    # events from peak to trough
    recovery_factor:       Optional[float]

    # Trade statistics
    total_signals:   int
    total_entered:   int
    total_skipped:   int
    winning_trades:  int
    losing_trades:   int
    no_data_trades:  int
    win_rate:               Optional[float]
    profit_factor:          Optional[float]
    avg_win_on_equity:      Optional[float]   # % of equity
    avg_loss_on_equity:     Optional[float]   # % of equity (positive = magnitude)
    expectancy_on_equity:   Optional[float]   # mean pnl_on_equity per trade
    expectancy_per_unit_risk: Optional[float] # expectancy / avg_loss_on_equity

    # Exposure
    avg_position_size_pct:    Optional[float]
    peak_exposure_pct:        float
    avg_exposure_pct:         Optional[float]
    avg_concurrent_positions: Optional[float]

    # Regime
    regime_concentration: dict[str, float]         # regime → % of deployed capital
    regime_win_rates:     dict[str, Optional[float]]

    # Risk controls
    circuit_breaker_triggered:  bool
    daily_loss_limit_triggered: int   # count of days trading was halted

    # Warnings
    warnings:     list[str]
    generated_at: str

    def to_dict(self) -> dict:
        def _r(v, n=4):
            return round(v, n) if v is not None else None

        return {
            "symbols":          self.symbols,
            "window":           self.window,
            "trade_params":     self.trade_params,
            "portfolio_params": self.portfolio_params,
            "capital": {
                "initial":               self.initial_capital,
                "final":                 _r(self.final_capital, 2),
                "total_return_pct":      _r(self.total_return_pct),
                "annualized_return_pct": _r(self.annualized_return_pct),
            },
            "ratios": {
                "sharpe_ratio":  _r(self.sharpe_ratio),
                "sortino_ratio": _r(self.sortino_ratio),
                "calmar_ratio":  _r(self.calmar_ratio),
            },
            "drawdown": {
                "max_drawdown_pct":      _r(self.max_drawdown_pct),
                "avg_drawdown_pct":      _r(self.avg_drawdown_pct),
                "max_drawdown_duration": self.max_drawdown_duration,
                "recovery_factor":       _r(self.recovery_factor),
            },
            "trades": {
                "total_signals":          self.total_signals,
                "total_entered":          self.total_entered,
                "total_skipped":          self.total_skipped,
                "winning":                self.winning_trades,
                "losing":                 self.losing_trades,
                "no_data":                self.no_data_trades,
                "win_rate":               _r(self.win_rate),
                "profit_factor":          _r(self.profit_factor),
                "avg_win_on_equity":      _r(self.avg_win_on_equity, 6),
                "avg_loss_on_equity":     _r(self.avg_loss_on_equity, 6),
                "expectancy_on_equity":   _r(self.expectancy_on_equity, 6),
                "expectancy_per_unit_risk": _r(self.expectancy_per_unit_risk),
            },
            "exposure": {
                "avg_position_size_pct":    _r(self.avg_position_size_pct),
                "peak_exposure_pct":        _r(self.peak_exposure_pct),
                "avg_exposure_pct":         _r(self.avg_exposure_pct),
                "avg_concurrent_positions": _r(self.avg_concurrent_positions, 2),
            },
            "regime": {
                "concentration": {k: round(v, 4) for k, v in self.regime_concentration.items()},
                "win_rates":     {k: (_r(v) if v is not None else None) for k, v in self.regime_win_rates.items()},
            },
            "risk_controls": {
                "circuit_breaker_triggered":  self.circuit_breaker_triggered,
                "daily_loss_limit_triggered": self.daily_loss_limit_triggered,
            },
            "warnings":     self.warnings,
            "generated_at": self.generated_at,
        }


# ---------------------------------------------------------------------------
# Internal types
# ---------------------------------------------------------------------------

@dataclass
class _OpenPosition:
    """Tracks a single live position inside PortfolioSimulator."""
    pt:               PortfolioTrade
    symbol:           str
    regime:           str
    exit_dt:          datetime
    position_size_pct: float


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


def _sortino_downside_dev(returns: list[float], mar: float = 0.0) -> float:
    """
    Population downside deviation below MAR (minimum acceptable return).
    Uses all returns in the denominator count to match the standard formula.
    """
    n = len(returns)
    if n == 0:
        return 0.0
    sq_sum = sum(min(r - mar, 0.0) ** 2 for r in returns)
    return math.sqrt(sq_sum / n)


def _compute_drawdown_stats(equity_values: list[float]) -> tuple[float, int]:
    """
    Compute (max_drawdown_pct, max_drawdown_duration) from a sequence of
    equity values (ordered in time).

    max_drawdown_pct    : peak-to-trough as % of peak value.
    max_drawdown_duration : number of events from peak to worst trough.
    """
    if not equity_values:
        return 0.0, 0

    peak = equity_values[0]
    peak_idx = 0
    max_dd = 0.0
    max_dd_dur = 0

    for i, eq in enumerate(equity_values):
        if eq >= peak:
            peak = eq
            peak_idx = i
        else:
            if peak > 0:
                dd = (peak - eq) / peak * 100.0
                dur = i - peak_idx
                if dd > max_dd:
                    max_dd = dd
                    max_dd_dur = dur

    return round(max_dd, 4), max_dd_dur


def _infer_trade_regime(trade: object) -> str:
    """Static single-point regime inference from trade features."""
    try:
        from app.services.regime_classifier import infer_static_regime
        return infer_static_regime(
            distance_pct   = trade.signal_dist_pct,    # type: ignore[attr-defined]
            days_to_expiry = trade.days_to_expiry,
            pcr            = trade.pcr,
            avg_iv         = trade.avg_iv,
            direction      = trade.direction,
        )
    except Exception:
        return "unknown"


def _compute_rolling_windows(
    closed_trades: list[PortfolioTrade],
    window_size:   int = _ROLL_WINDOW_SIZE,
) -> list[RollingMetrics]:
    """Compute rolling performance metrics over a sliding window of closed trades."""
    results: list[RollingMetrics] = []
    n = len(closed_trades)
    if n < window_size:
        return results

    for end in range(window_size - 1, n):
        start  = end - window_size + 1
        window = closed_trades[start: end + 1]

        pnls = [pt.pnl_on_equity for pt in window if pt.pnl_on_equity is not None]
        wins = [p for p in pnls if p > 0]

        win_rate   = round(len(wins) / len(pnls), 4) if pnls else None
        expectancy = round(sum(pnls) / len(pnls), 6) if pnls else None

        # Approximate equity at end of window
        last   = closed_trades[end]
        equity = last.capital_at_entry + (last.dollar_pnl or 0.0)

        results.append(RollingMetrics(
            window_size    = window_size,
            trade_index    = end,
            equity         = equity,
            win_rate       = win_rate,
            expectancy_pct = expectancy,
        ))

    return results


# ---------------------------------------------------------------------------
# Core simulator
# ---------------------------------------------------------------------------

class PortfolioSimulator:
    """
    Stateful portfolio simulator.

    Usage:
        sim = PortfolioSimulator(portfolio_params, trade_params)
        all_trades, curve = sim.run(list_of_simulated_trades)
        metrics_dict = sim.get_metrics_data()
    """

    def __init__(self, p_params: PortfolioParams, t_params: object) -> None:
        self._pp = p_params
        self._tp = t_params            # TradeParams (duck-typed)

        # Equity state
        self._equity      = p_params.initial_capital
        self._peak_equity = p_params.initial_capital

        # Position tracking
        self._open:         list[_OpenPosition]   = []
        self._closed_pts:   list[PortfolioTrade]  = []  # entered (not skipped)
        self._skipped_pts:  list[PortfolioTrade]  = []

        # Equity curve
        self._curve: list[EquityCurvePoint] = []

        # Risk control state
        self._circuit_breaker: bool = False
        self._daily_pnl:       dict[date, float] = {}
        self._day_start_equity: dict[date, float] = {}
        self._daily_limit_days: set[date]         = set()

        # Exposure snapshots (at every open/close event — for avg_exposure)
        self._exposure_snapshots: list[float] = []

        # Volatility estimation buffer
        self._recent_pnls: list[float] = []

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _parse_dt(self, ts: str) -> datetime:
        """Parse ISO timestamp to tz-aware UTC datetime."""
        try:
            dt = datetime.fromisoformat(ts)
        except (ValueError, TypeError):
            return datetime.now(timezone.utc)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt

    def _drawdown_pct(self) -> float:
        if self._peak_equity <= 0:
            return 0.0
        return round((self._peak_equity - self._equity) / self._peak_equity * 100.0, 4)

    def _exposure_pct(self) -> float:
        """Sum of all open position sizes (% of equity)."""
        return sum(pos.position_size_pct for pos in self._open)

    def _regime_exposure_pct(self, regime: str) -> float:
        return sum(pos.position_size_pct for pos in self._open if pos.regime == regime)

    def _positions_in_symbol(self, symbol: str) -> int:
        return sum(1 for pos in self._open if pos.symbol == symbol)

    def _compute_size(self, stop_pct: float) -> float:
        """
        Compute position size as % of equity.

        fixed_fractional  : risk_per_trade / stop_pct, capped.
        volatility_adjusted: scaled by (target_vol / realized_vol).
        """
        pp = self._pp
        stop = max(stop_pct, 1e-6)
        base = pp.risk_per_trade_pct / stop

        if pp.sizing_method == "volatility_adjusted" and len(self._recent_pnls) >= 5:
            realised_vol = _safe_pstdev(self._recent_pnls)
            if realised_vol and realised_vol > 1e-6:
                base = base * (pp.target_vol_pct / realised_vol)

        return min(base, pp.max_position_size_pct)

    def _check_risk_controls(
        self, entry_dt: datetime, regime: str, symbol: str
    ) -> tuple[bool, Optional[str]]:
        """
        Evaluate risk controls in priority order.
        Returns (allowed, skip_reason).  skip_reason is None when allowed.
        """
        pp = self._pp

        # 1. Circuit breaker already triggered
        if self._circuit_breaker:
            return False, "circuit_breaker"

        # 2. Check if circuit breaker SHOULD trigger now
        if self._drawdown_pct() >= pp.circuit_breaker_drawdown_pct:
            self._circuit_breaker = True
            return False, "circuit_breaker"

        # 3. Daily loss limit
        today = entry_dt.date()
        if today not in self._day_start_equity:
            self._day_start_equity[today] = self._equity
        day_start = self._day_start_equity[today]
        daily_loss = -self._daily_pnl.get(today, 0.0)   # positive = loss
        if day_start > 0 and (daily_loss / day_start * 100.0) >= pp.daily_loss_limit_pct:
            self._daily_limit_days.add(today)
            return False, "daily_loss_limit"

        # 4. Concurrent position limit
        if len(self._open) >= pp.concurrent_position_limit:
            return False, "concurrent_limit"

        # 5. Correlated positions limit (same symbol)
        if self._positions_in_symbol(symbol) >= pp.max_correlated_positions:
            return False, "correlated_limit"

        # 6. Portfolio exposure budget
        if self._exposure_pct() >= pp.max_portfolio_exposure_pct:
            return False, "exposure_limit"

        # 7. Regime exposure limit
        if self._regime_exposure_pct(regime) >= pp.regime_exposure_limit_pct:
            return False, "regime_exposure_limit"

        return True, None

    def _close_matured(self, at_dt: datetime) -> None:
        """Remove and realise all open positions whose exit_dt <= at_dt."""
        matured     = [pos for pos in self._open if pos.exit_dt <= at_dt]
        self._open  = [pos for pos in self._open if pos.exit_dt >  at_dt]
        for pos in matured:
            self._realize_close(pos, at_dt)

    def _realize_close(self, pos: _OpenPosition, at_dt: datetime) -> None:
        """Realise P&L for a position and update equity + equity curve."""
        pt = pos.pt
        if pt.dollar_pnl is not None:
            self._equity = round(self._equity + pt.dollar_pnl, 4)
            today = at_dt.date()
            self._daily_pnl[today] = self._daily_pnl.get(today, 0.0) + pt.dollar_pnl

        # Update peak equity
        if self._equity > self._peak_equity:
            self._peak_equity = self._equity

        # Update volatility buffer
        if pt.trade.net_pnl_pct is not None:   # type: ignore[attr-defined]
            self._recent_pnls.append(pt.trade.net_pnl_pct)  # type: ignore[attr-defined]
            if len(self._recent_pnls) > self._pp.vol_lookback_trades:
                self._recent_pnls.pop(0)

        # Equity curve — close event
        exp = self._exposure_pct()
        self._exposure_snapshots.append(exp)
        self._curve.append(EquityCurvePoint(
            timestamp           = at_dt.isoformat(),
            equity              = self._equity,
            drawdown_pct        = self._drawdown_pct(),
            open_positions      = len(self._open),
            exposure_pct        = exp,
            daily_pnl           = self._daily_pnl.get(at_dt.date(), 0.0),
            event               = "close",
            symbol              = pt.trade.symbol,     # type: ignore[attr-defined]
            trade_pnl_on_equity = pt.pnl_on_equity,
        ))

    def _record_open_event(self, trade: object, entry_dt: datetime) -> None:
        """Add an "open" event to the equity curve."""
        exp = self._exposure_pct()
        self._exposure_snapshots.append(exp)
        self._curve.append(EquityCurvePoint(
            timestamp      = entry_dt.isoformat(),
            equity         = self._equity,
            drawdown_pct   = self._drawdown_pct(),
            open_positions = len(self._open),
            exposure_pct   = exp,
            daily_pnl      = self._daily_pnl.get(entry_dt.date(), 0.0),
            event          = "open",
            symbol         = trade.symbol,              # type: ignore[attr-defined]
        ))

    # ------------------------------------------------------------------
    # Main simulation loop
    # ------------------------------------------------------------------

    def run(
        self,
        trades: list,                    # list[SimulatedTrade]
    ) -> tuple[list[PortfolioTrade], list[EquityCurvePoint]]:
        """
        Simulate portfolio-level execution over a list of SimulatedTrades.

        Trades are sorted chronologically by captured_at before processing.
        Returns (all_portfolio_trades, equity_curve).
        all_portfolio_trades includes both entered and skipped trades.
        """
        sorted_trades = sorted(trades, key=lambda t: t.captured_at)   # type: ignore[attr-defined]
        all_pts: list[PortfolioTrade] = []

        for trade in sorted_trades:
            entry_dt = self._parse_dt(trade.captured_at)   # type: ignore[attr-defined]
            regime   = _infer_trade_regime(trade)

            # --- Handle no_data trades: always skip ---
            if (trade.exit_horizon is None                          # type: ignore[attr-defined]
                    or trade.exit_horizon not in _HORIZON_DURATIONS):   # type: ignore[attr-defined]
                pt = PortfolioTrade(
                    trade            = trade,
                    entry_dt         = entry_dt,
                    exit_dt          = entry_dt,
                    regime           = regime,
                    position_size_pct= 0.0,
                    capital_at_entry = self._equity,
                    dollar_pnl       = None,
                    pnl_on_equity    = None,
                    skipped          = True,
                    skip_reason      = "no_data",
                )
                all_pts.append(pt)
                self._skipped_pts.append(pt)
                continue

            exit_dt = entry_dt + _HORIZON_DURATIONS[trade.exit_horizon]   # type: ignore[attr-defined]

            # --- Close positions that matured before this entry ---
            self._close_matured(entry_dt)

            # --- Risk control check ---
            allowed, skip_reason = self._check_risk_controls(
                entry_dt, regime, trade.symbol   # type: ignore[attr-defined]
            )

            if not allowed:
                pt = PortfolioTrade(
                    trade            = trade,
                    entry_dt         = entry_dt,
                    exit_dt          = exit_dt,
                    regime           = regime,
                    position_size_pct= 0.0,
                    capital_at_entry = self._equity,
                    dollar_pnl       = None,
                    pnl_on_equity    = None,
                    skipped          = True,
                    skip_reason      = skip_reason,
                )
                all_pts.append(pt)
                self._skipped_pts.append(pt)
                continue

            # --- Position sizing ---
            size_pct = self._compute_size(self._tp.stop_pct)    # type: ignore[attr-defined]

            # --- P&L computation (compounding: sizes off current equity) ---
            dollar_pnl    = None
            pnl_on_equity = None
            if trade.net_pnl_pct is not None:   # type: ignore[attr-defined]
                position_value = self._equity * size_pct / 100.0
                dollar_pnl     = round(position_value * trade.net_pnl_pct / 100.0, 4)    # type: ignore[attr-defined]
                pnl_on_equity  = round(size_pct * trade.net_pnl_pct / 100.0, 6)          # type: ignore[attr-defined]

            pt = PortfolioTrade(
                trade            = trade,
                entry_dt         = entry_dt,
                exit_dt          = exit_dt,
                regime           = regime,
                position_size_pct= size_pct,
                capital_at_entry = self._equity,
                dollar_pnl       = dollar_pnl,
                pnl_on_equity    = pnl_on_equity,
                skipped          = False,
                skip_reason      = None,
            )

            # --- Open position ---
            open_pos = _OpenPosition(
                pt                = pt,
                symbol            = trade.symbol,   # type: ignore[attr-defined]
                regime            = regime,
                exit_dt           = exit_dt,
                position_size_pct = size_pct,
            )
            self._open.append(open_pos)
            self._closed_pts.append(pt)
            all_pts.append(pt)
            self._record_open_event(trade, entry_dt)

        # --- Final sweep: close all remaining open positions ---
        remaining = sorted(self._open, key=lambda p: p.exit_dt)
        self._open = []
        for pos in remaining:
            self._realize_close(pos, pos.exit_dt)

        return all_pts, self._curve

    def get_metrics_data(self) -> dict:
        """
        Return raw aggregate data after run() completes.
        Call compute_portfolio_metrics() for the full PortfolioMetrics object.
        """
        closed  = self._closed_pts
        skipped = self._skipped_pts

        pnl_on_eq = [pt.pnl_on_equity for pt in closed if pt.pnl_on_equity is not None]
        winning   = [pt for pt in closed if pt.pnl_on_equity is not None and pt.pnl_on_equity > 0]
        losing    = [pt for pt in closed if pt.pnl_on_equity is not None and pt.pnl_on_equity <= 0]
        no_data_ct = sum(1 for pt in skipped if pt.skip_reason == "no_data")
        n = len(pnl_on_eq)

        win_rate = round(len(winning) / n, 4) if n > 0 else None

        win_pnls      = [pt.pnl_on_equity for pt in winning]
        loss_pnls     = [pt.pnl_on_equity for pt in losing]
        avg_win       = _safe_mean(win_pnls)
        avg_loss_raw  = _safe_mean(loss_pnls)         # negative
        avg_loss      = round(abs(avg_loss_raw), 6)   if avg_loss_raw is not None else None
        avg_win_r     = round(avg_win,         6)     if avg_win      is not None else None

        expectancy = round(_safe_mean(pnl_on_eq), 6) if pnl_on_eq else None
        exp_per_unit = round(expectancy / avg_loss, 4) if (
            expectancy is not None and avg_loss and avg_loss > 0
        ) else None

        # Profit factor on dollar P&L
        gross_wins   = sum(pt.dollar_pnl for pt in winning  if pt.dollar_pnl is not None)
        gross_losses = abs(sum(pt.dollar_pnl for pt in losing   if pt.dollar_pnl is not None))
        profit_factor = round(gross_wins / gross_losses, 4) if gross_losses > 0 else None

        # Total return
        total_return = round(
            (self._equity - self._pp.initial_capital) / self._pp.initial_capital * 100.0, 4
        )

        # Time span for annualisation
        ann_return = None
        span_days  = 0.0
        all_dts = (
            [pt.entry_dt for pt in closed]
            + [pt.exit_dt  for pt in closed]
            + [pt.entry_dt for pt in skipped if pt.entry_dt != pt.exit_dt]
        )
        if all_dts:
            span_days = (max(all_dts) - min(all_dts)).total_seconds() / 86400.0
            if span_days >= 1.0:
                years = span_days / 365.25
                ann_return = round(((1.0 + total_return / 100.0) ** (1.0 / years) - 1.0) * 100.0, 4)

        # Sharpe / Sortino
        sharpe = sortino = calmar = None
        eq_std = _safe_pstdev(pnl_on_eq)

        if n >= _MIN_TRADES_FOR_RATIOS and eq_std and eq_std > 1e-9:
            mean_r = _safe_mean(pnl_on_eq)

            # Annualisation factor
            if span_days >= 1.0:
                trades_per_year = n / (span_days / 365.25)
                ann_factor = math.sqrt(trades_per_year)
            else:
                ann_factor = 1.0

            sharpe = round(mean_r / eq_std * ann_factor, 4)

            dd_dev = _sortino_downside_dev(pnl_on_eq)
            if dd_dev > 1e-9:
                sortino = round(mean_r / dd_dev * ann_factor, 4)

        # Drawdown from equity curve
        equity_values = [self._pp.initial_capital] + [
            pt.equity for pt in self._curve if pt.event == "close"
        ]
        max_dd_pct, max_dd_dur = _compute_drawdown_stats(equity_values)

        # Calmar
        if ann_return is not None and max_dd_pct > 0:
            calmar = round(ann_return / max_dd_pct, 4)

        # Recovery factor
        recovery = round(total_return / max_dd_pct, 4) if max_dd_pct > 0 else None

        # Average drawdown
        dd_vals = [pt.drawdown_pct for pt in self._curve if pt.event == "close"]
        avg_dd  = round(_safe_mean(dd_vals), 4) if dd_vals else None

        # Exposure stats
        sizes         = [pt.position_size_pct for pt in closed]
        avg_size      = round(_safe_mean(sizes), 4)       if sizes else None
        peak_exposure = max(self._exposure_snapshots)      if self._exposure_snapshots else 0.0
        avg_exposure  = round(_safe_mean(self._exposure_snapshots), 4) if self._exposure_snapshots else None

        # Average concurrent open positions
        open_counts = [pt.open_positions for pt in self._curve]
        avg_conc    = round(_safe_mean(open_counts), 2) if open_counts else None

        # Regime concentration (% of total deployed dollar P&L absolute)
        regime_cap:    dict[str, float] = {}
        regime_wins_d: dict[str, list[bool]] = {}
        for pt in closed:
            amount = abs(pt.dollar_pnl) if pt.dollar_pnl is not None else 0.0
            regime_cap[pt.regime]  = regime_cap.get(pt.regime, 0.0) + amount
            if pt.pnl_on_equity is not None:
                regime_wins_d.setdefault(pt.regime, []).append(pt.pnl_on_equity > 0)

        total_cap = sum(regime_cap.values())
        regime_conc: dict[str, float] = {}
        regime_wr:   dict[str, Optional[float]] = {}
        for r, cap in regime_cap.items():
            regime_conc[r] = round(cap / total_cap * 100.0, 2) if total_cap > 0 else 0.0
        for r, wlist in regime_wins_d.items():
            regime_wr[r] = round(sum(wlist) / len(wlist), 4) if wlist else None

        return dict(
            final_capital             = self._equity,
            total_return_pct          = total_return,
            annualized_return_pct     = ann_return,
            sharpe_ratio              = sharpe,
            sortino_ratio             = sortino,
            calmar_ratio              = calmar,
            max_drawdown_pct          = max_dd_pct,
            avg_drawdown_pct          = avg_dd,
            max_drawdown_duration     = max_dd_dur,
            recovery_factor           = recovery,
            total_entered             = len(closed),
            total_skipped             = len(skipped),
            winning_trades            = len(winning),
            losing_trades             = len(losing),
            no_data_trades            = no_data_ct,
            win_rate                  = win_rate,
            profit_factor             = profit_factor,
            avg_win_on_equity         = avg_win_r,
            avg_loss_on_equity        = avg_loss,
            expectancy_on_equity      = expectancy,
            expectancy_per_unit_risk  = exp_per_unit,
            avg_position_size_pct     = avg_size,
            peak_exposure_pct         = round(peak_exposure, 4),
            avg_exposure_pct          = avg_exposure,
            avg_concurrent_positions  = avg_conc,
            regime_concentration      = regime_conc,
            regime_win_rates          = regime_wr,
            circuit_breaker_triggered = self._circuit_breaker,
            daily_loss_limit_triggered= len(self._daily_limit_days),
            _eq_std                   = eq_std,    # internal — used by warnings
            _n_entered                = len(closed),
        )


# ---------------------------------------------------------------------------
# Warning generator
# ---------------------------------------------------------------------------

def _generate_portfolio_warnings(
    data:    dict,
    pp:      PortfolioParams,
    symbols: list[str],
) -> list[str]:
    """Generate portfolio-level warnings from aggregate metrics data."""
    warnings: list[str] = []

    # Always-present structural limitation
    warnings.append(
        "discrete_exit_prices: exits modelled at 4 horizon closing prices only "
        "(15m/1h/4h/1d) — intraday stop/target touches are not captured"
    )

    # Insufficient diversification
    if len(set(symbols)) < 2:
        warnings.append(
            "insufficient_diversification: only 1 symbol in portfolio — "
            "all risk is concentrated in a single instrument"
        )

    # Over-concentration in a single regime
    for regime, pct in data.get("regime_concentration", {}).items():
        if pct > _OVERCONCENTRATION_PCT:
            warnings.append(
                f"over_concentration: {pct:.1f}% of deployed capital is in "
                f"'{regime}' regime — results may not generalise to other market conditions"
            )

    # Excessive peak leverage / exposure
    peak_exp = data.get("peak_exposure_pct", 0.0)
    if peak_exp > _EXCESSIVE_LEVERAGE_PCT:
        warnings.append(
            f"excessive_leverage: peak portfolio exposure reached {peak_exp:.1f}% of equity — "
            f"consider reducing max_position_size_pct or concurrent_position_limit"
        )

    # Unstable expectancy
    eq_std   = data.get("_eq_std")
    exp      = data.get("expectancy_on_equity")
    if eq_std is not None and exp is not None and abs(exp) > 1e-9:
        ratio = eq_std / abs(exp)
        if ratio > 3.0:
            warnings.append(
                f"unstable_expectancy: equity-return std is {ratio:.1f}× the per-trade "
                f"expectancy — edge is small relative to variance; extend the backtest window"
            )

    # Regime dependency: if one regime accounts for >70% of wins
    wr_map = data.get("regime_win_rates", {})
    conc    = data.get("regime_concentration", {})
    for regime, pct in conc.items():
        rwr = wr_map.get(regime)
        if pct > 50.0 and rwr is not None and rwr > 0.70:
            warnings.append(
                f"regime_dependency: {pct:.1f}% of capital is in '{regime}' regime "
                f"with {rwr:.0%} win rate — performance is heavily regime-dependent"
            )

    # High skip rate
    n_entered = data.get("total_entered", 0)
    n_skipped = data.get("total_skipped", 0)
    total     = n_entered + n_skipped
    if total > 0 and n_skipped / total > _HIGH_SKIP_RATE:
        warnings.append(
            f"high_skip_rate: {n_skipped}/{total} ({n_skipped/total:.0%}) signals skipped "
            f"— risk controls may be too restrictive; consider widening limits"
        )

    # Circuit breaker triggered
    if data.get("circuit_breaker_triggered"):
        warnings.append(
            f"circuit_breaker_triggered: trading was halted after a {pp.circuit_breaker_drawdown_pct}% "
            f"drawdown from peak — review position sizing and stop distances"
        )

    # Negative expectancy
    if exp is not None and exp < 0:
        warnings.append(
            "negative_expectancy: mean equity return per trade is negative — "
            "this parameter combination has no edge on this dataset"
        )

    return warnings


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def run_portfolio_simulation(
    trades:       list,               # list[SimulatedTrade]
    params:       PortfolioParams,
    trade_params: object,             # TradeParams
    symbols:      list[str],
    window:       str,
) -> tuple[list[PortfolioTrade], list[EquityCurvePoint]]:
    """
    Run portfolio simulation on a pre-loaded list of SimulatedTrades.

    This is the primary entry point for testing (no DB access).
    """
    sim = PortfolioSimulator(params, trade_params)
    return sim.run(trades)


def compute_portfolio_metrics(
    trades:       list,               # list[SimulatedTrade]
    params:       PortfolioParams,
    trade_params: object,             # TradeParams
    symbols:      list[str],
    window:       str,
) -> PortfolioMetrics:
    """
    Run simulation and return a PortfolioMetrics object.
    """
    from app.services.trade_simulator import TradeParams as _TP   # noqa: F401

    sim = PortfolioSimulator(params, trade_params)
    sim.run(trades)
    data = sim.get_metrics_data()

    warnings = _generate_portfolio_warnings(data, params, symbols)
    now      = datetime.now(timezone.utc).isoformat()

    return PortfolioMetrics(
        symbols                   = symbols,
        window                    = window,
        trade_params              = trade_params.to_dict() if hasattr(trade_params, "to_dict") else {},
        portfolio_params          = params.to_dict(),
        initial_capital           = params.initial_capital,
        final_capital             = data["final_capital"],
        total_return_pct          = data["total_return_pct"],
        annualized_return_pct     = data["annualized_return_pct"],
        sharpe_ratio              = data["sharpe_ratio"],
        sortino_ratio             = data["sortino_ratio"],
        calmar_ratio              = data["calmar_ratio"],
        max_drawdown_pct          = data["max_drawdown_pct"],
        avg_drawdown_pct          = data["avg_drawdown_pct"],
        max_drawdown_duration     = data["max_drawdown_duration"],
        recovery_factor           = data["recovery_factor"],
        total_signals             = len(trades),
        total_entered             = data["total_entered"],
        total_skipped             = data["total_skipped"],
        winning_trades            = data["winning_trades"],
        losing_trades             = data["losing_trades"],
        no_data_trades            = data["no_data_trades"],
        win_rate                  = data["win_rate"],
        profit_factor             = data["profit_factor"],
        avg_win_on_equity         = data["avg_win_on_equity"],
        avg_loss_on_equity        = data["avg_loss_on_equity"],
        expectancy_on_equity      = data["expectancy_on_equity"],
        expectancy_per_unit_risk  = data["expectancy_per_unit_risk"],
        avg_position_size_pct     = data["avg_position_size_pct"],
        peak_exposure_pct         = data["peak_exposure_pct"],
        avg_exposure_pct          = data["avg_exposure_pct"],
        avg_concurrent_positions  = data["avg_concurrent_positions"],
        regime_concentration      = data["regime_concentration"],
        regime_win_rates          = data["regime_win_rates"],
        circuit_breaker_triggered = data["circuit_breaker_triggered"],
        daily_loss_limit_triggered= data["daily_loss_limit_triggered"],
        warnings                  = warnings,
        generated_at              = now,
    )


def simulate_portfolio(
    symbols:          list[str],
    params:           PortfolioParams,
    trade_params:     object,              # TradeParams
    window:           str           = "30d",
    expiry:           Optional[str] = None,
    regime_filter:    Optional[str] = None,
    expiry_proximity: Optional[str] = None,
    vol_state:        Optional[str] = None,
) -> tuple[list[PortfolioTrade], list[EquityCurvePoint], PortfolioMetrics]:
    """
    Full pipeline: load trades for all symbols, merge, simulate portfolio.

    Returns (all_portfolio_trades, equity_curve, portfolio_metrics).
    """
    from app.services.trade_simulator import simulate_trades

    all_trades: list = []
    for sym in symbols:
        sym_trades = simulate_trades(
            symbol           = sym.upper(),
            params           = trade_params,
            window           = window,
            expiry           = expiry,
            regime_filter    = regime_filter,
            expiry_proximity = expiry_proximity,
            vol_state        = vol_state,
        )
        all_trades.extend(sym_trades)

    logger.info(
        "simulate_portfolio: symbols=%s window=%s total_signals=%d",
        symbols, window, len(all_trades),
    )

    sim = PortfolioSimulator(params, trade_params)
    all_pts, curve = sim.run(all_trades)
    data = sim.get_metrics_data()

    warnings = _generate_portfolio_warnings(data, params, symbols)
    now      = datetime.now(timezone.utc).isoformat()

    metrics = PortfolioMetrics(
        symbols                   = [s.upper() for s in symbols],
        window                    = window,
        trade_params              = trade_params.to_dict() if hasattr(trade_params, "to_dict") else {},  # type: ignore[attr-defined]
        portfolio_params          = params.to_dict(),
        initial_capital           = params.initial_capital,
        final_capital             = data["final_capital"],
        total_return_pct          = data["total_return_pct"],
        annualized_return_pct     = data["annualized_return_pct"],
        sharpe_ratio              = data["sharpe_ratio"],
        sortino_ratio             = data["sortino_ratio"],
        calmar_ratio              = data["calmar_ratio"],
        max_drawdown_pct          = data["max_drawdown_pct"],
        avg_drawdown_pct          = data["avg_drawdown_pct"],
        max_drawdown_duration     = data["max_drawdown_duration"],
        recovery_factor           = data["recovery_factor"],
        total_signals             = len(all_trades),
        total_entered             = data["total_entered"],
        total_skipped             = data["total_skipped"],
        winning_trades            = data["winning_trades"],
        losing_trades             = data["losing_trades"],
        no_data_trades            = data["no_data_trades"],
        win_rate                  = data["win_rate"],
        profit_factor             = data["profit_factor"],
        avg_win_on_equity         = data["avg_win_on_equity"],
        avg_loss_on_equity        = data["avg_loss_on_equity"],
        expectancy_on_equity      = data["expectancy_on_equity"],
        expectancy_per_unit_risk  = data["expectancy_per_unit_risk"],
        avg_position_size_pct     = data["avg_position_size_pct"],
        peak_exposure_pct         = data["peak_exposure_pct"],
        avg_exposure_pct          = data["avg_exposure_pct"],
        avg_concurrent_positions  = data["avg_concurrent_positions"],
        regime_concentration      = data["regime_concentration"],
        regime_win_rates          = data["regime_win_rates"],
        circuit_breaker_triggered = data["circuit_breaker_triggered"],
        daily_loss_limit_triggered= data["daily_loss_limit_triggered"],
        warnings                  = warnings,
        generated_at              = now,
    )

    return all_pts, curve, metrics
