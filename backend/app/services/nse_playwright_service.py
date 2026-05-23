"""
NSE Option Chain — requests-based fetcher
==========================================
Uses Python requests (HTTP/1.1) instead of Playwright/Chromium.
Playwright's HTTP/2 causes ERR_HTTP2_PROTOCOL_ERROR on Windows Server
with Hyper-V virtual network adapters — requests bypasses this entirely.

Design:
  • Single persistent requests.Session per process (reuses cookies).
  • Session warmed by visiting NSE homepage + option-chain page.
  • RLock serialises all requests (session is not thread-safe for concurrent use).
  • 5-minute in-memory cache per symbol URL.
  • Auto re-warm every 25 minutes or on fetch errors.
"""
from __future__ import annotations

import json
import logging
import threading
import time
from datetime import datetime, timezone
from typing import Optional

import requests
import urllib3

from app.services.nse_option_chain_service import (
    OptionChainResult,
    StrikeRow,
    OptionLeg,
    NSEDataError,
    NSEFetchError,
    NSEMarketClosedError,
    _safe_float,
    _safe_int,
)

# Suppress SSL warnings (NSE cert chain can be noisy on Windows Server)
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

logger = logging.getLogger(__name__)

_BASE       = "https://www.nseindia.com"
_URL_INDEX  = _BASE + "/api/option-chain-indices?symbol={symbol}"
_URL_EQUITY = _BASE + "/api/option-chain-equities?symbol={symbol}"

_INDEX_SYMS = frozenset({
    "NIFTY", "BANKNIFTY", "FINNIFTY", "MIDCPNIFTY",
    "NIFTYNXT50", "SENSEX",
})

_CACHE_TTL   = 300       # 5 minutes per symbol
_SESSION_TTL = 25 * 60   # re-warm session every 25 min
_WARM_PAUSE  = 2         # seconds to pause after each NSE page load

_lock      = threading.RLock()
_session:  Optional[requests.Session] = None
_warmed    = False
_last_warm = 0.0

_cache: dict[str, tuple[dict, float]] = {}

