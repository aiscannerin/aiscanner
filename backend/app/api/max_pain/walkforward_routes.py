"""
Walk-Forward Validation API Routes
====================================
Expose the walk-forward engine through three focused endpoints.

Endpoints
---------
GET /api/max-pain/walkforward/run
    Full walk-forward validation: per-fold IS/OOS stats, degradation
    metrics, aggregate statistics, and all diagnostics.

GET /api/max-pain/walkforward/summary
    Aggregate statistics only (lighter response, same computation).
    Useful for dashboard cards.

GET /api/max-pain/walkforward/stability
    Time-series view per fold: OOS expectancy, feature correlation
    decay, and regime drift across time.  Designed for trend plotting.

Common query parameters (all endpoints)
-----------------------------------------
symbols               : comma-separated NSE symbols (required)
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

Walk-forward parameters
------------------------
method           : expanding | rolling | anchored (default: expanding)
n_splits         : number of train/test folds (2–20, default: 5)
min_train_obs    : minimum training records per fold (5–100, default: 10)
min_test_obs     : minimum test records per fold (3–50, default: 5)
confidence_level : CI confidence level (0.50–0.999, default: 0.95)
features         : comma-separated continuous features to track
                   (default: signal_dist_pct,pcr,avg_iv,days_to_expiry)
"""

from __future__ import annotations

import logging
from typing import Optional

from flask import Blueprint, request, jsonify
from flask_jwt_extended import jwt_required

from app.services.trade_simulator import TradeParams, VALID_TRADE_TYPES, simulate_trades
from app.services.research_engine import (
    extract_feature_records,
    CONTINUOUS_FEATURES,
)
from app.services.walkforward_engine import (
    WalkForwardParams,
    VALID_WF_METHODS,
    run_walkforward,
)

logger = logging.getLogger(__name__)

walkforward_bp = Blueprint(
    "max_pain_walkforward", __name__, url_prefix="/api/max-pain/walkforward"
)

_VALID_WINDOWS          = {"1h", "4h", "1d", "3d", "7d", "30d", "90d"}
_VALID_HORIZONS         = {"15m", "1h", "4h", "1d"}
_VALID_EXPIRY_PROXIMITY = {"near", "far"}
_VALID_VOL_STATES       = {"high_iv", "low_iv", "normal_iv"}

_MAX_SYMBOLS = 10


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


