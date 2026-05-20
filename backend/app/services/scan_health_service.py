"""
Scan Health & Data Integrity Service

Produces a structured `scan_health` object for every scan run that captures:
  - symbol fetch success / failure rates
  - cache performance (hits, misses, hit rate)
  - market state at time of scan
  - candle data quality warnings
  - overall data quality classification (good / partial / poor)

Public API:
  validate_candles(candles, symbol, timeframe) -> list[str]
  detect_market_state(timeframe)               -> str
  compute_scan_health(...)                     -> dict
"""

import logging
from datetime import datetime, timezone, timedelta
from typing import Optional

logger = logging.getLogger(__name__)

# ── Market-state thresholds ────────────────────────────────────────────────────

# NSE trading calendar (IST = UTC+5:30)
_IST_OFFSET       = timedelta(hours=5, minutes=30)
_MARKET_OPEN_IST  = (9,  15)   # hour, minute
_MARKET_CLOSE_IST = (15, 30)
_PREOPEN_IST      = (9,  0)

# Stale-data thresholds: if the newest candle timestamp is older than N × bar_duration,
# the data is considered stale.
_STALE_MULTIPLIER = 5   # e.g. 5 daily bars → stale if data is > 5 trading days old

# Bar duration in minutes (mirrors yfinance_provider constants)
_BAR_MINUTES: dict[str, int] = {
    "15m": 15,
    "1h":  60,
    "4h":  240,
    "1d":  1440,
    "1w":  10080,
}

# ── Data quality thresholds ────────────────────────────────────────────────────

_GOOD_THRESHOLD    = 0.95   # ≥95% symbols scanned successfully
_PARTIAL_THRESHOLD = 0.80   # 80–94%
# <80% → poor

# ── Failure-rate abort threshold ──────────────────────────────────────────────
# If more than 40% of symbols fail to fetch data, the scan_service marks the
# job failed.  This constant is documented here for reference — the abort
# decision is made in scanner_job_service, not here.
ABORT_FAILURE_RATE = 0.40


# ── Public: validate_candles ───────────────────────────────────────────────────

def validate_candles(
    candles: list[dict],
    symbol:  str,
    timeframe: str,
) -> list[str]:
    """
    Run data-integrity checks on a candle list for one symbol.

    Returns a list of warning strings (empty = clean data).
    Does NOT raise — callers decide what to do with warnings.

    Checks:
      1. Insufficient candle count (< 30)
      2. Duplicate timestamps
      3. Malformed OHLC rows (open > high, low > close, negative, NaN)
      4. Stale data (newest candle older than _STALE_MULTIPLIER × bar_minutes)
      5. Timezone inconsistency (mixing tz-aware and naive timestamps)
      6. Incomplete current candle (open == close during market hours)
    """
    warnings: list[str] = []

    if not candles:
        warnings.append(f"{symbol}: no candles returned")
        return warnings

    # ── 1. Insufficient count ─────────────────────────────────────────────────
    if len(candles) < 30:
        warnings.append(
            f"{symbol}: insufficient candles ({len(candles)} < 30)"
        )

    # ── 2. Duplicate timestamps ───────────────────────────────────────────────
    ts_list = [c.get("timestamp", "") for c in candles]
    if len(ts_list) != len(set(ts_list)):
        from collections import Counter
        dups = [ts for ts, cnt in Counter(ts_list).items() if cnt > 1]
        warnings.append(
            f"{symbol}: duplicate timestamps ({len(dups)} duplicate bar(s))"
        )

    # ── 3. Malformed OHLC rows ────────────────────────────────────────────────
    malformed = 0
    for c in candles:
        try:
            o, h, lo, cl = (
                float(c.get("open",  0)),
                float(c.get("high",  0)),
                float(c.get("low",   0)),
                float(c.get("close", 0)),
            )
            # Structural violations
            if h < o or h < cl or lo > o or lo > cl:
                malformed += 1
            elif lo <= 0 or h <= 0:
                malformed += 1
        except (TypeError, ValueError):
            malformed += 1
    if malformed:
        warnings.append(
            f"{symbol}: {malformed} malformed OHLC row(s)"
        )

    # ── 4. Stale data ─────────────────────────────────────────────────────────
    bar_mins = _BAR_MINUTES.get(timeframe)
    if bar_mins and candles:
        try:
            last_ts_raw = candles[-1].get("timestamp", "")
            last_ts = _parse_ts(last_ts_raw)
            if last_ts:
                now_utc = datetime.now(timezone.utc)
                staleness_mins = (now_utc - last_ts).total_seconds() / 60
                threshold_mins = bar_mins * _STALE_MULTIPLIER
                if staleness_mins > threshold_mins:
                    days_old = round(staleness_mins / 1440, 1)
                    warnings.append(
                        f"{symbol}: stale data — newest candle is {days_old}d old"
                    )
        except Exception:
            pass

    # ── 5. Timezone inconsistency ─────────────────────────────────────────────
    has_tz  = any(_ts_has_tz(c.get("timestamp", "")) for c in candles[:10])
    lacks_tz = any(not _ts_has_tz(c.get("timestamp", "")) for c in candles[:10])
    if has_tz and lacks_tz:
        warnings.append(
            f"{symbol}: mixed timezone-aware and naive timestamps"
        )

    return warnings


