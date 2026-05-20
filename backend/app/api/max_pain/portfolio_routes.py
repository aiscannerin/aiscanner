"""
Portfolio and Risk Management API Routes
=========================================
Simulate portfolio-level capital deployment from max pain trade signals.

Endpoints
---------
GET /api/max-pain/portfolio/simulate
    Run portfolio simulation and return the full list of portfolio trades.

GET /api/max-pain/portfolio/metrics
    Aggregate portfolio performance metrics (Sharpe, Sortino, Calmar, etc.).

GET /api/max-pain/portfolio/equity-curve
    Equity curve, drawdown series, and rolling performance windows.

Common query parameters
-----------------------
symbols               : comma-separated NSE symbols (required, e.g. "NIFTY,BANKNIFTY")
window                : lookback window (default: 30d)
expiry                : optional expiry filter
trade_type            : mean_reversion | continuation | long | short (default: mean_reversion)
stop_pct              : stop distance % (default: 1.0)
target_pct            : fixed target % (default: null)
holding_horizon       : 15m | 1h | 4h | 1d (default: 1d)
slippage_pct          : one-way slippage % (default: 0.05)
transaction_cost_pct  : round-trip brokerage % (default: 0.05)
min_distance_pct      : minimum signal distance % (default: 1.0)
regime_filter         : optional regime label filter
expiry_proximity      : near | far
vol_state             : high_iv | low_iv | normal_iv

Portfolio parameters
--------------------
sizing_method              : fixed_fractional | volatility_adjusted (default: fixed_fractional)
risk_per_trade_pct         : % of equity to risk per trade (default: 2.0)
max_position_size_pct      : max position size % of equity (default: 20.0)
max_portfolio_exposure_pct : max total exposure % of equity (default: 60.0)
concurrent_position_limit  : max simultaneous open positions (default: 5)
max_correlated_positions   : max positions per symbol (default: 2)
daily_loss_limit_pct       : daily halt threshold % of day-equity (default: 5.0)
regime_exposure_limit_pct  : max equity % in one regime (default: 40.0)
circuit_breaker_drawdown_pct : halt if drawdown > this % (default: 20.0)
initial_capital            : starting capital in ₹ (default: 1000000)
target_vol_pct             : target per-trade vol for vol-adjusted sizing (default: 1.0)
vol_lookback_trades        : lookback for realized vol (default: 20)
"""

from __future__ import annotations

import logging
from typing import Optional

from flask import Blueprint, request, jsonify
from flask_jwt_extended import jwt_required

from app.services.trade_simulator import TradeParams, VALID_TRADE_TYPES
from app.services.portfolio_engine import (
    PortfolioParams,
    VALID_SIZING_METHODS,
    simulate_portfolio,
    compute_portfolio_metrics,
    run_portfolio_simulation,
    _compute_rolling_windows,
)

logger = logging.getLogger(__name__)

portfolio_bp = Blueprint(
    "max_pain_portfolio", __name__, url_prefix="/api/max-pain/portfolio"
)

_VALID_WINDOWS          = {"1h", "4h", "1d", "3d", "7d", "30d", "90d"}
_VALID_HORIZONS         = {"15m", "1h", "4h", "1d"}
_VALID_EXPIRY_PROXIMITY = {"near", "far"}
_VALID_VOL_STATES       = {"high_iv", "low_iv", "normal_iv"}

_MAX_SYMBOLS = 10    # guard against excessive fan-out


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _ok(data, status: int = 200):
    return jsonify({"success": True, "data": data}), status


def _err(message: str, status: int = 400, code: str = "INVALID_PARAMS"):
    return jsonify({"success": False, "error": message, "code": code}), status


def _float(key: str, default: float) -> float:
    try:
        return float(request.args.get(key, default))
    except (ValueError, TypeError):
        return default


def _int(key: str, default: int) -> int:
    try:
        return int(request.args.get(key, default))
    except (ValueError, TypeError):
        return default


def _opt_float(key: str) -> Optional[float]:
    v = request.args.get(key)
    if v is None or v == "":
        return None
    try:
        return float(v)
    except (ValueError, TypeError):
        return None


def _require_symbols() -> tuple[Optional[list[str]], Optional[str]]:
    raw = request.args.get("symbols", "").strip()
    if not raw:
        return None, "symbols is required (comma-separated, e.g. NIFTY,BANKNIFTY)"
    syms = [s.strip().upper() for s in raw.split(",") if s.strip()]
    if not syms:
        return None, "symbols is required"
    if len(syms) > _MAX_SYMBOLS:
        return None, f"at most {_MAX_SYMBOLS} symbols per request"
    return syms, None


