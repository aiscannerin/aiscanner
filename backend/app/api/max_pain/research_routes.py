"""
Quantitative Research Workbench API Routes
===========================================
Expose the research engine through four focused endpoints.

Endpoints
---------
GET /api/max-pain/research/features
    Analyse each feature's conditional relationship with net P&L.
    Returns per-feature correlations, conditional expectancy buckets,
    and cross-sectional breakdowns.

GET /api/max-pain/research/correlations
    Feature-to-PnL correlations (Pearson + Spearman) for all continuous
    and categorical features.  Includes feature-feature pairwise correlations
    and redundancy flags.

GET /api/max-pain/research/stability
    Split-half reliability and rolling directional consistency for each
    feature and each (symbol, regime) signal combination.

GET /api/max-pain/research/rankings
    Ranked (symbol, regime) combinations by expectancy, stability,
    win rate, and risk-adjusted return.  Also ranked per regime.

Common query parameters (all endpoints)
-----------------------------------------
symbols               : comma-separated NSE symbols (required, e.g. "NIFTY,BANKNIFTY")
window                : lookback window (default: 30d)
expiry                : optional expiry filter
trade_type            : mean_reversion | continuation | long | short
stop_pct              : stop distance % (default: 1.0)
target_pct            : fixed target % (optional)
holding_horizon       : 15m | 1h | 4h | 1d (default: 1d)
slippage_pct          : one-way slippage % (default: 0.05)
transaction_cost_pct  : round-trip brokerage % (default: 0.05)
min_distance_pct      : minimum signal distance % (default: 1.0)
regime_filter         : optional regime label filter
expiry_proximity      : near | far
vol_state             : high_iv | low_iv | normal_iv

Research-specific parameters
------------------------------
n_buckets  : quantile buckets for /features (default: 4, range: 2–10)
roll_window: rolling window size in trades for /stability (default: 20, range: 5–100)
"""

from __future__ import annotations

import logging
from typing import Optional

from flask import Blueprint, request, jsonify
from flask_jwt_extended import jwt_required

from app.services.trade_simulator import TradeParams, VALID_TRADE_TYPES, simulate_trades
from app.services.research_engine import (
    extract_feature_records,
    run_feature_analysis,
    run_correlation_analysis,
    run_stability_analysis,
    run_rankings,
)

logger = logging.getLogger(__name__)

research_bp = Blueprint(
    "max_pain_research", __name__, url_prefix="/api/max-pain/research"
)

_VALID_WINDOWS          = {"1h", "4h", "1d", "3d", "7d", "30d", "90d"}
_VALID_HORIZONS         = {"15m", "1h", "4h", "1d"}
_VALID_EXPIRY_PROXIMITY = {"near", "far"}
_VALID_VOL_STATES       = {"high_iv", "low_iv", "normal_iv"}

_MAX_SYMBOLS = 10


# ---------------------------------------------------------------------------
# Helpers (shared across all endpoints)
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


def _load_records(syms: list[str], t_params: TradeParams, filters: dict) -> list:
    """Load and combine SimulatedTrade objects for all symbols, return FeatureRecords."""
    trades_per_symbol = {}
    for sym in syms:
        trades_per_symbol[sym] = simulate_trades(
            symbol           = sym,
            params           = t_params,
            window           = filters["window"],
            expiry           = filters["expiry"],
            regime_filter    = filters["regime_filter"],
            expiry_proximity = filters["expiry_proximity"],
            vol_state        = filters["vol_state"],
        )
    return extract_feature_records(trades_per_symbol)


# ---------------------------------------------------------------------------
# GET /api/max-pain/research/features
# ---------------------------------------------------------------------------

@research_bp.route("/features", methods=["GET"])
@jwt_required()
def features():
    """
    Feature analysis: conditional expectancy and correlation for each signal feature.

    Extra parameters:
      n_buckets : quantile buckets for continuous features (default: 4, range: 2–10)

    Response shape:
      {
        "symbols", "window", "n_trades",
        "continuous": [
          {
            "name", "label", "type", "n_obs", "mean", "std",
            "pearson_r", "spearman_r", "eta_squared",
            "buckets": [{"label", "range_low", "range_high", "n_obs",
                          "win_rate", "expectancy_pct", "std_pct", "sharpe_approx"}, ...]
          }, ...
        ],
        "categorical": [
          {
            "name", "label", "type", "n_obs", "eta_squared",
            "categories": [{"category", "n_obs", "win_rate", "expectancy_pct", "std_pct"}, ...]
          }, ...
        ],
        "cross_sections": {
          "symbol":           [{"group", "n_obs", "win_rate", "expectancy_pct", ...}, ...],
          "direction":        [...],
          "vol_state":        [...],
          "expiry_proximity": [...]
        },
        "warnings": [...],
        "generated_at": str
      }
    """
    syms, err = _require_symbols()
    if err:
        return _err(err)

    t_params, err = _parse_trade_params()
    if err:
        return _err(err)

    filters   = _common_filter_args()
    n_buckets = max(2, min(_int("n_buckets", 4), 10))

    try:
        records = _load_records(syms, t_params, filters)
        result  = run_feature_analysis(records, syms, filters["window"], n_buckets)
        return _ok(result.to_dict())

    except ValueError as exc:
        return _err(str(exc), code="INSUFFICIENT_DATA")
    except Exception as exc:
        logger.error("Research features error: %s", exc, exc_info=True)
        return _err(str(exc), status=500, code="RESEARCH_ERROR")