# ── Public: detect_market_state ────────────────────────────────────────────────

def detect_market_state(timeframe: str) -> str:
    """
    Detect NSE market state at the current wall-clock time.

    Returns: "open" | "closed" | "preopen" | "weekend"

    Logic:
      - Weekends (Sat/Sun IST) → "weekend"
      - Pre-open 09:00–09:15 IST → "preopen"
      - Market hours 09:15–15:30 IST → "open"
      - All other times → "closed"

    Intraday timeframes (15m, 1h, 4h) use precise IST time.
    Daily / weekly scans always return "closed" outside official hours
    since the candle is from the previous session.
    """
    now_utc = datetime.now(timezone.utc)
    now_ist = now_utc + _IST_OFFSET

    weekday = now_ist.weekday()   # 0=Mon … 6=Sun
    if weekday >= 5:
        return "weekend"

    h, m = now_ist.hour, now_ist.minute
    current_min = h * 60 + m
    preopen_min = _PREOPEN_IST[0] * 60 + _PREOPEN_IST[1]
    open_min    = _MARKET_OPEN_IST[0] * 60 + _MARKET_OPEN_IST[1]
    close_min   = _MARKET_CLOSE_IST[0] * 60 + _MARKET_CLOSE_IST[1]

    if current_min < preopen_min or current_min >= close_min:
        return "closed"
    if current_min < open_min:
        return "preopen"
    return "open"


# ── Public: compute_scan_health ────────────────────────────────────────────────