def _parse_trade_params() -> tuple[Optional[TradeParams], Optional[str]]:
    trade_type = request.args.get("trade_type", "mean_reversion")
    if trade_type not in VALID_TRADE_TYPES:
        return None, (
            f"invalid trade_type '{trade_type}'; "
            f"choose from {sorted(VALID_TRADE_TYPES)}"
        )

    holding_horizon = request.args.get("holding_horizon", "1d")
    if holding_horizon not in _VALID_HORIZONS:
        return None, (
            f"invalid holding_horizon '{holding_horizon}'; "
            f"choose from {sorted(_VALID_HORIZONS)}"
        )

    params = TradeParams(
        trade_type           = trade_type,
        stop_pct             = max(0.01, _float("stop_pct",             1.0)),
        target_pct           = _opt_float("target_pct"),
        holding_horizon      = holding_horizon,
        slippage_pct         = max(0.0,  _float("slippage_pct",         0.05)),
        transaction_cost_pct = max(0.0,  _float("transaction_cost_pct", 0.05)),
        min_distance_pct     = max(0.0,  _float("min_distance_pct",     1.0)),
    )
    issues = params.validate()
    if issues:
        return None, "; ".join(issues)
    return params, None


def _parse_portfolio_params() -> tuple[Optional[PortfolioParams], Optional[str]]:
    sizing_method = request.args.get("sizing_method", "fixed_fractional")
    if sizing_method not in VALID_SIZING_METHODS:
        return None, (
            f"invalid sizing_method '{sizing_method}'; "
            f"choose from {sorted(VALID_SIZING_METHODS)}"
        )

    params = PortfolioParams(
        sizing_method              = sizing_method,
        risk_per_trade_pct         = max(0.01, _float("risk_per_trade_pct",         2.0)),
        max_position_size_pct      = max(0.01, _float("max_position_size_pct",      20.0)),
        max_portfolio_exposure_pct = max(0.01, _float("max_portfolio_exposure_pct", 60.0)),
        concurrent_position_limit  = max(1,    _int("concurrent_position_limit",    5)),
        max_correlated_positions   = max(1,    _int("max_correlated_positions",     2)),
        daily_loss_limit_pct       = max(0.01, _float("daily_loss_limit_pct",       5.0)),
        regime_exposure_limit_pct  = max(0.01, _float("regime_exposure_limit_pct",  40.0)),
        circuit_breaker_drawdown_pct = max(5.0, _float("circuit_breaker_drawdown_pct", 20.0)),
        initial_capital            = max(1.0,  _float("initial_capital",            1_000_000.0)),
        target_vol_pct             = max(0.01, _float("target_vol_pct",             1.0)),
        vol_lookback_trades        = max(5,    _int("vol_lookback_trades",           20)),
    )
    issues = params.validate()
    if issues:
        return None, "; ".join(issues)
    return params, None


def _common_filter_args() -> dict:
    window = request.args.get("window", "30d")
    if window not in _VALID_WINDOWS:
        window = "30d"

    expiry_proximity = request.args.get("expiry_proximity")
    if expiry_proximity not in _VALID_EXPIRY_PROXIMITY:
        expiry_proximity = None

    vol_state = request.args.get("vol_state")
    if vol_state not in _VALID_VOL_STATES:
        vol_state = None

    return {
        "window":           window,
        "expiry":           request.args.get("expiry") or None,
        "regime_filter":    request.args.get("regime_filter") or None,
        "expiry_proximity": expiry_proximity,
        "vol_state":        vol_state,
    }


# ---------------------------------------------------------------------------
# GET /api/max-pain/portfolio/simulate
# ---------------------------------------------------------------------------

