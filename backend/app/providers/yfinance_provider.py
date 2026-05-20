"""
yfinance data provider.

Thin wrapper around yfinance that converts timeframe slugs to yfinance
interval strings, handles empty dataframes, and returns normalised OHLCV
records for downstream consumption.

Supported timeframes (must match scanner frontend dropdown values):
    15m  → "15m"   (last 60d max in yfinance free tier)
    1h   → "60m"   (last 730d)
    4h   → resampled from 1h data  (yfinance has no native 4h interval)
    1d   → "1d"    (full history)
    1w   → "1wk"

Performance features:
    - Redis candle cache with per-timeframe TTL
    - Batch download via yf.download() — one network call for all symbols
    - Per-symbol concurrent fallback when batch silently drops a ticker
    - Open/incomplete candle dropping
    - Fetch timing metrics (cache hits / misses / errors / slow fetches / fallbacks)
"""

import json
import logging
import os
import threading
import time as _time
from concurrent.futures import ThreadPoolExecutor, as_completed

import pandas as pd
import yfinance as yf

logger = logging.getLogger(__name__)

# ── Timeframe mapping ──────────────────────────────────────────────────────────

# Maps our internal slug → (yfinance_interval, yfinance_period)
_TF_MAP: dict[str, tuple[str, str]] = {
    "15m": ("15m", "60d"),
    "1h":  ("60m", "730d"),
    "4h":  ("60m", "730d"),   # fetched as 1h, then resampled
    "1d":  ("1d",  "5y"),
    "1w":  ("1wk", "10y"),
}

# Bar duration in minutes (used for open-candle detection)
_BAR_MINUTES: dict[str, int] = {
    "15m": 15,
    "1h":  60,
    "4h":  240,
    "1d":  1440,
    "1w":  10080,
}

# ── Redis candle cache ─────────────────────────────────────────────────────────

# Cache TTL per timeframe (seconds)
_CACHE_TTL: dict[str, int] = {
    "15m": 300,    # 5 min  — intraday, refresh often
    "1h":  300,    # 5 min
    "4h":  900,    # 15 min
    "1d":  900,    # 15 min
    "1w":  3600,   # 1 hour
}

_SLOW_FETCH_THRESHOLD = 5.0   # seconds — flag as slow if single fetch exceeds this

_redis_client = None
_redis_ok     = None   # None=untested, True=connected, False=unavailable

def _get_redis():
    """Lazy-init Redis client. Returns None if Redis is unavailable."""
    global _redis_client, _redis_ok
    if _redis_ok is False:
        return None
    if _redis_client is not None:
        return _redis_client
    try:
        import redis as _redis_lib
        url = os.environ.get("REDIS_URL", "redis://localhost:6379/0")
        c = _redis_lib.from_url(
            url,
            decode_responses=True,
            socket_connect_timeout=2,
            socket_timeout=2,
        )
        c.ping()
        _redis_client = c
        _redis_ok     = True
        logger.info("yfinance_provider: Redis candle cache connected (%s)", url)
        return _redis_client
    except Exception as exc:
        _redis_ok = False
        logger.warning(
            "yfinance_provider: Redis unavailable — candle cache disabled (%s)", exc
        )
        return None


def _cache_key(symbol: str, timeframe: str) -> str:
    return f"candles:v1:{symbol}:{timeframe}"


def _cache_get(symbol: str, timeframe: str) -> list[dict] | None:
    r = _get_redis()
    if r is None:
        return None
    try:
        raw = r.get(_cache_key(symbol, timeframe))
        if raw:
            return json.loads(raw)
    except Exception:
        pass
    return None


def _cache_set(symbol: str, timeframe: str, records: list[dict]) -> None:
    r = _get_redis()
    if r is None or not records:
        return
    ttl = _CACHE_TTL.get(timeframe, 300)
    try:
        r.setex(_cache_key(symbol, timeframe), ttl, json.dumps(records))
    except Exception:
        pass


# ── Fetch timing metrics ───────────────────────────────────────────────────────

