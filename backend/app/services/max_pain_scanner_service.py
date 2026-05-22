"""
Max Pain Deviation Scanner Service
====================================
Orchestrates option-chain fetching, max pain calculation, and deviation
scanning across multiple symbols.

Data source: NSE option chain via headless Chromium (nse_playwright_service).
No per-user credentials required — the shared browser fetches for everyone.
"""

from __future__ import annotations

import logging
import time
from typing import Optional

from app.services.nse_option_chain_service import (
    OptionChainResult,
    NSEMarketClosedError,
)
from app.services import nse_playwright_service as nse_pw
from app.services.max_pain_engine import (
    MaxPainResult,
    calculate_max_pain,
    get_oi_walls,
)
from app.services.reversal_probability_engine import (
    calculate_reversal_score,
    days_until_expiry,
)

logger = logging.getLogger(__name__)

# Default F&O universe — top liquid names
DEFAULT_FO_UNIVERSE: list[str] = [
    "NIFTY", "BANKNIFTY", "FINNIFTY",
    "RELIANCE", "TCS", "INFY", "HDFCBANK", "ICICIBANK",
    "SBIN", "AXISBANK", "KOTAKBANK", "LT",
    "ITC", "BHARTIARTL", "MARUTI", "BAJFINANCE", "ASIANPAINT",
    "WIPRO", "HCLTECH", "TITAN", "NESTLEIND", "POWERGRID",
    "NTPC", "ONGC", "COALINDIA", "TATAMOTORS", "TATASTEEL",
    "ADANIPORTS", "ULTRACEMCO", "JSWSTEEL", "GRASIM", "HINDALCO",
    "DRREDDY", "CIPLA", "SUNPHARMA", "DIVISLAB", "APOLLOHOSP",
    "BPCL", "IOC", "HINDUNILVR", "PIDILITIND", "SIEMENS",
    "HAVELLS", "VOLTAS", "DABUR", "MARICO", "COLPAL",
]


# ── Helpers ───────────────────────────────────────────────────────────────────

def _oi_buildup_zones(chain: OptionChainResult, top_n: int = 5) -> dict:
    spot = chain.spot_price
    above = sorted(
        [s for s in chain.strikes if s.strike > spot],
        key=lambda s: s.ce.oi, reverse=True,
    )[:top_n]
    below = sorted(
        [s for s in chain.strikes if s.strike < spot],
        key=lambda s: s.pe.oi, reverse=True,
    )[:top_n]
    return {
        "resistance_zones": [{"strike": s.strike, "ce_oi": s.ce.oi} for s in above],
        "support_zones":    [{"strike": s.strike, "pe_oi": s.pe.oi} for s in below],
    }


def _classify_distance(distance_pct: float) -> str:
    if distance_pct >= 6:
        return "extreme"
    if distance_pct >= 4:
        return "high"
    if distance_pct >= 2:
        return "moderate"
    return "low"


def _oi_bias(ce_wall_oi: int, pe_wall_oi: int) -> str:
    if pe_wall_oi > ce_wall_oi * 1.3:
        return "bullish"
    if ce_wall_oi > pe_wall_oi * 1.3:
        return "bearish"
    return "neutral"


# ── Single-symbol scan ────────────────────────────────────────────────────────

_SKIP_BELOW_THRESHOLD = "below_threshold"
_SKIP_EMPTY_CHAIN     = "empty_chain"
_SKIP_MARKET_CLOSED   = "market_closed"