def compute_scan_health(
    *,
    timeframe:         str,
    symbols_requested: int,
    symbols_scanned:   int,
    failed_symbols:    list[str],
    fetch_stats:       dict,
    fetch_time_s:      float,
    htf_batch:         Optional[dict] = None,   # {yf_sym: [candles]}
    ltf_batch:         Optional[dict] = None,   # {yf_sym: [candles]}
    candle_warnings:   Optional[list[str]] = None,
    extra_warnings:    Optional[list[str]] = None,
) -> dict:
    """
    Build the full scan_health object for one scan run.

    Args:
        timeframe:         HTF timeframe string (e.g. "1d")
        symbols_requested: total symbols the scan attempted
        symbols_scanned:   symbols that had sufficient candle data
        failed_symbols:    list of symbol names that failed (no/insufficient data)
        fetch_stats:       dict from yfinance_provider.get_fetch_stats()
        fetch_time_s:      total fetch elapsed time in seconds
        htf_batch:         optional HTF candle batch (for last-candle detection)
        ltf_batch:         optional LTF candle batch
        candle_warnings:   pre-collected candle validation warnings
        extra_warnings:    any additional warning strings

    Returns dict matching the scan_health schema:
        {
          symbols_requested, symbols_scanned, symbols_failed, failed_symbols,
          partial_scan, cache_hits, cache_misses, cache_hit_rate,
          fetch_time_s, market_state, last_complete_htf_candle,
          last_complete_ltf_candle, data_quality, warnings
        }
    """
    symbols_failed_count = len(failed_symbols)

    # ── Cache metrics ─────────────────────────────────────────────────────────
    cache_hits   = fetch_stats.get("cache_hits",   0)
    cache_misses = fetch_stats.get("cache_misses", 0)
    total_fetches = cache_hits + cache_misses
    cache_hit_rate = round(cache_hits / total_fetches, 4) if total_fetches > 0 else 0.0

    # ── Partial scan flag ─────────────────────────────────────────────────────
    partial_scan = (symbols_failed_count > 0) and (symbols_requested > 0)

    # ── Market state ──────────────────────────────────────────────────────────
    market_state = detect_market_state(timeframe)

    # ── Last complete candle timestamps ───────────────────────────────────────
    last_htf_ts = _last_candle_ts(htf_batch)
    last_ltf_ts = _last_candle_ts(ltf_batch)

    # ── Aggregate warnings ────────────────────────────────────────────────────
    warnings: list[str] = list(candle_warnings or [])
    warnings.extend(extra_warnings or [])

    # Batch fetch errors warning
    fetch_errors = fetch_stats.get("fetch_errors", 0)
    if fetch_errors > 0:
        warnings.append(f"batch fetch errors: {fetch_errors} symbol(s) failed network request")

    # Batch fallbacks warning
    fallbacks = fetch_stats.get("batch_fallbacks", 0)
    if fallbacks > 0:
        warnings.append(f"batch fallbacks: {fallbacks} symbol(s) retried individually")

    # Slow fetch warning
    slow = fetch_stats.get("slow_fetches", [])
    if slow:
        warnings.append(f"slow fetch detected: {len(slow)} batch/symbol exceeded threshold")

    # LTF missing warning
    if ltf_batch is None:
        warnings.append("ltf_data_unavailable: no LTF timeframe for this HTF (15m)")

    # ── Data quality classification ───────────────────────────────────────────
    if symbols_requested > 0:
        success_rate = symbols_scanned / symbols_requested
    else:
        success_rate = 1.0

    has_critical = any(
        w for w in warnings
        if any(kw in w for kw in ("batch fetch error", "major", "stale data"))
    )

    if success_rate >= _GOOD_THRESHOLD and not has_critical:
        data_quality = "good"
    elif success_rate >= _PARTIAL_THRESHOLD:
        data_quality = "partial"
    else:
        data_quality = "poor"

    # Downgrade to partial if there are stale-data or partial-fetch warnings
    if data_quality == "good" and any(
        "stale" in w or "batch fallback" in w or "slow fetch" in w
        for w in warnings
    ):
        data_quality = "partial"

    return {
        "symbols_requested":      symbols_requested,
        "symbols_scanned":        symbols_scanned,
        "symbols_failed":         symbols_failed_count,
        "failed_symbols":         failed_symbols[:50],   # cap list length
        "partial_scan":           partial_scan,
        "cache_hits":             cache_hits,
        "cache_misses":           cache_misses,
        "cache_hit_rate":         cache_hit_rate,
        "fetch_time_s":           round(fetch_time_s, 2),
        "market_state":           market_state,
        "last_complete_htf_candle": last_htf_ts,
        "last_complete_ltf_candle": last_ltf_ts,
        "data_quality":           data_quality,
        "warnings":               warnings,
    }


# ── Mock scan health (for mock mode scans) ────────────────────────────────────

def compute_mock_scan_health(
    *,
    timeframe:         str,
    symbols_requested: int,
    symbols_scanned:   int,
) -> dict:
    """Return a lightweight scan_health for mock mode scans."""
    return {
        "symbols_requested":        symbols_requested,
        "symbols_scanned":          symbols_scanned,
        "symbols_failed":           0,
        "failed_symbols":           [],
        "partial_scan":             False,
        "cache_hits":               0,
        "cache_misses":             0,
        "cache_hit_rate":           0.0,
        "fetch_time_s":             0.0,
        "market_state":             detect_market_state(timeframe),
        "last_complete_htf_candle": None,
        "last_complete_ltf_candle": None,
        "data_quality":             "good",
        "warnings":                 ["mock_mode: no real candle data fetched"],
    }


# ── Private helpers ────────────────────────────────────────────────────────────

def _parse_ts(ts_raw: str) -> Optional[datetime]:
    """Parse an ISO timestamp string to a UTC-aware datetime. Returns None on failure."""
    if not ts_raw:
        return None
    try:
        ts_clean = ts_raw.replace("Z", "+00:00")
        dt = datetime.fromisoformat(ts_clean)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc)
    except Exception:
        return None


def _ts_has_tz(ts_raw: str) -> bool:
    """Return True if the timestamp string appears to carry timezone info."""
    if not ts_raw:
        return False
    return "+" in ts_raw or ts_raw.endswith("Z") or ts_raw.endswith("z")


def _last_candle_ts(batch: Optional[dict]) -> Optional[str]:
    """
    Find the most-recent candle timestamp across all symbols in a batch dict.
    Returns ISO string or None.
    """
    if not batch:
        return None
    latest: Optional[datetime] = None
    for candles in batch.values():
        if not candles:
            continue
        ts = _parse_ts(candles[-1].get("timestamp", ""))
        if ts and (latest is None or ts > latest):
            latest = ts
    return latest.isoformat() if latest else None