_stats_lock   = threading.Lock()
_fetch_stats: dict = {
    "cache_hits":          0,
    "cache_misses":        0,
    "fetch_errors":        0,
    "batch_fallbacks":     0,    # symbols retried individually after batch failure
    "slow_fetches":        [],   # list of (symbol_or_batch_label, timeframe, seconds)
    "total_fetch_seconds": 0.0,
}


def reset_fetch_stats() -> None:
    """Reset all fetch counters. Call before a scan run to get per-run metrics."""
    with _stats_lock:
        _fetch_stats.update({
            "cache_hits":          0,
            "cache_misses":        0,
            "fetch_errors":        0,
            "batch_fallbacks":     0,
            "slow_fetches":        [],
            "total_fetch_seconds": 0.0,
        })


def get_fetch_stats() -> dict:
    """Return a snapshot of current fetch metrics."""
    with _stats_lock:
        s = dict(_fetch_stats)
        s["slow_fetches"] = list(s["slow_fetches"])
        return s


# ── Open-candle dropping ───────────────────────────────────────────────────────

def _drop_open_candle(records: list[dict], timeframe: str) -> list[dict]:
    """
    Drop the last candle if it is an incomplete (still-open) bar.

    yfinance includes the current partial bar during live market hours.
    We detect this by checking if: last_bar_open_time + bar_duration > now_utc.
    If so the bar has not closed yet → drop it.

    Safe to call any time; if detection fails records are returned unchanged.
    """
    if not records:
        return records
    bar_mins = _BAR_MINUTES.get(timeframe)
    if not bar_mins:
        return records
    try:
        last_ts = pd.Timestamp(records[-1]["timestamp"])
        if last_ts.tzinfo is None:
            last_ts = last_ts.tz_localize("UTC")
        now_utc = pd.Timestamp.now(tz="UTC")
        bar_end = last_ts + pd.Timedelta(minutes=bar_mins)
        if now_utc < bar_end:
            logger.debug(
                "yfinance_provider: dropped open bar %s for %s (closes %s)",
                records[-1]["timestamp"], timeframe, bar_end,
            )
            return records[:-1]
    except Exception:
        pass
    return records


# ── Main API ───────────────────────────────────────────────────────────────────

def get_candles(
    yfinance_symbol: str,
    timeframe: str = "1d",
    limit: int = 200,
    skip_cache: bool = False,
) -> list[dict]:
    """
    Fetch OHLCV candles for a single yfinance symbol.

    Checks Redis cache first (unless skip_cache=True).
    Falls back to a live yfinance Ticker.history() call on cache miss.
    Open/incomplete bars are automatically dropped.

    Args:
        yfinance_symbol: e.g. "RELIANCE.NS", "TCS.NS"
        timeframe: one of "15m", "1h", "4h", "1d", "1w"
        limit: number of most-recent *closed* candles to return
        skip_cache: bypass Redis cache (force live fetch)

    Returns:
        List of dicts with keys: timestamp, open, high, low, close, volume
        Returns [] on any error or insufficient data.
    """
    if timeframe not in _TF_MAP:
        logger.warning(
            "yfinance_provider: unsupported timeframe '%s' for %s",
            timeframe, yfinance_symbol,
        )
        return []

    # ── Cache check ───────────────────────────────────────────────────────────
    if not skip_cache:
        cached = _cache_get(yfinance_symbol, timeframe)
        if cached is not None:
            with _stats_lock:
                _fetch_stats["cache_hits"] += 1
            records = cached[-limit:] if len(cached) > limit else cached
            return _drop_open_candle(records, timeframe)

    with _stats_lock:
        _fetch_stats["cache_misses"] += 1

    # ── Live fetch ────────────────────────────────────────────────────────────
    yf_interval, yf_period = _TF_MAP[timeframe]
    t0 = _time.monotonic()

    try:
        ticker = yf.Ticker(yfinance_symbol)
        df = ticker.history(period=yf_period, interval=yf_interval, auto_adjust=True)

        elapsed = _time.monotonic() - t0
        with _stats_lock:
            _fetch_stats["total_fetch_seconds"] += elapsed
            if elapsed >= _SLOW_FETCH_THRESHOLD:
                _fetch_stats["slow_fetches"].append(
                    (yfinance_symbol, timeframe, round(elapsed, 2))
                )

        if df is None or df.empty:
            logger.warning(
                "yfinance_provider: no data returned for %s (%s)",
                yfinance_symbol, timeframe,
            )
            return []

        # Resample 1h → 4h if needed
        if timeframe == "4h":
            df = _resample_to_4h(df)

        records = _df_to_records(df)

        # Cache the full record set (before limit trim, after open-candle drop)
        records = _drop_open_candle(records, timeframe)
        _cache_set(yfinance_symbol, timeframe, records)

        return records[-limit:] if len(records) > limit else records

    except Exception as exc:
        with _stats_lock:
            _fetch_stats["fetch_errors"] += 1
        logger.error(
            "yfinance_provider: error fetching %s (%s) — %s",
            yfinance_symbol, timeframe, exc,
        )
        return []