def _scan_symbol_internal(
    symbol: str,
    expiry: Optional[str] = None,
    threshold_pct: float  = 2.0,
) -> tuple[Optional[dict], Optional[str], Optional[str]]:
    """
    Returns a 3-tuple: (result_dict, skip_reason, error_message).
    Exactly one element is non-None.
    """
    t0 = time.monotonic()
    try:
        chain: OptionChainResult = nse_pw.get_option_chain(symbol.upper(), expiry=expiry)
        fetch_ms = (time.monotonic() - t0) * 1000

        if not chain.strikes:
            logger.warning("[SCAN] symbol=%s rows=0 SKIP empty_chain fetch_ms=%.0f", symbol, fetch_ms)
            return None, _SKIP_EMPTY_CHAIN, None

        mp: MaxPainResult = calculate_max_pain(chain)

        logger.info(
            "[SCAN] symbol=%s rows=%d spot=%.2f max_pain=%.2f distance_pct=%.2f%% "
            "pcr=%.3f expiry=%s fetch_ms=%.0f threshold=%.1f%%",
            symbol, len(chain.strikes), mp.spot_price, mp.max_pain,
            mp.distance_pct, mp.pcr, chain.expiry, fetch_ms, threshold_pct,
        )

        if mp.distance_pct < threshold_pct:
            logger.info(
                "[SCAN] symbol=%s SKIP below_threshold distance=%.3f%% < threshold=%.1f%%",
                symbol, mp.distance_pct, threshold_pct,
            )
            return None, _SKIP_BELOW_THRESHOLD, None

        total_ce_oi_change = sum(s.ce.oi_change for s in chain.strikes)
        total_pe_oi_change = sum(s.pe.oi_change for s in chain.strikes)

        ce_oi       = mp.ce_wall.oi if mp.ce_wall else 0
        pe_oi       = mp.pe_wall.oi if mp.pe_wall else 0
        oi_bias_str = _oi_bias(ce_oi, pe_oi)

        dte = days_until_expiry(chain.expiry)
        rev = calculate_reversal_score(
            distance_pct   = mp.distance_pct,
            pcr            = mp.pcr,
            oi_bias        = oi_bias_str,
            days_to_expiry = dte,
            spot_price     = mp.spot_price,
            max_pain       = mp.max_pain,
            ce_oi_change   = total_ce_oi_change,
            pe_oi_change   = total_pe_oi_change,
        )

        direction = "bearish" if mp.spot_price > mp.max_pain else "bullish"
        if mp.pcr > 1.2:
            pcr_bias = "bullish"
        elif mp.pcr < 0.8:
            pcr_bias = "bearish"
        else:
            pcr_bias = "neutral"

        result = {
            "symbol":             chain.symbol,
            "spot_price":         mp.spot_price,
            "max_pain":           mp.max_pain,
            "distance_pct":       mp.distance_pct,
            "distance_from_spot": mp.distance_from_spot,
            "distance_level":     _classify_distance(mp.distance_pct),
            "direction":          direction,
            "pcr":                mp.pcr,
            "pcr_bias":           pcr_bias,
            "oi_bias":            oi_bias_str,
            "expiry":             chain.expiry,
            "all_expiries":       chain.all_expiries,
            "days_to_expiry":     dte,
            "total_ce_oi":        mp.total_ce_oi,
            "total_pe_oi":        mp.total_pe_oi,
            "ce_oi_wall":         mp.ce_wall.strike  if mp.ce_wall else None,
            "pe_oi_wall":         mp.pe_wall.strike  if mp.pe_wall else None,
            "ce_oi_wall_oi":      mp.ce_wall.oi      if mp.ce_wall else None,
            "pe_oi_wall_oi":      mp.pe_wall.oi      if mp.pe_wall else None,
            "reversal_score":     rev["score"],
            "reversal_category":  rev["category"],
            "reversal_color":     rev["color"],
            "reversal_breakdown": rev["breakdown"],
            "oi_zones":           _oi_buildup_zones(chain),
            "pain_values":        [p.to_dict() for p in mp.pain_curve],
            "top_pain_strikes":   [p.to_dict() for p in mp.top_pain_strikes],
            "option_chain":       [s.to_dict() for s in chain.strikes],
            "timestamp":          chain.timestamp,
            "atm_ce_iv":          chain.atm_ce_iv,
            "atm_pe_iv":          chain.atm_pe_iv,
        }
        logger.info(
            "[SCAN] symbol=%s HIT distance=%.2f%% direction=%s pcr=%.3f "
            "rev_score=%s dte=%dd",
            symbol, mp.distance_pct, direction, mp.pcr, rev["score"], dte,
        )
        return result, None, None

    except NSEMarketClosedError as exc:
        fetch_ms = (time.monotonic() - t0) * 1000
        logger.warning("[SCAN] symbol=%s SKIP market_closed fetch_ms=%.0f — %s", symbol, fetch_ms, exc)
        return None, _SKIP_MARKET_CLOSED, None

    except Exception as exc:
        fetch_ms = (time.monotonic() - t0) * 1000
        logger.error("[SCAN] symbol=%s FAILED fetch_ms=%.0f error=%s", symbol, fetch_ms, exc)
        return None, None, str(exc)


