"""
Monte Carlo Robustness and Stress-Testing API Routes
======================================================
Expose the Monte Carlo engine through three focused endpoints.

Endpoints
---------
GET /api/max-pain/monte-carlo/run
    Run a full Monte Carlo simulation and return the aggregate summary.

GET /api/max-pain/monte-carlo/summary
    Alias of /run — same computation, same response shape.
    Preserved as a separate route for semantic clarity in the client.

GET /api/max-pain/monte-carlo/stress
    Run all predefined stress scenarios and return the comparison table.

Common query parameters (all endpoints)
----------------------------------------
symbol              : NSE symbol (required)
window              : lookback window (default: 30d)
expiry              : optional expiry filter
trade_type          : mean_reversion | continuation | long | short
stop_pct            : stop distance % (default: 1.0)
target_pct          : fixed target % (optional)
holding_horizon     : 15m | 1h | 4h | 1d (default: 1d)
slippage_pct        : one-way slippage % (default: 0.05)
transaction_cost_pct: round-trip brokerage % (default: 0.05)
min_distance_pct    : minimum signal distance % (default: 1.0)
regime_filter       : optional regime label filter
expiry_proximity    : near | far
vol_state           : high_iv | low_iv | normal_iv

Monte Carlo parameters (run + summary)
---------------------------------------
n_simulations       : number of paths (default: 1000, max: 10 000)
method              : bootstrap | random_order | block_bootstrap | regime_shuffle
position_size_pct   : fixed sizing % per trade (default: 2.0)
initial_capital     : starting equity ₹ (default: 1 000 000)
ruin_threshold_pct  : drawdown that triggers ruin (default: 50.0)
block_size          : block length for block_bootstrap (default: 5)
seed                : optional integer seed for reproducibility

Stress parameters (/stress only)
----------------------------------
n_simulations       : paths per stress scenario (default: 500, capped at 1 000)
position_size_pct   : sizing % per trade (default: 2.0)
initial_capital     : starting equity ₹ (default: 1 000 000)
ruin_threshold_pct  : ruin threshold (default: 50.0)
seed                : optional integer seed
"""

from __future__ import annotations

import logging
from typing import Optional

from flask import Blueprint, request, jsonify
from flask_jwt_extended import jwt_required

from app.services.trade_simulator import TradeParams, VALID_TRADE_TYPES, simulate_trades
from app.services.monte_carlo_engine import (
    MonteCarloParams,
    VALID_MC_METHODS,
    run_monte_carlo,
    run_stress_tests,
)

logger = logging.getLogger(__name__)

monte_carlo_bp = Blueprint(
    "max_pain_monte_carlo", __name__, url_prefix="/api/max-pain/monte-carlo"
)

_VALID_WINDOWS          = {"1h", "4h", "1d", "3d", "7d", "30d", "90d"}
_VALID_HORIZONS         = {"15m", "1h", "4h", "1d"}
_VALID_EXPIRY_PROXIMITY = {"near", "far"}
_VALID_VOL_STATES       = {"high_iv", "low_iv", "normal_iv"}


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


def _opt_int(key: str) -> Optional[int]:
    v = request.args.get(key)
    if v is None or v == "":
        return None
    try:
        return int(v)
    except (ValueError, TypeError):
        return None


def _require_symbol() -> tuple[Optional[str], Optional[str]]:
    sym = request.args.get("symbol", "").strip().upper()
    if not sym:
        return None, "symbol is required"
    return sym, None


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


