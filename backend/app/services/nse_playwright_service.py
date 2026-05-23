"""
NSE Option Chain — Playwright fetcher
=======================================
Runs a single headless Chromium browser to fetch NSE option-chain data.
Akamai's _abck cookie is validated by the real browser JS engine.

Design:
  • One persistent BrowserContext per server process.
  • Session warmed by visiting NSE homepage (lets Akamai JS validate cookies).
  • API calls use page.goto() so Akamai sees a real browser request, not plain HTTP.
    (context.request bypasses JS challenge validation — always returns empty data.)
  • RLock serialises all browser operations (Playwright sync API is NOT thread-safe).
  • 5-minute in-memory cache per symbol URL.
  • Auto re-warm every 25 minutes or on stale-session errors.
"""
from __future__ import annotations

import json
import logging
import threading
import time
from datetime import datetime, timezone
from typing import Optional

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

logger = logging.getLogger(__name__)

_BASE       = "https://www.nseindia.com"
_URL_INDEX  = _BASE + "/api/option-chain-indices?symbol={symbol}"
_URL_EQUITY = _BASE + "/api/option-chain-equities?symbol={symbol}"

_INDEX_SYMS = frozenset({
    "NIFTY", "BANKNIFTY", "FINNIFTY", "MIDCPNIFTY",
    "NIFTYNXT50", "SENSEX",
})

_CACHE_TTL      = 300       # 5 minutes per symbol
_SESSION_TTL    = 25 * 60   # re-warm session every 25 min
_WARM_PAUSE     = 3         # seconds to pause after each NSE page load

_lock      = threading.RLock()
_pw        = None
_browser   = None
_ctx       = None
_page      = None
_warmed    = False
_last_warm = 0.0

_cache: dict[str, tuple[dict, float]] = {}


# ── Browser lifecycle ─────────────────────────────────────────────────────────

def _start():
    global _pw, _browser, _ctx, _page, _warmed, _last_warm
    from playwright.sync_api import sync_playwright

    logger.info("[NSE-PW] Launching Chromium headless browser...")
    if _pw:
        try:
            _pw.stop()
        except Exception:
            pass

    _pw      = sync_playwright().start()
    _browser = _pw.firefox.launch(headless=True)
    _ctx = _browser.new_context(
        user_agent=(
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:125.0) "
            "Gecko/20100101 Firefox/125.0"
        ),
        viewport={"width": 1280, "height": 900},
        locale="en-IN",
        timezone_id="Asia/Kolkata",
        extra_http_headers={
            "Accept-Language": "en-IN,en;q=0.9",
        },
    )
    _page   = _ctx.new_page()
    _warmed = False
    logger.info("[NSE-PW] Chromium started.")


def _warm():
    global _warmed, _last_warm
    logger.info("[NSE-PW] Warming NSE session (letting Akamai JS validate)...")
    # 1. Visit NSE homepage — triggers Akamai JS, sets _abck cookie
    _page.goto(_BASE + "/", wait_until="domcontentloaded", timeout=30_000)
    time.sleep(_WARM_PAUSE)
    # 2. Visit the option-chain page — runs the JS that Akamai validates for API calls
    _page.goto(
        _BASE + "/option-chain",
        wait_until="domcontentloaded",
        timeout=30_000,
    )
    time.sleep(_WARM_PAUSE)
    _warmed    = True
    _last_warm = time.monotonic()
    logger.info("[NSE-PW] NSE session warmed successfully.")


def _ensure_ready():
    """Start browser and/or re-warm session if needed. MUST be called inside _lock."""
    if _browser is None or not _browser.is_connected():
        _start()
    if not _warmed or (time.monotonic() - _last_warm) > _SESSION_TTL:
        _warm()


# ── Browser-native fetch ──────────────────────────────────────────────────────

def _fetch(url: str) -> dict:
    """
    Navigate the browser page directly to the NSE API URL.

    Using page.goto() (not context.request) is critical: Akamai's _abck cookie
    is only marked valid after the browser JS engine runs the challenge.  A plain
    HTTP request — even with the cookie attached — returns HTTP 200 with empty /
    fake JSON because the cookie is not JS-validated for that request path.
    page.goto() goes through the full browser stack, so Akamai accepts it.
    """
    _page.goto(url, wait_until="domcontentloaded", timeout=25_000)

    # The browser renders the raw JSON as a <pre> or plain body text.
    try:
        raw_text = _page.evaluate("() => document.body.innerText")
    except Exception:
        raw_text = _page.content()

    if not raw_text or not raw_text.strip():
        raise NSEFetchError("NSE returned blank page — session may need re-warming")

    try:
        data = json.loads(raw_text)
    except Exception:
        snippet = raw_text[:300]
        # HTML response means Akamai is blocking / redirecting
        if "<html" in snippet.lower() or "<!doctype" in snippet.lower():
            raise NSEFetchError(
                "NSE returned HTML instead of JSON — Akamai blocked the request, will re-warm"
            )
        raise NSEDataError(f"NSE returned non-JSON: {snippet}")

    # Akamai-blocked responses come back as HTTP 200 with {{}} or minimal records
    if not data or (isinstance(data, dict) and not data.get("records")):
        raise NSEFetchError(
            "NSE returned empty/minimal data — Akamai session not fully validated, will re-warm"
        )

    return data


def _get_raw(url: str) -> dict:
    """Return cached JSON, or fetch fresh with one retry on session failure."""
    # Fast path: check cache without lock
    cached = _cache.get(url)
    if cached and (time.monotonic() - cached[1]) < _CACHE_TTL:
        return cached[0]

    with _lock:
        # Double-check inside lock (another thread may have just populated it)
        cached = _cache.get(url)
        if cached and (time.monotonic() - cached[1]) < _CACHE_TTL:
            return cached[0]

        _ensure_ready()

        try:
            data = _fetch(url)
        except Exception as exc:
            # Any navigation error (NS_ERROR_NET_RESET, HTTP2 error, NSEFetchError)
            # means Akamai killed the session — re-warm once and retry
            err_str = str(exc)
            logger.warning("[NSE-PW] Fetch failed (%s); re-warming and retrying...", err_str[:120])
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

    # Pick expiry
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
    """Return all expiry date strings for symbol (nearest first)."""
    data = _get_raw(_oc_url(symbol))
    return (data.get("records") or {}).get("expiryDates") or []


def get_option_chain(symbol: str, expiry: Optional[str] = None) -> OptionChainResult:
    """Fetch full option chain from NSE via headless browser. Returns OptionChainResult."""
    symbol = symbol.upper().strip()
    data   = _get_raw(_oc_url(symbol))
    return _parse(data, symbol, expiry)


def invalidate_cache(symbol: str = None):
    """Clear cache entry for one symbol, or all entries if symbol is None."""
    with _lock:
        if symbol:
            _cache.pop(_oc_url(symbol), None)
        else:
            _cache.clear()


def is_ready() -> bool:
    """True if the browser is running and the session has been warmed."""
    return _browser is not None and _browser.is_connected() and _warmed


def shutdown():
    """Cleanly close the browser. Call on app teardown."""
    global _browser, _pw, _warmed
    with _lock:
        if _browser:
            try:
                _browser.close()
            except Exception:
                pass
        if _pw:
            try:
                _pw.stop()
            except Exception:
                pass
        _warmed = False
    logger.info("[NSE-PW] Browser shut down.")