def get_candles_multi(
    yfinance_symbols: list[str],
    timeframe: str = "1d",
    limit: int = 200,
    skip_cache: bool = False,
) -> dict[str, list[dict]]:
    """
    Batch-fetch candles for multiple symbols.

    Strategy:
      1. Check Redis cache for each symbol — return cached results immediately.
      2. For symbols not in cache, use yf.download() (single network call for
         all remaining symbols, significantly faster than N individual calls).
      3. Write all newly-fetched results back to cache.
      4. Drop open/incomplete candles on all results.

    Returns:
        { "RELIANCE.NS": [...candles...], "TCS.NS": [...], ... }
        Symbols with no data return [].
    """
    if not yfinance_symbols:
        return {}

    if timeframe not in _TF_MAP:
        logger.warning("yfinance_provider: unsupported timeframe '%s'", timeframe)
        return {}

    result:   dict[str, list[dict]] = {}
    to_fetch: list[str]             = []

    # ── Phase 1: cache lookup ─────────────────────────────────────────────────
    if not skip_cache:
        for sym in yfinance_symbols:
            cached = _cache_get(sym, timeframe)
            if cached is not None:
                with _stats_lock:
                    _fetch_stats["cache_hits"] += 1
                records = cached[-limit:] if len(cached) > limit else cached
                result[sym] = _drop_open_candle(records, timeframe)
            else:
                with _stats_lock:
                    _fetch_stats["cache_misses"] += 1
                to_fetch.append(sym)
    else:
        with _stats_lock:
            _fetch_stats["cache_misses"] += len(yfinance_symbols)
        to_fetch = list(yfinance_symbols)

    if not to_fetch:
        logger.debug(
            "yfinance_provider: batch %s — all %d symbols served from cache",
            timeframe, len(yfinance_symbols),
        )
        return result

    logger.debug(
        "yfinance_provider: batch %s — %d cache hits, %d to fetch",
        timeframe, len(result), len(to_fetch),
    )

    # ── Phase 2: batch live fetch ─────────────────────────────────────────────
    yf_interval, yf_period = _TF_MAP[timeframe]
    t0 = _time.monotonic()

    try:
        raw = yf.download(
            tickers=to_fetch,
            period=yf_period,
            interval=yf_interval,
            auto_adjust=True,
            group_by="ticker",
            threads=True,
            progress=False,
        )
    except Exception as exc:
        elapsed = _time.monotonic() - t0
        logger.error("yfinance_provider: batch download failed (%s) — %s", timeframe, exc)
        with _stats_lock:
            _fetch_stats["fetch_errors"]        += len(to_fetch)
            _fetch_stats["total_fetch_seconds"] += elapsed
        for sym in to_fetch:
            result[sym] = []
        return result

    elapsed = _time.monotonic() - t0
    with _stats_lock:
        _fetch_stats["total_fetch_seconds"] += elapsed
        if elapsed >= _SLOW_FETCH_THRESHOLD * 3:   # higher threshold for a full batch
            _fetch_stats["slow_fetches"].append(
                (f"BATCH[{len(to_fetch)}]", timeframe, round(elapsed, 2))
            )

    # ── Phase 3: parse, cache, trim ───────────────────────────────────────────
    single = len(to_fetch) == 1

    for sym in to_fetch:
        try:
            if single:
                df = raw
            else:
                # Multi-ticker download: MultiIndex columns (field, ticker)
                top_level = raw.columns.get_level_values(0)
                df = raw[sym] if sym in top_level else pd.DataFrame()

            if df is None or df.empty:
                result[sym] = []
                continue

            if timeframe == "4h":
                df = _resample_to_4h(df)

            records = _df_to_records(df)
            records = _drop_open_candle(records, timeframe)

            # Cache full set before limit trim
            _cache_set(sym, timeframe, records)

            result[sym] = records[-limit:] if len(records) > limit else records

        except Exception as exc:
            logger.warning(
                "yfinance_provider: failed to process %s — %s", sym, exc
            )
            result[sym] = []

    # ── Phase 4: concurrent per-symbol fallback for batch-empty results ───────
    # yf.download() silently fails for some tickers in large batches (returns
    # None or raises TypeError inside the MultiIndex slice). Any symbol that
    # came back empty from the batch is retried with an individual Ticker call,
    # run concurrently via ThreadPoolExecutor so the fallback stays fast.
    need_fallback = [sym for sym in to_fetch if not result.get(sym)]
    if need_fallback:
        with _stats_lock:
            _fetch_stats["batch_fallbacks"] += len(need_fallback)
        logger.debug(
            "yfinance_provider: batch %s — %d symbols need individual fallback",
            timeframe, len(need_fallback),
        )

        def _fetch_one(sym: str) -> tuple[str, list[dict]]:
            """Individual Ticker.history() call used as batch fallback."""
            try:
                ticker = yf.Ticker(sym)
                df = ticker.history(
                    period=yf_period, interval=yf_interval, auto_adjust=True
                )
                if df is None or df.empty:
                    return sym, []
                if timeframe == "4h":
                    df = _resample_to_4h(df)
                records = _df_to_records(df)
                records = _drop_open_candle(records, timeframe)
                _cache_set(sym, timeframe, records)
                return sym, (records[-limit:] if len(records) > limit else records)
            except Exception as exc2:
                logger.warning(
                    "yfinance_provider: individual fallback failed %s — %s", sym, exc2
                )
                return sym, []

        max_workers = min(len(need_fallback), 12)   # cap concurrency
        fb_t0 = _time.monotonic()
        with ThreadPoolExecutor(max_workers=max_workers) as pool:
            futures = {pool.submit(_fetch_one, sym): sym for sym in need_fallback}
            for fut in as_completed(futures):
                sym, records = fut.result()
                result[sym] = records
        fb_elapsed = _time.monotonic() - fb_t0
        with _stats_lock:
            _fetch_stats["total_fetch_seconds"] += fb_elapsed
        logger.debug(
            "yfinance_provider: fallback complete %.1fs  recovered=%d",
            fb_elapsed,
            sum(1 for sym in need_fallback if result.get(sym)),
        )

    return result


# ── Helpers ────────────────────────────────────────────────────────────────────

def _resample_to_4h(df: pd.DataFrame) -> pd.DataFrame:
    """Resample a 1h OHLCV dataframe to 4h bars."""
    df = df.copy()
    df.index = pd.to_datetime(df.index)
    resampled = df.resample("4h", closed="left", label="left").agg({
        "Open":   "first",
        "High":   "max",
        "Low":    "min",
        "Close":  "last",
        "Volume": "sum",
    }).dropna(subset=["Open"])
    return resampled


def _df_to_records(df: pd.DataFrame) -> list[dict]:
    """Convert a yfinance OHLCV dataframe to a list of plain dicts."""
    records = []
    for ts, row in df.iterrows():
        try:
            records.append({
                "timestamp": pd.Timestamp(ts).isoformat(),
                "open":      float(row["Open"]),
                "high":      float(row["High"]),
                "low":       float(row["Low"]),
                "close":     float(row["Close"]),
                "volume":    int(row["Volume"]) if not pd.isna(row["Volume"]) else 0,
            })
        except Exception:
            continue   # skip malformed rows silently
    return records
