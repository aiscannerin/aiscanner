"""
Trade Simulation API Routes
============================
Simulate realistic trade outcomes from validated max pain signals.

Endpoints
---------
GET /api/max-pain/trades/simulate
    Simulate individual trades and return the full list.

GET /api/max-pain/trades/summary
    Aggregate statistics + regime and direction breakdowns.

GET /api/max-pain/trades/expectancy
    Focused expectancy report with sizing guidance and warnings.

Common query parameters
-----------------------
symbol            : NSE symbol (required)
window            : lookback window (default: 30d)
expiry            : optional expiry filter
trade_type        : mean_reversion | continuation | long | short (default: mean_reversion)
stop_pct          : stop distance % (default: 1.0)
target_pct        : fixed target % (default: null = use max_pain for mean_reversion)
holding_horizon   : 15m | 1h | 4h | 1d (default: 1d)
slippage_pct      : one-way slippage % (default: 0.05)
transaction_cost_pct: round-trip brokerage % (default: 0.05)
min_distance_pct  : minimum signal distance filter (default: 1.0)
regime_filter     : optional regime label filter
expiry_proximity  : near | far
vol_state         : high_iv | low_iv | normal_iv
"""

from __future__ import annotations

import logging
from flask import Blueprint, request, jsonify
from flask_jwt_extended import jwt_required
from typing import Optional

from app.services.trade_simulator import (
    TradeParams,
    simulate_trades,
    compute_expectancy,
    build_expectancy_report,
    compute_regime_breakdown,
    VALID_TRADE_TYPES,
)

logger = logging.getLogger(__name__)

trade_bp = Blueprint(
    "max_pain_trades", __name__, url_prefix="/api/max-pain/trades"
)

VALID_WINDOWS  = {"1h", "4h", "1d", "3d", "7d", "30d", "90d"}
VALID_HORIZONS = {"15m", "1h", "4h", "1d"}
VALID_EXPIRY_PROXIMITY = {"near", "far"}
VALID_VOL_STATES       = {"high_iv", "low_iv", "normal_iv"}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _ok(data, status: int = 200):
    return jsonify({"success": True, "data": data}), status


def _err(message: str, status: int = 400, code: str = "INVALID_PARAMS"):
    return jsonify({"success": False, "error": message, "code": code}), status