def _parse_mc_params(max_sims: int = 10_000) -> tuple[Optional[MonteCarloParams], Optional[str]]:
    method = request.args.get("method", "bootstrap")
    if method not in VALID_MC_METHODS:
        return None, (
            f"invalid method '{method}'; "
            f"choose from {sorted(VALID_MC_METHODS)}"
        )

    n_sims = max(1, min(_int("n_simulations", 1_000), max_sims))

    params = MonteCarloParams(
        n_simulations      = n_sims,
        method             = method,
        position_size_pct  = max(0.01, _float("position_size_pct",  2.0)),
        initial_capital    = max(1.0,  _float("initial_capital",    1_000_000.0)),
        ruin_threshold_pct = max(1.0,  min(_float("ruin_threshold_pct", 50.0), 99.0)),
        block_size         = max(2,    _int("block_size",            5)),
        seed               = _opt_int("seed"),
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


def _load_trades(symbol: str, t_params: TradeParams, filters: dict) -> list:
    """Load SimulatedTrade list — central point so all endpoints share it."""
    return simulate_trades(
        symbol           = symbol,
        params           = t_params,
        window           = filters["window"],
        expiry           = filters["expiry"],
        regime_filter    = filters["regime_filter"],
        expiry_proximity = filters["expiry_proximity"],
        vol_state        = filters["vol_state"],
    )


# ---------------------------------------------------------------------------
# GET /api/max-pain/monte-carlo/run
# ---------------------------------------------------------------------------

@monte_carlo_bp.route("/run", methods=["GET"])
@jwt_required()
def mc_run():
    """
    Run a full Monte Carlo simulation on the trade signal history.

    Response
    --------
    {
      "symbol", "window", "method", "n_sims", "n_trades",
      "distribution": {
        "returns":       { p5, p25, p50, p75, p95 },
        "max_drawdowns": { p5, p25, p50, p75, p95 }
      },
      "tail_risk":    { var_pct, expected_shortfall_pct, capital_at_risk_pct },
      "ruin":         { probability, threshold_pct, survival_probability },
      "recovery":     { median_trades, p95_trades },
      "extremes":     { worst_return_pct, worst_drawdown_pct, best_return_pct },
      "warnings":     [...],
      "generated_at": str
    }
    """
    sym, err = _require_symbol()
    if err:
        return _err(err)

    t_params, err = _parse_trade_params()
    if err:
        return _err(err)

    mc_params, err = _parse_mc_params(max_sims=10_000)
    if err:
        return _err(err)

    filters = _common_filter_args()

    try:
        trades  = _load_trades(sym, t_params, filters)
        summary = run_monte_carlo(trades, mc_params, sym, filters["window"])
        return _ok(summary.to_dict())

    except ValueError as exc:
        return _err(str(exc), code="INSUFFICIENT_DATA")
    except Exception as exc:
        logger.error("MC run error for %s: %s", sym, exc, exc_info=True)
        return _err(str(exc), status=500, code="SIMULATION_ERROR")


# ---------------------------------------------------------------------------
# GET /api/max-pain/monte-carlo/summary
# ---------------------------------------------------------------------------

@monte_carlo_bp.route("/summary", methods=["GET"])
@jwt_required()
def mc_summary():
    """
    Aggregate Monte Carlo summary — identical to /run.

    Preserved as a separate endpoint for semantic clarity:
    use /run for exploration, /summary for dashboards.
    """
    sym, err = _require_symbol()
    if err:
        return _err(err)

    t_params, err = _parse_trade_params()
    if err:
        return _err(err)

    mc_params, err = _parse_mc_params(max_sims=10_000)
    if err:
        return _err(err)

    filters = _common_filter_args()

    try:
        trades  = _load_trades(sym, t_params, filters)
        summary = run_monte_carlo(trades, mc_params, sym, filters["window"])
        return _ok(summary.to_dict())

    except ValueError as exc:
        return _err(str(exc), code="INSUFFICIENT_DATA")
    except Exception as exc:
        logger.error("MC summary error for %s: %s", sym, exc, exc_info=True)
        return _err(str(exc), status=500, code="SIMULATION_ERROR")


# ---------------------------------------------------------------------------
# GET /api/max-pain/monte-carlo/stress
# ---------------------------------------------------------------------------

@monte_carlo_bp.route("/stress", methods=["GET"])
@jwt_required()
def mc_stress():
    """
    Run all predefined stress scenarios and return a comparison table.

    Each scenario modifies the trade P&L series and re-measures expectancy,
    win rate, drawdown distribution, and ruin probability.  Results include
    delta vs baseline so the sensitivity is immediately visible.

    n_simulations is capped at 1 000 per scenario (8 scenarios total).

    Response
    --------
    {
      "symbol", "window", "n_trades",
      "scenarios": [
        {
          "scenario", "description", "n_trades",
          "baseline": { win_rate, expectancy_pct, max_dd_p50, ruin_prob },
          "stressed": { win_rate, expectancy_pct, max_dd_p50, ruin_prob },
          "delta":    { win_rate_delta, expectancy_delta_pct, max_dd_delta },
          "warnings": [...]
        },
        ...
      ],
      "generated_at": str
    }
    """
    sym, err = _require_symbol()
    if err:
        return _err(err)

    t_params, err = _parse_trade_params()
    if err:
        return _err(err)

    # Stress uses a lighter MC; cap per-scenario sims at 1 000
    mc_params, err = _parse_mc_params(max_sims=1_000)
    if err:
        return _err(err)

    # Stress tests default to 500 simulations per scenario unless overridden
    if request.args.get("n_simulations") is None:
        mc_params.n_simulations = 500

    filters = _common_filter_args()

    try:
        trades  = _load_trades(sym, t_params, filters)
        results = run_stress_tests(trades, mc_params, sym, filters["window"])

        from datetime import datetime, timezone
        return _ok({
            "symbol":       sym,
            "window":       filters["window"],
            "n_trades":     sum(1 for t in trades if t.net_pnl_pct is not None),
            "scenarios":    [r.to_dict() for r in results],
            "generated_at": datetime.now(timezone.utc).isoformat(),
        })

    except ValueError as exc:
        return _err(str(exc), code="INSUFFICIENT_DATA")
    except Exception as exc:
        logger.error("MC stress error for %s: %s", sym, exc, exc_info=True)
        return _err(str(exc), status=500, code="SIMULATION_ERROR")