def scan_symbol(
    symbol: str,
    expiry: Optional[str] = None,
    threshold_pct: float  = 2.0,
) -> Optional[dict]:
    result, _skip, _err = _scan_symbol_internal(symbol, expiry, threshold_pct)
    return result


# ── Multi-symbol scanner ──────────────────────────────────────────────────────

def run_scanner(
    symbols: Optional[list[str]] = None,
    threshold_pct: float = 2.0,
    expiry: Optional[str] = None,
) -> dict:
    """
    Run the deviation scanner across multiple symbols using NSE data
    fetched via headless Chromium.  No credentials required.

    Returns:
        { "results", "summary", "errors", "below_threshold", "market_closed", "metrics" }
    """
    target     = symbols or DEFAULT_FO_UNIVERSE
    scan_start = time.monotonic()

    logger.info(
        "[SCANNER] Starting NSE scan — symbols=%d threshold=%.1f%% expiry=%s",
        len(target), threshold_pct, expiry or "nearest",
    )

    results:         list[dict] = []
    errors:          list[dict] = []
    below_threshold: list[str]  = []
    market_closed:   list[str]  = []

    for sym in target:
        try:
            result, skip_reason, error_msg = _scan_symbol_internal(sym, expiry, threshold_pct)
            if result is not None:
                results.append(result)
            elif skip_reason == _SKIP_BELOW_THRESHOLD:
                below_threshold.append(sym)
            elif skip_reason == _SKIP_MARKET_CLOSED:
                market_closed.append(sym)
            elif error_msg is not None:
                if any(k in error_msg.lower() for k in ("market", "empty", "closed")):
                    market_closed.append(sym)
                else:
                    errors.append({"symbol": sym, "error": error_msg})
            else:
                errors.append({"symbol": sym, "error": f"skipped: {skip_reason}"})
        except Exception as exc:
            errors.append({"symbol": sym, "error": str(exc)})
            logger.error("[SCANNER] Unexpected error scanning %s: %s", sym, exc)

    results.sort(key=lambda x: x["distance_pct"], reverse=True)

    scan_elapsed_ms = (time.monotonic() - scan_start) * 1000
    fetch_success   = len(results) + len(below_threshold)

    logger.info(
        "[SCANNER] Scan complete — total=%d hits=%d below_threshold=%d "
        "market_closed=%d errors=%d elapsed=%.1fs",
        len(target), len(results), len(below_threshold),
        len(market_closed), len(errors), scan_elapsed_ms / 1000,
    )

    metrics = {
        "symbols_total":      len(target),
        "fetch_success":      fetch_success,
        "fetch_failed":       len(errors),
        "threshold_filtered": len(below_threshold),
        "returned_results":   len(results),
        "market_closed":      len(market_closed),
        "scan_elapsed_ms":    round(scan_elapsed_ms, 1),
        "avg_fetch_ms":       round(scan_elapsed_ms / max(len(target), 1), 1),
        "effective_workers":  1,
    }

    summary = build_summary(
        results,
        len(target),
        total_errors          = len(errors),
        total_below_threshold = len(below_threshold),
        total_market_closed   = len(market_closed),
    )

    return {
        "results":         results,
        "summary":         summary,
        "errors":          errors,
        "below_threshold": below_threshold,
        "market_closed":   market_closed,
        "metrics":         metrics,
    }


def build_summary(
    results: list[dict],
    total_scanned: int,
    total_errors: int = 0,
    total_below_threshold: int = 0,
    total_market_closed: int = 0,
) -> dict:
    base = {
        "total_scanned":         total_scanned,
        "total_hits":            len(results),
        "total_errors":          total_errors,
        "total_below_threshold": total_below_threshold,
        "total_market_closed":   total_market_closed,
        "highest_deviation":     None,
        "highest_pcr":           None,
        "strongest_bullish":     None,
        "strongest_bearish":     None,
    }
    if not results:
        return base

    bullish = [r for r in results if r["direction"] == "bullish"]
    bearish = [r for r in results if r["direction"] == "bearish"]

    base.update({
        "highest_deviation": results[0],
        "highest_pcr":       max(results, key=lambda x: x["pcr"]),
        "strongest_bullish": (max(bullish, key=lambda x: x["reversal_score"]) if bullish else None),
        "strongest_bearish": (max(bearish, key=lambda x: x["reversal_score"]) if bearish else None),
    })
    return base