def _parse_params() -> tuple[Optional[TradeParams], Optional[str]]:
    """
    Parse and validate TradeParams from query string.
    Returns (params, error_message).  error_message is None on success.
    """
    def _float(key: str, default: float) -> float:
        try:
            return float(request.args.get(key, default))
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

    trade_type = request.args.get("trade_type", "mean_reversion")
    if trade_type not in VALID_TRADE_TYPES:
        return None, (
            f"invalid trade_type '{trade_type}'; "
            f"choose from {sorted(VALID_TRADE_TYPES)}"
        )

    holding_horizon = request.args.get("holding_horizon", "1d")
    if holding_horizon not in VALID_HORIZONS:
        return None, (
            f"invalid holding_horizon '{holding_horizon}'; "
            f"choose from {sorted(VALID_HORIZONS)}"
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


def _common_args() -> dict:
    """Extract common routing arguments."""
    window = request.args.get("window", "30d")
    if window not in VALID_WINDOWS:
        window = "30d"

    expiry_proximity = request.args.get("expiry_proximity")
    if expiry_proximity not in VALID_EXPIRY_PROXIMITY:
        expiry_proximity = None

    vol_state = request.args.get("vol_state")
    if vol_state not in VALID_VOL_STATES:
        vol_state = None

    return {
        "window":           window,
        "expiry":           request.args.get("expiry") or None,
        "regime_filter":    request.args.get("regime_filter") or None,
        "expiry_proximity": expiry_proximity,
        "vol_state":        vol_state,
    }


def _require_symbol() -> tuple[Optional[str], Optional[str]]:
    sym = request.args.get("symbol", "").strip().upper()
    if not sym:
        return None, "symbol is required"
    return sym, None


# ---------------------------------------------------------------------------
# GET /api/max-pain/trades/simulate
# ---------------------------------------------------------------------------

@trade_bp.route("/simulate", methods=["GET"])
@jwt_required()
def simulate():
    """
    Simulate individual trades from max pain signals.

    Returns the full list of simulated trades (paginated), including
    trades where no forward data was available (exit_reason=no_data).

    Extra query params:
      limit  : max trades to return (default: 200, max: 500)
      offset : skip first N trades (default: 0)

    Response:
      {
        "symbol", "window", "params",
        "total":      int  (total simulated before pagination),
        "no_data":    int  (signals with no forward price data),
        "limit":      int,
        "offset":     int,
        "trades":     [SimulatedTrade.to_dict(), …]
      }
    """
    sym, err = _require_symbol()
    if err:
        return _err(err)

    params, err = _parse_params()
    if err:
        return _err(err)

    args  = _common_args()
    limit  = max(1, min(int(request.args.get("limit",  200)), 500))
    offset = max(0, int(request.args.get("offset", 0)))

    try:
        trades = simulate_trades(symbol=sym, params=params, **args)

        total    = len(trades)
        no_data  = sum(1 for t in trades if t.exit_reason == "no_data")
        page     = trades[offset: offset + limit]

        return _ok({
            "symbol":   sym,
            "window":   args["window"],
            "params":   params.to_dict(),
            "total":    total,
            "no_data":  no_data,
            "limit":    limit,
            "offset":   offset,
            "trades":   [t.to_dict() for t in page],
        })

    except Exception as exc:
        logger.error("Trade simulate error for %s: %s", sym, exc, exc_info=True)
        return _err(str(exc), status=500, code="SIMULATION_ERROR")


# ---------------------------------------------------------------------------
# GET /api/max-pain/trades/summary
# ---------------------------------------------------------------------------

@trade_bp.route("/summary", methods=["GET"])
@jwt_required()
def summary():
    """
    Aggregate trade statistics with regime and direction breakdowns.

    Response:
      {
        "symbol", "window", "params",
        "report":   ExpectancyReport.to_dict(),
        "by_direction": {
          "bullish": { win_rate, expectancy_pct, count },
          "bearish": { … }
        },
        "by_exit_reason": { "target": N, "stop": N, "time_stop": N, … },
        "by_regime": {
          "expiry_pinning": { count, win_rate, expectancy_pct, … },
          …
        }
      }
    """
    sym, err = _require_symbol()
    if err:
        return _err(err)

    params, err = _parse_params()
    if err:
        return _err(err)

    args = _common_args()

    try:
        trades = simulate_trades(symbol=sym, params=params, **args)
        report = build_expectancy_report(trades, params, sym, args["window"])

        # Direction breakdown
        by_direction: dict[str, dict] = {}
        for side in ("bullish", "bearish"):
            bucket = [t for t in trades if t.direction == side and t.is_win is not None]
            if not bucket:
                continue
            wins   = sum(1 for t in bucket if t.is_win)
            pnls   = [t.net_pnl_pct for t in bucket if t.net_pnl_pct is not None]
            mean_p = round(sum(pnls) / len(pnls), 4) if pnls else None
            by_direction[side] = {
                "count":          len(bucket),
                "wins":           wins,
                "win_rate":       round(wins / len(bucket), 4),
                "expectancy_pct": mean_p,
            }

        # Regime breakdown (static inference)
        by_regime = compute_regime_breakdown(trades, params, sym, args["window"])

        return _ok({
            "symbol":         sym,
            "window":         args["window"],
            "params":         params.to_dict(),
            "report":         report.to_dict(),
            "by_direction":   by_direction,
            "by_exit_reason": report.exits_by_reason,
            "by_regime":      by_regime,
        })

    except Exception as exc:
        logger.error("Trade summary error for %s: %s", sym, exc, exc_info=True)
        return _err(str(exc), status=500, code="SIMULATION_ERROR")


# ---------------------------------------------------------------------------
# GET /api/max-pain/trades/expectancy
# ---------------------------------------------------------------------------

@trade_bp.route("/expectancy", methods=["GET"])
@jwt_required()
def expectancy():
    """
    Focused expectancy report with position sizing guidance.

    Response:
      {
        "symbol", "window", "params",
        "sample":   { total_signals, simulated, wins, losses, no_data },
        "metrics":  { win_rate, avg_win_pct, avg_loss_pct, payoff_ratio,
                      expectancy_pct, expectancy_r, profit_factor,
                      std_pnl, max_win_pct, max_loss_pct },
        "risk":     { max_drawdown_pct, avg_mae_pct, avg_mfe_pct },
        "sizing":   { kelly_fraction, recommended_kelly },
        "exits_by_reason": { … },
        "warnings": [ … ],
        "generated_at": str
      }
    """
    sym, err = _require_symbol()
    if err:
        return _err(err)

    params, err = _parse_params()
    if err:
        return _err(err)

    args = _common_args()

    try:
        report = compute_expectancy(symbol=sym, params=params, **args)
        return _ok(report.to_dict())

    except Exception as exc:
        logger.error("Trade expectancy error for %s: %s", sym, exc, exc_info=True)
        return _err(str(exc), status=500, code="SIMULATION_ERROR")