# ---------------------------------------------------------------------------
# GET /api/max-pain/research/correlations
# ---------------------------------------------------------------------------

@research_bp.route("/correlations", methods=["GET"])
@jwt_required()
def correlations():
    """
    Feature correlation analysis.

    Response shape:
      {
        "symbols", "window", "n_trades",
        "feature_pnl_correlations": [
          {"feature", "label", "pearson_r", "spearman_r", "n_obs"}, ...
        ],
        "feature_feature_correlations": [
          {"feature_a", "feature_b", "pearson_r", "n_obs", "redundant"}, ...
        ],
        "redundant_features": [str, ...],
        "warnings": [...],
        "generated_at": str
      }
    """
    syms, err = _require_symbols()
    if err:
        return _err(err)

    t_params, err = _parse_trade_params()
    if err:
        return _err(err)

    filters = _common_filter_args()

    try:
        records = _load_records(syms, t_params, filters)
        result  = run_correlation_analysis(records, syms, filters["window"])
        return _ok(result.to_dict())

    except ValueError as exc:
        return _err(str(exc), code="INSUFFICIENT_DATA")
    except Exception as exc:
        logger.error("Research correlations error: %s", exc, exc_info=True)
        return _err(str(exc), status=500, code="RESEARCH_ERROR")


# ---------------------------------------------------------------------------
# GET /api/max-pain/research/stability
# ---------------------------------------------------------------------------

@research_bp.route("/stability", methods=["GET"])
@jwt_required()
def stability():
    """
    Signal stability analysis using split-half reliability and rolling consistency.

    Extra parameters:
      roll_window : rolling window size in trades (default: 20, range: 5–100)

    Response shape:
      {
        "symbols", "window", "n_trades",
        "feature_stability": [
          {
            "feature", "label", "n_obs",
            "first_half_r", "second_half_r",
            "direction_consistent", "magnitude_ratio",
            "stability_score", "is_stable",
            "roll_directional_consistency"
          }, ...
        ],
        "signal_stability": [
          {
            "symbol", "regime", "n_obs",
            "first_half_expectancy_pct", "second_half_expectancy_pct",
            "direction_consistent", "stability_score"
          }, ...
        ],
        "most_stable_features": [str, ...],
        "unstable_features":    [str, ...],
        "warnings": [...],
        "generated_at": str
      }
    """
    syms, err = _require_symbols()
    if err:
        return _err(err)

    t_params, err = _parse_trade_params()
    if err:
        return _err(err)

    filters     = _common_filter_args()
    roll_window = max(5, min(_int("roll_window", 20), 100))

    try:
        records = _load_records(syms, t_params, filters)
        result  = run_stability_analysis(records, syms, filters["window"], roll_window)
        return _ok(result.to_dict())

    except ValueError as exc:
        return _err(str(exc), code="INSUFFICIENT_DATA")
    except Exception as exc:
        logger.error("Research stability error: %s", exc, exc_info=True)
        return _err(str(exc), status=500, code="RESEARCH_ERROR")


# ---------------------------------------------------------------------------
# GET /api/max-pain/research/rankings
# ---------------------------------------------------------------------------

@research_bp.route("/rankings", methods=["GET"])
@jwt_required()
def rankings():
    """
    Rank all (symbol, regime) signal combinations by multiple performance
    dimensions.

    Response shape:
      {
        "symbols", "window", "n_trades",
        "by_expectancy":    [RankingEntry, ...],
        "by_stability":     [RankingEntry, ...],
        "by_win_rate":      [RankingEntry, ...],
        "by_risk_adjusted": [RankingEntry, ...],
        "by_regime": {
          "<regime_name>": [RankingEntry, ...],
          ...
        },
        "warnings": [...],
        "generated_at": str
      }

    Each RankingEntry:
      {
        "rank", "symbol", "regime", "n_obs",
        "win_rate", "expectancy_pct", "std_pct",
        "stability_score", "risk_adjusted"
      }
    """
    syms, err = _require_symbols()
    if err:
        return _err(err)

    t_params, err = _parse_trade_params()
    if err:
        return _err(err)

    filters = _common_filter_args()

    try:
        records = _load_records(syms, t_params, filters)
        result  = run_rankings(records, syms, filters["window"])
        return _ok(result.to_dict())

    except ValueError as exc:
        return _err(str(exc), code="INSUFFICIENT_DATA")
    except Exception as exc:
        logger.error("Research rankings error: %s", exc, exc_info=True)
        return _err(str(exc), status=500, code="RESEARCH_ERROR")