def _parse_wf_params() -> tuple[Optional[WalkForwardParams], Optional[str]]:
    method = request.args.get("method", "expanding")
    if method not in VALID_WF_METHODS:
        return None, (
            f"invalid method '{method}'; "
            f"choose from {sorted(VALID_WF_METHODS)}"
        )

    # Features to track: comma-separated, validated against CONTINUOUS_FEATURES
    raw_features = request.args.get("features", "").strip()
    if raw_features:
        features = [f.strip() for f in raw_features.split(",") if f.strip()]
        invalid = [f for f in features if f not in CONTINUOUS_FEATURES]
        if invalid:
            return None, (
                f"invalid feature(s) {invalid}; "
                f"choose from {CONTINUOUS_FEATURES}"
            )
    else:
        features = list(CONTINUOUS_FEATURES)

    params = WalkForwardParams(
        method           = method,
        n_splits         = max(2, min(_int("n_splits",      5),  20)),
        min_train_obs    = max(5, min(_int("min_train_obs", 10), 100)),
        min_test_obs     = max(3, min(_int("min_test_obs",   5),  50)),
        features_to_track= features,
        confidence_level = max(0.50, min(_float("confidence_level", 0.95), 0.999)),
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
    """Load trades for all symbols and return flat FeatureRecord list."""
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
# GET /api/max-pain/walkforward/run
# ---------------------------------------------------------------------------

@walkforward_bp.route("/run", methods=["GET"])
@jwt_required()
def wf_run():
    """
    Full walk-forward validation with per-fold IS/OOS detail.

    Response shape:
      {
        "symbols", "window", "params", "n_total_obs", "n_folds",
        "folds": [
          {
            "fold_idx",
            "period": {"train_start", "train_end", "test_start", "test_end",
                       "n_train", "n_test"},
            "in_sample":     {"n_obs", "win_rate", "expectancy_pct", "std_pct",
                               "sharpe_approx", "feature_correlations",
                               "regime_distribution"},
            "out_of_sample": {same fields},
            "degradation":   {"expectancy_degradation_pct", "win_rate_delta",
                               "feature_correlation_decay", "regime_drift_tvd",
                               "oos_positive"}
          }, ...
        ],
        "aggregate": {
          "mean_is_expectancy_pct", "mean_oos_expectancy_pct",
          "std_oos_expectancy_pct", "oos_ci_low_pct", "oos_ci_high_pct",
          "degradation_ratio", "overfit_score", "robustness_score",
          "stability_score", "mean_regime_drift_tvd", "regime_drift_detected",
          "feature_decay", "overfit_detected", "fold_consistency_score"
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

    wf_params, err = _parse_wf_params()
    if err:
        return _err(err)

    filters = _common_filter_args()

    try:
        records = _load_records(syms, t_params, filters)
        result  = run_walkforward(records, wf_params, syms, filters["window"])
        return _ok(result.to_run_dict())

    except ValueError as exc:
        return _err(str(exc), code="INSUFFICIENT_DATA")
    except Exception as exc:
        logger.error("Walk-forward run error: %s", exc, exc_info=True)
        return _err(str(exc), status=500, code="WALKFORWARD_ERROR")


# ---------------------------------------------------------------------------
# GET /api/max-pain/walkforward/summary
# ---------------------------------------------------------------------------

@walkforward_bp.route("/summary", methods=["GET"])
@jwt_required()
def wf_summary():
    """
    Aggregate walk-forward statistics — lighter than /run (no per-fold detail).

    Response shape:
      {
        "symbols", "window", "params", "n_total_obs", "n_folds",
        "aggregate": { ... same as /run aggregate ... },
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

    wf_params, err = _parse_wf_params()
    if err:
        return _err(err)

    filters = _common_filter_args()

    try:
        records = _load_records(syms, t_params, filters)
        result  = run_walkforward(records, wf_params, syms, filters["window"])
        return _ok(result.to_summary_dict())

    except ValueError as exc:
        return _err(str(exc), code="INSUFFICIENT_DATA")
    except Exception as exc:
        logger.error("Walk-forward summary error: %s", exc, exc_info=True)
        return _err(str(exc), status=500, code="WALKFORWARD_ERROR")


# ---------------------------------------------------------------------------
# GET /api/max-pain/walkforward/stability
# ---------------------------------------------------------------------------

@walkforward_bp.route("/stability", methods=["GET"])
@jwt_required()
def wf_stability():
    """
    Time-series stability view across folds — optimised for trend plotting.

    Response shape:
      {
        "symbols", "window", "params", "n_total_obs", "n_folds",
        "stability": {
          "fold_indices":            [0, 1, 2, ...],
          "oos_expectancy_series":   [float | null, ...],
          "oos_win_rate_series":     [float | null, ...],
          "regime_drift_series":     [float, ...],
          "feature_correlation_is":  {"signal_dist_pct": [...], ...},
          "feature_correlation_oos": {"signal_dist_pct": [...], ...},
          "decay_series":            {"signal_dist_pct": [...], ...},
          "expectancy_trend":        float | null,
          "expectancy_trend_direction": "improving" | "decaying" | "stable"
        },
        "aggregate": {
          "robustness_score", "stability_score",
          "overfit_detected", "regime_drift_detected",
          "mean_oos_expectancy_pct"
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

    wf_params, err = _parse_wf_params()
    if err:
        return _err(err)

    filters = _common_filter_args()

    try:
        records = _load_records(syms, t_params, filters)
        result  = run_walkforward(records, wf_params, syms, filters["window"])
        return _ok(result.to_stability_dict())

    except ValueError as exc:
        return _err(str(exc), code="INSUFFICIENT_DATA")
    except Exception as exc:
        logger.error("Walk-forward stability error: %s", exc, exc_info=True)
        return _err(str(exc), status=500, code="WALKFORWARD_ERROR")