@portfolio_bp.route("/simulate", methods=["GET"])
@jwt_required()
def simulate():
    """
    Run portfolio simulation and return the full list of portfolio trades.

    Extra query params:
      limit  : max trades to return (default: 200, max: 1000)
      offset : skip first N trades (default: 0)

    Response:
      {
        "symbols", "window", "trade_params", "portfolio_params",
        "total":          int  (all trades incl. skipped),
        "entered":        int,
        "skipped":        int,
        "no_data":        int,
        "final_equity":   float,
        "total_return_pct": float,
        "limit":          int,
        "offset":         int,
        "trades":         [PortfolioTrade.to_dict(), …],
        "warnings":       [str, …]
      }
    """
    syms, err = _require_symbols()
    if err:
        return _err(err)

    t_params, err = _parse_trade_params()
    if err:
        return _err(err)

    p_params, err = _parse_portfolio_params()
    if err:
        return _err(err)

    filters = _common_filter_args()
    limit   = max(1, min(_int("limit",  200), 1000))
    offset  = max(0,     _int("offset", 0))

    try:
        all_pts, curve, metrics = simulate_portfolio(
            symbols      = syms,
            params       = p_params,
            trade_params = t_params,
            **filters,
        )

        page = all_pts[offset: offset + limit]
        entered  = sum(1 for pt in all_pts if not pt.skipped)
        skipped  = sum(1 for pt in all_pts if pt.skipped)
        no_data  = sum(1 for pt in all_pts if pt.skip_reason == "no_data")

        return _ok({
            "symbols":          syms,
            "window":           filters["window"],
            "trade_params":     t_params.to_dict(),
            "portfolio_params": p_params.to_dict(),
            "total":            len(all_pts),
            "entered":          entered,
            "skipped":          skipped,
            "no_data":          no_data,
            "final_equity":     round(metrics.final_capital, 2),
            "total_return_pct": metrics.total_return_pct,
            "limit":            limit,
            "offset":           offset,
            "trades":           [pt.to_dict() for pt in page],
            "warnings":         metrics.warnings,
        })

    except Exception as exc:
        logger.error("Portfolio simulate error: %s", exc, exc_info=True)
        return _err(str(exc), status=500, code="SIMULATION_ERROR")


# ---------------------------------------------------------------------------
# GET /api/max-pain/portfolio/metrics
# ---------------------------------------------------------------------------

@portfolio_bp.route("/metrics", methods=["GET"])
@jwt_required()
def metrics():
    """
    Aggregate portfolio performance metrics.

    Response: PortfolioMetrics.to_dict() wrapped in the standard envelope.
    Includes: Sharpe, Sortino, Calmar, drawdown stats, regime concentration,
    win rate, profit factor, expectancy per unit risk, risk control triggers.
    """
    syms, err = _require_symbols()
    if err:
        return _err(err)

    t_params, err = _parse_trade_params()
    if err:
        return _err(err)

    p_params, err = _parse_portfolio_params()
    if err:
        return _err(err)

    filters = _common_filter_args()

    try:
        _, __, portfolio_metrics = simulate_portfolio(
            symbols      = syms,
            params       = p_params,
            trade_params = t_params,
            **filters,
        )
        return _ok(portfolio_metrics.to_dict())

    except Exception as exc:
        logger.error("Portfolio metrics error: %s", exc, exc_info=True)
        return _err(str(exc), status=500, code="SIMULATION_ERROR")


# ---------------------------------------------------------------------------
# GET /api/max-pain/portfolio/equity-curve
# ---------------------------------------------------------------------------

@portfolio_bp.route("/equity-curve", methods=["GET"])
@jwt_required()
def equity_curve():
    """
    Equity curve, drawdown series, and rolling performance windows.

    Extra query params:
      roll_window : rolling window size in trades (default: 20, min: 5, max: 100)
      curve_limit : max curve points to return (default: 2000, max: 5000)

    Response:
      {
        "symbols", "window", "initial_capital", "final_capital",
        "total_return_pct", "max_drawdown_pct",
        "curve":    [EquityCurvePoint.to_dict(), …],
        "rolling":  [RollingMetrics.to_dict(), …]
      }
    """
    syms, err = _require_symbols()
    if err:
        return _err(err)

    t_params, err = _parse_trade_params()
    if err:
        return _err(err)

    p_params, err = _parse_portfolio_params()
    if err:
        return _err(err)

    filters     = _common_filter_args()
    roll_window = max(5, min(_int("roll_window", 20), 100))
    curve_limit = max(1, min(_int("curve_limit", 2000), 5000))

    try:
        all_pts, curve, portfolio_metrics = simulate_portfolio(
            symbols      = syms,
            params       = p_params,
            trade_params = t_params,
            **filters,
        )

        # Rolling windows are computed on entered (non-skipped) closed trades
        entered = [pt for pt in all_pts if not pt.skipped]
        rolling = _compute_rolling_windows(entered, roll_window)

        return _ok({
            "symbols":          syms,
            "window":           filters["window"],
            "initial_capital":  p_params.initial_capital,
            "final_capital":    round(portfolio_metrics.final_capital, 2),
            "total_return_pct": portfolio_metrics.total_return_pct,
            "max_drawdown_pct": portfolio_metrics.max_drawdown_pct,
            "curve":            [pt.to_dict() for pt in curve[:curve_limit]],
            "rolling":          [r.to_dict() for r in rolling],
        })

    except Exception as exc:
        logger.error("Portfolio equity-curve error: %s", exc, exc_info=True)
        return _err(str(exc), status=500, code="SIMULATION_ERROR")