_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept":          "*/*",
    "Accept-Language": "en-IN,en;q=0.9",
    "Accept-Encoding": "gzip, deflate, br",
    "Referer":         "https://www.nseindia.com/option-chain",
    "Connection":      "keep-alive",
}


# ── Session lifecycle ─────────────────────────────────────────────────────────

def _start():
    global _session, _warmed, _last_warm
    logger.info("[NSE-REQ] Creating new requests session...")
    if _session:
        try:
            _session.close()
        except Exception:
            pass
    _session = requests.Session()
    _session.headers.update(_HEADERS)
    _session.verify = False
    _warmed = False
    logger.info("[NSE-REQ] Session created.")


def _warm():
    global _warmed, _last_warm
    logger.info("[NSE-REQ] Warming NSE session (acquiring Akamai cookies)...")
    try:
        _session.get(_BASE + "/", timeout=15)
        time.sleep(_WARM_PAUSE)
    except Exception as exc:
        logger.warning("[NSE-REQ] Homepage warm failed (%s) — continuing anyway", str(exc)[:100])
    try:
        _session.get(_BASE + "/option-chain", timeout=15)
        time.sleep(_WARM_PAUSE)
    except Exception as exc:
        logger.warning("[NSE-REQ] Option-chain warm failed (%s) — continuing anyway", str(exc)[:100])
    _warmed    = True
    _last_warm = time.monotonic()
    logger.info("[NSE-REQ] NSE session warm complete.")


def _ensure_ready():
    """Start session and/or re-warm if needed. MUST be called inside _lock."""
    if _session is None:
        _start()
    if not _warmed or (time.monotonic() - _last_warm) > _SESSION_TTL:
        _warm()


# ── Fetch ─────────────────────────────────────────────────────────────────────

def _fetch(url: str) -> dict:
    resp = _session.get(url, timeout=20)

    if resp.status_code == 401 or resp.status_code == 403:
        raise NSEFetchError(f"NSE returned {resp.status_code} — session blocked, will re-warm")

    if resp.status_code != 200:
        raise NSEFetchError(f"NSE returned HTTP {resp.status_code}")

    content_type = resp.headers.get("Content-Type", "")
    raw_text = resp.text.strip()

    if not raw_text:
        raise NSEFetchError("NSE returned blank response — session may need re-warming")

    if "text/html" in content_type or raw_text.lower().startswith("<!doctype") or raw_text.lower().startswith("<html"):
        raise NSEFetchError("NSE returned HTML instead of JSON — Akamai blocked, will re-warm")

    try:
        data = json.loads(raw_text)
    except Exception:
        snippet = raw_text[:300]
        raise NSEDataError(f"NSE returned non-JSON: {snippet}")

    if not data or (isinstance(data, dict) and not data.get("records")):
        raise NSEFetchError("NSE returned empty/minimal data — Akamai session not validated, will re-warm")

    return data


def _get_raw(url: str) -> dict:
    """Return cached JSON, or fetch fresh with one retry on session failure."""
    cached = _cache.get(url)
    if cached and (time.monotonic() - cached[1]) < _CACHE_TTL:
        return cached[0]

    with _lock:
        cached = _cache.get(url)
        if cached and (time.monotonic() - cached[1]) < _CACHE_TTL:
            return cached[0]

        _ensure_ready()

        try:
            data = _fetch(url)
        except Exception as exc:
            logger.warning("[NSE-REQ] Fetch failed (%s); re-warming and retrying...", str(exc)[:120])
            time.sleep(2)
            _warm()
            time.sleep(1)
            data = _fetch(url)

        _cache[url] = (data, time.monotonic())
        return data


# ── Parser ────────────────────────────────────────────────────────────────────

def _parse(data: dict, symbol: str, expiry: Optional[str]) -> OptionChainResult:
    records  = data.get("records") or {}
    filtered = data.get("filtered") or {}

    all_expiries: list[str] = records.get("expiryDates") or []
    spot = _safe_float(
        records.get("underlyingValue") or filtered.get("underlyingValue")
    )
    timestamp = records.get("timestamp") or datetime.now(timezone.utc).isoformat()

    rows_raw = records.get("data") or []

    if expiry and expiry in all_expiries:
        chosen = expiry
    else:
        chosen = all_expiries[0] if all_expiries else None

    if chosen:
        rows_raw = [r for r in rows_raw if r.get("expiryDate") == chosen]

    if not rows_raw:
        raise NSEMarketClosedError(
            f"No option rows for {symbol} expiry={chosen} — market may be closed"
        )

    strike_rows: list[StrikeRow] = []
    for row in rows_raw:
        strike = _safe_float(row.get("strikePrice"))
        if strike <= 0:
            continue
        ce_raw = row.get("CE") or {}
        pe_raw = row.get("PE") or {}

        def _leg(r: dict) -> OptionLeg:
            return OptionLeg(
                oi        = _safe_int(r.get("openInterest")),
                oi_change = _safe_int(r.get("changeinOpenInterest")),
                volume    = _safe_int(r.get("totalTradedVolume")),
                iv        = _safe_float(r.get("impliedVolatility")),
                ltp       = _safe_float(r.get("lastPrice")),
                bid       = _safe_float(r.get("bidprice") or r.get("bid")),
                ask       = _safe_float(r.get("askPrice") or r.get("ask")),
                delta     = _safe_float(r.get("delta")),
                theta     = _safe_float(r.get("theta")),
                vega      = _safe_float(r.get("vega")),
            )

        strike_rows.append(StrikeRow(strike=strike, ce=_leg(ce_raw), pe=_leg(pe_raw)))

    strike_rows.sort(key=lambda r: r.strike)

    total_ce_oi  = sum(r.ce.oi     for r in strike_rows)
    total_pe_oi  = sum(r.pe.oi     for r in strike_rows)
    total_ce_vol = sum(r.ce.volume for r in strike_rows)
    total_pe_vol = sum(r.pe.volume for r in strike_rows)
    pcr = round(total_pe_oi / total_ce_oi, 4) if total_ce_oi else 0.0

    atm_row = (
        min(strike_rows, key=lambda r: abs(r.strike - spot))
        if spot > 0
        else strike_rows[len(strike_rows) // 2]
    )

    return OptionChainResult(
        symbol           = symbol.upper(),
        expiry           = chosen or "",
        all_expiries     = all_expiries,
        spot_price       = spot,
        timestamp        = timestamp,
        strikes          = strike_rows,
        total_ce_oi      = total_ce_oi,
        total_pe_oi      = total_pe_oi,
        total_ce_volume  = total_ce_vol,
        total_pe_volume  = total_pe_vol,
        pcr              = pcr,
        atm_strike       = atm_row.strike,
        atm_ce_iv        = atm_row.ce.iv,
        atm_pe_iv        = atm_row.pe.iv,
        fetched_from_cache = False,
    )


# ── Public API ────────────────────────────────────────────────────────────────

def _oc_url(symbol: str) -> str:
    sym = symbol.upper().strip()
    return (
        _URL_INDEX.format(symbol=sym)
        if sym in _INDEX_SYMS
        else _URL_EQUITY.format(symbol=sym)
    )


def get_expiries(symbol: str) -> list[str]:
    data = _get_raw(_oc_url(symbol))
    return (data.get("records") or {}).get("expiryDates") or []


def get_option_chain(symbol: str, expiry: Optional[str] = None) -> OptionChainResult:
    symbol = symbol.upper().strip()
    data   = _get_raw(_oc_url(symbol))
    return _parse(data, symbol, expiry)


def invalidate_cache(symbol: str = None):
    with _lock:
        if symbol:
            _cache.pop(_oc_url(symbol), None)
        else:
            _cache.clear()


def is_ready() -> bool:
    return _session is not None and _warmed


def shutdown():
    global _session, _warmed
    with _lock:
        if _session:
            try:
                _session.close()
            except Exception:
                pass
        _warmed = False
    logger.info("[NSE-REQ] Session closed.")
