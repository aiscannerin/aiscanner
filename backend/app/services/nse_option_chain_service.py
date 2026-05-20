"""
NSE Option Chain Fetcher Service
=================================
Production-grade live data ingestion from NSE India.

Public API (module-level helpers wrapping the singleton service):
    get_option_chain(symbol, expiry=None)  -> OptionChainResult
    get_expiries(symbol)                   -> list[str]
    get_nearest_expiry(symbol)             -> str
    get_atm_strike(symbol, expiry=None)    -> float

All methods are thread-safe and share a single cached NSE session.
"""

from __future__ import annotations

import logging
import math
import random
import threading
import time
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from typing import Optional

# Prefer curl_cffi for browser-grade TLS fingerprinting (defeats Akamai/CF bot checks).
# Fall back to requests if not installed.
try:
    from curl_cffi import requests as _http_lib
    _USING_CURL_CFFI = True
    logger_import = logging.getLogger(__name__)
    logger_import.info("NSE HTTP backend: curl_cffi (browser-grade TLS)")
except ImportError:
    import requests as _http_lib          # type: ignore[no-redef]
    from requests.adapters import HTTPAdapter
    from urllib3.util.retry import Retry
    _USING_CURL_CFFI = False
    logger_import = logging.getLogger(__name__)
    logger_import.warning("curl_cffi not installed — falling back to requests (reduced anti-bot capability)")

from app.services.option_chain_monitor import monitor
from app.services.option_chain_validator import (
    validate_raw_response,
    validate_nse_json_structure,
    validate_parsed_chain,
)

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

# NSE API endpoints
_URL_INDEX_CHAIN  = "https://www.nseindia.com/api/option-chain-indices"
_URL_EQUITY_CHAIN = "https://www.nseindia.com/api/option-chain-equities"
_URL_HOMEPAGE     = "https://www.nseindia.com"
_URL_OC_PAGE      = "https://www.nseindia.com/option-chain"

# Symbols served by the indices endpoint
INDEX_SYMBOLS: frozenset[str] = frozenset(
    {"NIFTY", "BANKNIFTY", "FINNIFTY", "MIDCPNIFTY", "NIFTYNXT50"}
)

# F&O universe — top liquid names used as default scan targets
FO_UNIVERSE: list[str] = [
    "NIFTY", "BANKNIFTY", "FINNIFTY",
    "RELIANCE", "TCS", "INFY", "HDFCBANK", "ICICIBANK",
    "SBIN", "AXISBANK", "KOTAKBANK", "LT", "ITC",
    "BHARTIARTL", "MARUTI", "BAJFINANCE", "ASIANPAINT", "WIPRO",
    "HCLTECH", "TITAN", "NESTLEIND", "POWERGRID", "NTPC",
    "ONGC", "COALINDIA", "TATAMOTORS", "TATASTEEL", "ADANIPORTS",
    "ULTRACEMCO", "JSWSTEEL", "GRASIM", "HINDALCO", "DRREDDY",
    "CIPLA", "SUNPHARMA", "DIVISLAB", "APOLLOHOSP", "BPCL",
    "IOC", "HINDUNILVR", "PIDILITIND", "SIEMENS", "HAVELLS",
]

# NSE market hours (IST)
_MARKET_OPEN_IST  = (9, 15)
_MARKET_CLOSE_IST = (15, 30)
_IST_OFFSET_SECS  = 19800   # UTC+5:30

# Request config
_REQUEST_TIMEOUT   = 20          # seconds per attempt
_COOKIE_TTL        = 270         # seconds before proactive cookie refresh
_RATE_LIMIT_CODES  = {429, 503}  # HTTP codes indicating back-off needed
_BLOCK_CODES       = {403}       # hard blocks — force full session reset
_SESSION_TTL       = 1800        # force session rebuild every 30 minutes

# Cache config
_CACHE_TTL_SECS    = 20          # default cache lifetime (seconds)
_CACHE_MAX_ENTRIES = 256

# ---------------------------------------------------------------------------
# Browser-like headers
# ---------------------------------------------------------------------------

# Multiple realistic UA strings rotated per session init to avoid fingerprinting
_USER_AGENTS = [
    (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/123.0.0.0 Safari/537.36 Edg/123.0.0.0"
    ),
    (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    (
        "Mozilla/5.0 (X11; Linux x86_64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
]

def _ua_to_sec_ch_ua(ua: str) -> str:
    """
    Derive a plausible sec-ch-ua header from a User-Agent string.
    Covers Chrome and Edge UA patterns used in _USER_AGENTS.
    """
    import re
    m = re.search(r"Chrome/(\d+)", ua)
    version = m.group(1) if m else "124"
    if "Edg/" in ua:
        edg = re.search(r"Edg/(\d+)", ua)
        ev = edg.group(1) if edg else version
        return (
            f'"Microsoft Edge";v="{ev}", "Chromium";v="{version}", '
            f'"Not-A.Brand";v="99"'
        )
    return (
        f'"Google Chrome";v="{version}", "Chromium";v="{version}", '
        f'"Not-A.Brand";v="99"'
    )


_BASE_HEADERS = {
    "Accept":            "application/json, text/plain, */*",
    "Accept-Language":   "en-US,en;q=0.9,hi;q=0.8",
    "Accept-Encoding":   "gzip, deflate, br",
    "Referer":           "https://www.nseindia.com/option-chain",
    "X-Requested-With":  "XMLHttpRequest",
    "Connection":        "keep-alive",
    "Cache-Control":     "no-cache",
    "Pragma":            "no-cache",
    "DNT":               "1",
    "sec-ch-ua-mobile":  "?0",
    "Sec-Fetch-Dest":    "empty",
    "Sec-Fetch-Mode":    "cors",
    "Sec-Fetch-Site":    "same-origin",
    "sec-ch-ua-platform": '"Windows"',
}

# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------

@dataclass
class OptionLeg:
    """Normalised data for one side (CE or PE) of a strike."""
    oi:         int   = 0
    oi_change:  int   = 0
    volume:     int   = 0
    iv:         float = 0.0
    ltp:        float = 0.0
    bid:        float = 0.0
    ask:        float = 0.0
    delta:      float = 0.0   # populated if available from NSE
    theta:      float = 0.0
    vega:       float = 0.0

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class StrikeRow:
    """One strike row in the option chain — both CE and PE sides."""
    strike: float
    ce:     OptionLeg = field(default_factory=OptionLeg)
    pe:     OptionLeg = field(default_factory=OptionLeg)

    def to_dict(self) -> dict:
        return {
            "strike": self.strike,
            "ce":     self.ce.to_dict(),
            "pe":     self.pe.to_dict(),
        }


@dataclass
class OptionChainResult:
    """
    Fully normalised option chain for one symbol + expiry.

    All fields are typed; no None values in numeric slots (use 0 / 0.0).
    """
    symbol:      str
    expiry:      str
    all_expiries: list[str]
    spot_price:  float
    timestamp:   str

    # Chain data — ordered by strike ascending
    strikes: list[StrikeRow] = field(default_factory=list)

    # Aggregates (pre-computed for convenience)
    total_ce_oi:     int   = 0
    total_pe_oi:     int   = 0
    total_ce_volume: int   = 0
    total_pe_volume: int   = 0
    pcr:             float = 0.0   # PE OI / CE OI

    # ATM info
    atm_strike:  float = 0.0
    atm_ce_iv:   float = 0.0
    atm_pe_iv:   float = 0.0

    # Source metadata
    fetched_from_cache: bool = False

    def to_dict(self) -> dict:
        return {
            "symbol":            self.symbol,
            "expiry":            self.expiry,
            "all_expiries":      self.all_expiries,
            "spot_price":        self.spot_price,
            "timestamp":         self.timestamp,
            "total_ce_oi":       self.total_ce_oi,
            "total_pe_oi":       self.total_pe_oi,
            "total_ce_volume":   self.total_ce_volume,
            "total_pe_volume":   self.total_pe_volume,
            "pcr":               self.pcr,
            "atm_strike":        self.atm_strike,
            "atm_ce_iv":         self.atm_ce_iv,
            "atm_pe_iv":         self.atm_pe_iv,
            "fetched_from_cache": self.fetched_from_cache,
            "strikes":           [s.to_dict() for s in self.strikes],
        }


# ---------------------------------------------------------------------------
# Exceptions
# ---------------------------------------------------------------------------

class NSEFetchError(Exception):
    """Raised when the NSE API cannot be reached after all retries."""

class NSERateLimitError(NSEFetchError):
    """Raised when NSE responds with a rate-limit / throttle signal."""

class NSEBlockedError(NSEFetchError):
    """Raised when NSE returns a hard 403 block."""

class NSEDataError(NSEFetchError):
    """Raised when the response is reachable but data is malformed."""

class NSECaptchaError(NSEDataError):
    """Raised when NSE serves a captcha / bot-check page instead of JSON."""

class NSEMalformedPayloadError(NSEDataError):
    """
    Raised when the JSON is parseable but no usable option-chain rows can be
    extracted from any known NSE payload shape.
    Carries ``response_type`` for caller diagnostics.
    """
    def __init__(self, message: str, response_type: str = "unknown"):
        super().__init__(message)
        self.response_type = response_type

class NSERetryExhaustedError(NSEFetchError):
    """
    Raised after all malformed-payload retries are spent.
    The last underlying cause is chained via __cause__.
    """

class NSEMarketClosedError(NSEDataError):
    """
    Raised when NSE returns an empty JSON object `{}` — the documented
    off-hours response indicating no option-chain data is available
    (market is closed or pre-open).
    """


# ---------------------------------------------------------------------------
# In-memory cache (thread-safe, TTL-based)
# ---------------------------------------------------------------------------

class _TTLCache:
    """
    Simple LRU-style TTL cache for option chain responses.

    Keys: str  (symbol:expiry)
    Values: (OptionChainResult, expiry_ts)
    """

    def __init__(self, ttl: float = _CACHE_TTL_SECS, max_entries: int = _CACHE_MAX_ENTRIES):
        self._store:      dict[str, tuple[OptionChainResult, float]] = {}
        self._lock        = threading.Lock()
        self._ttl         = ttl
        self._max_entries = max_entries
        self._hits        = 0
        self._misses      = 0

    def _make_key(self, symbol: str, expiry: str) -> str:
        return f"{symbol}:{expiry}"

    def get(self, symbol: str, expiry: str) -> Optional[OptionChainResult]:
        key = self._make_key(symbol, expiry)
        with self._lock:
            entry = self._store.get(key)
            if entry is None:
                self._misses += 1
                return None
            result, expires_at = entry
            if time.monotonic() > expires_at:
                del self._store[key]
                self._misses += 1
                logger.debug("Cache expired for %s", key)
                return None
            self._hits += 1
            logger.debug("Cache hit for %s (hits=%d misses=%d)", key, self._hits, self._misses)
            return result

    def set(self, symbol: str, expiry: str, result: OptionChainResult) -> None:
        key = self._make_key(symbol, expiry)
        with self._lock:
            # Evict oldest entry if at capacity
            if len(self._store) >= self._max_entries and key not in self._store:
                oldest = min(self._store, key=lambda k: self._store[k][1])
                del self._store[oldest]
                logger.debug("Cache evicted %s (capacity reached)", oldest)
            self._store[key] = (result, time.monotonic() + self._ttl)

    def invalidate(self, symbol: str, expiry: str = "") -> int:
        """Remove all entries for symbol (or a specific expiry). Returns count removed."""
        prefix = f"{symbol}:{expiry}" if expiry else f"{symbol}:"
        with self._lock:
            keys = [k for k in self._store if k.startswith(prefix)]
            for k in keys:
                del self._store[k]
        if keys:
            logger.debug("Cache invalidated %d entries for %s", len(keys), symbol)
        return len(keys)

    def stats(self) -> dict:
        with self._lock:
            total = self._hits + self._misses
            return {
                "entries":    len(self._store),
                "hits":       self._hits,
                "misses":     self._misses,
                "hit_rate":   round(self._hits / total, 3) if total else 0.0,
                "ttl_secs":   self._ttl,
            }


# ---------------------------------------------------------------------------
# NSE HTTP session (persistent, thread-safe)
# ---------------------------------------------------------------------------

class _NSESession:
    """
    Manages a long-lived requests.Session with NSE-compatible headers,
    automatic cookie refresh, and full session rebuild on hard failures.

    Thread-safety: a single threading.Lock guards all mutable state.
    Multiple threads share the same session object, which is itself
    thread-safe for reads; lock is only held during session mutations.
    """

    def __init__(self) -> None:
        self._lock             = threading.Lock()
        self._session          = None
        self._cookie_ts:  float = 0.0
        self._session_ts: float = 0.0
        self._consecutive_errors: int = 0
        # Adaptive throttling: track consecutive captcha/empty events
        self._captcha_streak: int = 0

        self._build_session()

    # ------------------------------------------------------------------
    # Session lifecycle
    # ------------------------------------------------------------------

    def _build_session(self) -> None:
        """
        Create a new HTTP session. Uses curl_cffi with Chrome impersonation
        when available (browser-grade TLS fingerprint defeats Akamai/CF bots),
        otherwise falls back to a plain requests Session.
        """
        ua = random.choice(_USER_AGENTS)

        if _USING_CURL_CFFI:
            sess = _http_lib.Session(impersonate="chrome124")
            # curl_cffi sets TLS fingerprint automatically; just add our extra headers
            sess.headers.update({
                **_BASE_HEADERS,
                "User-Agent": ua,
                "sec-ch-ua":  _ua_to_sec_ch_ua(ua),
            })
            logger.info("NSE session built via curl_cffi/chrome124 (UA=%.60s…)", ua)
        else:
            sess = _http_lib.Session()
            sess.headers.update({
                **_BASE_HEADERS,
                "User-Agent": ua,
                "sec-ch-ua":  _ua_to_sec_ch_ua(ua),
            })
            adapter = HTTPAdapter(max_retries=Retry(total=0))
            sess.mount("https://", adapter)
            sess.mount("http://",  adapter)
            logger.info("NSE session built via requests (UA=%.60s…)", ua)

        self._session    = sess
        self._session_ts = time.monotonic()
        self._cookie_ts  = 0.0   # force cookie refresh on next use
        monitor.record_session_built()

    def _maybe_rebuild_session(self) -> None:
        """Rebuild if session has exceeded its maximum lifetime."""
        if time.monotonic() - self._session_ts > _SESSION_TTL:
            logger.info("NSE session TTL exceeded — rebuilding")
            self._build_session()

    def _warm_cookies(self) -> None:
        """
        Visit the NSE option-chain page to acquire valid session cookies
        (nsit, bm_sv, etc.).

        IMPORTANT: We skip the NSE homepage — it returns 403 from Akamai
        geo/bot filters while the option-chain page itself remains accessible.
        The OC page visit is sufficient to obtain `nsit` and Akamai cookies.
        """
        try:
            resp = self._session.get(
                _URL_OC_PAGE,
                timeout=15,
                allow_redirects=True,
                headers={
                    "Accept": (
                        "text/html,application/xhtml+xml,application/xml;"
                        "q=0.9,image/avif,image/webp,*/*;q=0.8"
                    ),
                    "Accept-Language": "en-US,en;q=0.9",
                },
            )
            cookies_obtained = list(self._session.cookies.keys())
            logger.info(
                "NSE cookie warmup → HTTP %d  cookies=%s",
                resp.status_code, cookies_obtained,
            )
            has_nsit = "nsit" in cookies_obtained
            if not has_nsit:
                logger.warning(
                    "Cookie warmup: 'nsit' not obtained (got: %s) — "
                    "API may return empty responses",
                    cookies_obtained,
                )
            # Human-like pause
            time.sleep(random.uniform(1.0, 2.0))
        except Exception as exc:
            logger.warning("NSE cookie warmup failed: %s", exc)

        self._cookie_ts = time.monotonic()

    def _ensure_cookies(self) -> None:
        """Refresh cookies if they're stale."""
        if time.monotonic() - self._cookie_ts > _COOKIE_TTL:
            logger.debug("Cookie TTL exceeded — refreshing")
            self._warm_cookies()

    # ------------------------------------------------------------------
    # HTTP GET with retry
    # ------------------------------------------------------------------

    def get(
        self,
        url:      str,
        params:   Optional[dict] = None,
        retries:  int            = 4,
        symbol:   str            = "",
    ) -> dict:
        """
        Perform a GET request with:
          - automatic cookie refresh
          - exponential back-off with full jitter on transient errors
          - session rebuild on hard blocks
          - HTML-response detection (captcha / maintenance page)
          - structured logging at each retry

        Returns parsed JSON dict on success.
        Raises NSEFetchError (or subclass) on permanent failure.
        """
        log_ctx = f"[{symbol or url}]"

        with self._lock:
            self._maybe_rebuild_session()
            self._ensure_cookies()

        last_exc: Optional[Exception] = None

        for attempt in range(1, retries + 1):
            try:
                logger.debug("%s GET %s (attempt %d/%d)", log_ctx, url, attempt, retries)
                resp = self._session.get(url, params=params, timeout=_REQUEST_TIMEOUT)

                # ── Rate limit ─────────────────────────────────────────────
                if resp.status_code in _RATE_LIMIT_CODES:
                    wait = self._backoff(attempt, base=10.0)
                    logger.warning(
                        "%s HTTP %d (rate-limited) — backing off %.1fs",
                        log_ctx, resp.status_code, wait,
                    )
                    time.sleep(wait)
                    last_exc = NSERateLimitError(f"HTTP {resp.status_code}")
                    continue

                # ── Hard block ─────────────────────────────────────────────
                if resp.status_code in _BLOCK_CODES:
                    logger.error("%s HTTP 403 — rebuilding session", log_ctx)
                    with self._lock:
                        self._build_session()
                        self._warm_cookies()
                    last_exc = NSEBlockedError("HTTP 403")
                    time.sleep(self._backoff(attempt, base=5.0))
                    continue

                # ── 401 — stale cookies ────────────────────────────────────
                if resp.status_code == 401:
                    logger.warning(
                        "%s HTTP 401 (stale cookies) — refreshing (attempt %d)",
                        log_ctx, attempt,
                    )
                    with self._lock:
                        self._warm_cookies()
                    last_exc = NSEFetchError("HTTP 401")
                    time.sleep(self._backoff(attempt, base=2.0))
                    continue

                # ── Other HTTP errors ──────────────────────────────────────
                if not resp.ok:
                    logger.error(
                        "%s Unexpected HTTP %d", log_ctx, resp.status_code
                    )
                    resp.raise_for_status()

                # ── Deep response diagnostics (logged before any validation) ─
                ct          = resp.headers.get("Content-Type", "")
                body_snippet = resp.text[:500].replace("\n", " ")
                resp_type   = _detect_response_type(resp.text, ct)
                logger.debug(
                    "%s HTTP %d  Content-Type=%r  resp_type=%s  body_snippet=%r",
                    log_ctx, resp.status_code, ct, resp_type, body_snippet,
                )

                # ── Captcha / HTML → rebuild session immediately ──────────
                if resp_type in ("captcha", "blocked", "html"):
                    exc_cls = NSECaptchaError if resp_type == "captcha" else NSEDataError
                    logger.error(
                        "%s NSE returned %s page (attempt %d/%d) — rebuilding session. "
                        "Snippet: %s",
                        log_ctx, resp_type, attempt, retries, body_snippet[:200],
                    )
                    with self._lock:
                        self._build_session()
                        self._warm_cookies()
                    last_exc = exc_cls(f"NSE returned {resp_type} page for {symbol}")
                    time.sleep(self._backoff(attempt, base=5.0))
                    continue

                if resp_type == "empty":
                    logger.error("%s Empty response body (attempt %d/%d)", log_ctx, attempt, retries)
                    last_exc = NSEDataError(f"Empty response body for {symbol}")
                    time.sleep(self._backoff(attempt, base=2.0))
                    continue

                # ── Validate raw response (content-type) ─────────────────
                raw_vr = validate_raw_response(resp.text, ct, symbol=symbol)
                if not raw_vr.is_valid:
                    logger.error(
                        "%s Raw response validation failed — %s",
                        log_ctx,
                        "; ".join(e.message for e in raw_vr.errors),
                    )
                    with self._lock:
                        self._build_session()
                        self._warm_cookies()
                    last_exc = NSEDataError(
                        "Raw response invalid: "
                        + "; ".join(e.message for e in raw_vr.errors)
                    )
                    time.sleep(self._backoff(attempt, base=5.0))
                    continue

                # ── Parse JSON ────────────────────────────────────────────
                try:
                    data = resp.json()
                except ValueError as exc:
                    logger.error("%s JSON decode failed: %s  snippet=%r", log_ctx, exc, body_snippet[:200])
                    last_exc = NSEDataError(f"JSON decode: {exc}")
                    time.sleep(self._backoff(attempt, base=2.0))
                    continue

                # ── Detect market-closed empty response {} ────────────────
                if isinstance(data, dict) and len(data) == 0:
                    self._captcha_streak += 1
                    logger.warning(
                        "%s NSE returned empty JSON {} (market likely closed or "
                        "bot-throttled; streak=%d attempt %d/%d)",
                        log_ctx, self._captcha_streak, attempt, retries,
                    )
                    # Raise immediately — retrying won't help if market is closed
                    raise NSEMarketClosedError(
                        f"NSE returned empty response for {symbol} — "
                        "market may be closed or session is throttled"
                    )

                self._captcha_streak = 0  # reset on good response

                # ── Log parsed JSON shape for diagnostics ─────────────────
                logger.info(
                    "%s Parsed JSON top-level keys=%s",
                    log_ctx, list(data.keys()) if isinstance(data, dict) else type(data).__name__,
                )

                # Success
                self._consecutive_errors = 0
                return data

            except (NSEMarketClosedError, NSECaptchaError, NSEBlockedError):
                # Don't retry these — propagate immediately
                raise

            except Exception as exc:
                # Catch-all for both requests and curl_cffi transport errors
                exc_str = str(exc)
                if "timeout" in exc_str.lower() or "timed out" in exc_str.lower():
                    logger.warning(
                        "%s Request timed out (attempt %d/%d)",
                        log_ctx, attempt, retries,
                    )
                elif "connection" in exc_str.lower():
                    logger.warning(
                        "%s Connection error (attempt %d/%d): %s",
                        log_ctx, attempt, retries, exc,
                    )
                else:
                    logger.error("%s Unexpected request error: %s", log_ctx, exc)
                last_exc = exc

            if attempt < retries:
                wait = self._backoff(attempt)
                logger.info("%s Retrying in %.1fs…", log_ctx, wait)
                monitor.record_retry(symbol)
                time.sleep(wait)

        self._consecutive_errors += 1
        raise NSEFetchError(
            f"NSE API failed for {symbol or url} after {retries} attempts. "
            f"Last error: {last_exc}"
        ) from last_exc

    def force_cookie_refresh(self) -> None:
        """Public helper so callers can trigger a cookie refresh between retries."""
        with self._lock:
            self._warm_cookies()

    @staticmethod
    def _backoff(attempt: int, base: float = 1.5, cap: float = 30.0) -> float:
        """Full-jitter exponential back-off: uniform(0, min(cap, base * 2^attempt))."""
        ceiling = min(cap, base * (2 ** (attempt - 1)))
        return random.uniform(0.5, ceiling)


# ---------------------------------------------------------------------------
# Response-type detection & payload normalisation
# ---------------------------------------------------------------------------

# Markers that indicate NSE returned HTML instead of JSON
_CAPTCHA_MARKERS   = ("captcha", "verify you are human", "i am not a robot")
_HTML_MARKERS      = ("<!doctype html", "<html", "<body")
_BLOCKED_MARKERS   = ("access denied", "403 forbidden", "cloudflare")

def _detect_response_type(body: str, content_type: str) -> str:
    """
    Inspect a raw HTTP response body and classify it before JSON parsing.

    Returns one of:
        "json"      — looks like valid JSON (starts with '{' or '[')
        "captcha"   — NSE bot-check / captcha page
        "html"      — HTML page (not captcha-specific)
        "blocked"   — hard block / CF page
        "empty"     — empty or whitespace-only body
        "unknown"   — none of the above heuristics matched
    """
    stripped = (body or "").strip()
    if not stripped:
        return "empty"

    lower = stripped[:2048].lower()

    # Check captcha first (subset of HTML)
    for m in _CAPTCHA_MARKERS:
        if m in lower:
            return "captcha"
    for m in _BLOCKED_MARKERS:
        if m in lower:
            return "blocked"
    for m in _HTML_MARKERS:
        if lower.startswith(m) or m in lower[:512]:
            return "html"

    ct = content_type.lower()
    if stripped[0] in ("{", "[") or "application/json" in ct:
        return "json"

    return "unknown"


def _extract_nse_payload(raw_json: dict, symbol: str = "") -> dict:
    """
    Normalise any known NSE option-chain JSON shape into a single canonical dict:

        {
            "data":            list[dict],   # strike rows
            "underlyingValue": float,        # spot price (0.0 if fully absent)
            "expiryDates":     list[str],    # sorted nearest-first
        }

    Supported input shapes:
        1. Standard:        records.data + records.underlyingValue + records.expiryDates
        2. Filtered-only:   filtered.data  (no records envelope)
        3. Top-level data:  root.data list
        4. Partial records: records.data present but sub-keys partially absent

    underlyingValue is derived from CE/PE LTP midpoints of ATM row when absent.
    expiryDates     is derived from unique expiryDate values in the rows when absent.

    Raises:
        NSEMalformedPayloadError if no usable data rows can be found anywhere.
    """
    records  = raw_json.get("records")  if isinstance(raw_json.get("records"),  dict) else {}
    filtered = raw_json.get("filtered") if isinstance(raw_json.get("filtered"), dict) else {}

    # ── Locate data rows (priority: records > filtered > root) ───────────
    data_rows: list = (
        records.get("data")
        or filtered.get("data")
        or (raw_json.get("data") if isinstance(raw_json.get("data"), list) else None)
        or []
    )
    if not data_rows:
        top_keys = list(raw_json.keys())
        raise NSEMalformedPayloadError(
            f"No usable option-chain data rows found for {symbol}. "
            f"Top-level keys present: {top_keys}",
            response_type="no_data_rows",
        )

    # ── Locate underlyingValue ────────────────────────────────────────────
    spot: float = (
        _safe_float(records.get("underlyingValue"))
        or _safe_float(filtered.get("underlyingValue"))
        or _safe_float(raw_json.get("underlyingValue"))
    )
    if spot <= 0:
        # Derive from the average of CE.lastPrice and PE.lastPrice for the
        # row whose strike is closest to the median strike value.
        strikes_with_both = [
            r for r in data_rows
            if r.get("CE") and r.get("PE")
            and (_safe_float(r["CE"].get("lastPrice")) + _safe_float(r["PE"].get("lastPrice"))) > 0
        ]
        if strikes_with_both:
            # pick middle row
            mid = strikes_with_both[len(strikes_with_both) // 2]
            ce_ltp = _safe_float(mid["CE"].get("lastPrice"))
            pe_ltp = _safe_float(mid["PE"].get("lastPrice"))
            strike = _safe_float(mid.get("strikePrice"))
            # spot ≈ strike ± (pe_ltp - ce_ltp)  (put-call parity approximation)
            spot = strike + (pe_ltp - ce_ltp)
            logger.warning(
                "[%s] underlyingValue absent — derived spot=%.2f from strike=%.2f "
                "CE.ltp=%.2f PE.ltp=%.2f",
                symbol, spot, strike, ce_ltp, pe_ltp,
            )

    # ── Locate expiryDates ────────────────────────────────────────────────
    expiry_dates: list[str] = (
        records.get("expiryDates")
        or filtered.get("expiryDates")
        or raw_json.get("expiryDates")
        or []
    )
    if not expiry_dates:
        # Derive from unique expiryDate values in the data rows
        seen_expiries: list[str] = []
        seen_set: set[str] = set()
        for row in data_rows:
            exp = row.get("expiryDate", "")
            if exp and exp not in seen_set:
                seen_set.add(exp)
                seen_expiries.append(exp)
        expiry_dates = seen_expiries
        if expiry_dates:
            logger.warning(
                "[%s] expiryDates absent — derived %d unique expiries from row data: %s",
                symbol, len(expiry_dates), expiry_dates[:5],
            )

    return {
        "data":            data_rows,
        "underlyingValue": spot,
        "expiryDates":     expiry_dates,
    }


# ---------------------------------------------------------------------------
# Debug dump helper
# ---------------------------------------------------------------------------

import os as _os

def _write_debug_dump(symbol: str, raw: object, reason: str) -> str:
    """
    Write a debug dump of the raw NSE response to disk.

    Dump file location: <project_root>/debug/nse_fail_<timestamp>_<symbol>.txt
    Returns the path written (or empty string if write failed).
    """
    import json as _json
    try:
        dump_dir = _os.path.join(
            _os.path.dirname(_os.path.dirname(_os.path.dirname(__file__))), "debug"
        )
        _os.makedirs(dump_dir, exist_ok=True)
        ts    = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        fname = f"nse_fail_{ts}_{symbol.upper()}.txt"
        path  = _os.path.join(dump_dir, fname)
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(f"# NSE debug dump — symbol={symbol}  reason={reason}\n")
            fh.write(f"# generated_at={datetime.now(timezone.utc).isoformat()}\n\n")
            if isinstance(raw, str):
                fh.write(raw)
            else:
                try:
                    fh.write(_json.dumps(raw, indent=2, ensure_ascii=False))
                except Exception:
                    fh.write(repr(raw))
        logger.info("[%s] NSE debug dump written → %s", symbol, path)
        return path
    except Exception as exc:
        logger.warning("[%s] Could not write NSE debug dump: %s", symbol, exc)
        return ""


# ---------------------------------------------------------------------------
# Parser
# ---------------------------------------------------------------------------

def _safe_int(v, default: int = 0) -> int:
    try:
        return int(v) if v is not None and v != "-" else default
    except (TypeError, ValueError):
        return default


def _safe_float(v, default: float = 0.0) -> float:
    try:
        return float(v) if v is not None and v != "-" else default
    except (TypeError, ValueError):
        return default


def _parse_leg(raw: dict) -> OptionLeg:
    """Parse one side (CE or PE) of a strike from the NSE API entry."""
    return OptionLeg(
        oi         = _safe_int(raw.get("openInterest")),
        oi_change  = _safe_int(raw.get("changeinOpenInterest")),
        volume     = _safe_int(raw.get("totalTradedVolume")),
        iv         = _safe_float(raw.get("impliedVolatility")),
        ltp        = _safe_float(raw.get("lastPrice")),
        bid        = _safe_float(raw.get("bidprice")),
        ask        = _safe_float(raw.get("askPrice")),
        delta      = _safe_float(raw.get("delta")),
        theta      = _safe_float(raw.get("theta")),
        vega       = _safe_float(raw.get("vega")),
    )


def _parse_raw_chain(raw: dict, symbol: str, target_expiry: Optional[str]) -> OptionChainResult:
    """
    Convert the raw NSE API JSON into a typed OptionChainResult.

    Accepts all four NSE payload shapes via _extract_nse_payload():
      1. Standard:        records.data + records.underlyingValue + records.expiryDates
      2. Filtered-only:   filtered.data
      3. Top-level data:  root.data list
      4. Partial records: records.data with derivable underlyingValue / expiryDates

    Raises NSEMalformedPayloadError (subclass of NSEDataError) if no rows can
    be extracted; raises NSEDataError for other unrecoverable parse issues.
    """
    # ── Normalise payload across all known shapes ─────────────────────────
    # _extract_nse_payload raises NSEMalformedPayloadError if truly unusable
    payload = _extract_nse_payload(raw, symbol)

    # ── Spot price ────────────────────────────────────────────────────────
    spot = _safe_float(payload["underlyingValue"])
    if spot <= 0:
        logger.warning("[%s] Spot price is zero or undeducible — data may be stale", symbol)

    # ── Expiries ──────────────────────────────────────────────────────────
    all_expiries: list[str] = payload["expiryDates"]
    if not all_expiries:
        raise NSEDataError(
            f"No expiry dates found (or derivable) in NSE response for {symbol}"
        )

    expiry = (
        target_expiry
        if target_expiry and target_expiry in all_expiries
        else all_expiries[0]
    )

    # ── Strike data ───────────────────────────────────────────────────────
    raw_data: list[dict] = payload["data"]
    # raw_data is guaranteed non-empty by _extract_nse_payload

    # Filter to chosen expiry only
    rows = [e for e in raw_data if e.get("expiryDate") == expiry]
    if not rows:
        logger.warning(
            "[%s] No strike rows for expiry %r — falling back to first available",
            symbol, expiry,
        )
        rows = [e for e in raw_data if e.get("expiryDate") == all_expiries[0]]
        expiry = all_expiries[0]

    # ── Build StrikeRow list ──────────────────────────────────────────────
    strike_rows: list[StrikeRow] = []
    for entry in rows:
        s = _safe_float(entry.get("strikePrice"))
        if s <= 0:
            continue
        ce_raw = entry.get("CE") or {}
        pe_raw = entry.get("PE") or {}
        strike_rows.append(StrikeRow(
            strike = s,
            ce     = _parse_leg(ce_raw),
            pe     = _parse_leg(pe_raw),
        ))

    strike_rows.sort(key=lambda r: r.strike)

    if not strike_rows:
        raise NSEDataError(f"Zero valid strike rows parsed for {symbol} expiry {expiry}")

    # ── Aggregates ────────────────────────────────────────────────────────
    total_ce_oi  = sum(r.ce.oi     for r in strike_rows)
    total_pe_oi  = sum(r.pe.oi     for r in strike_rows)
    total_ce_vol = sum(r.ce.volume for r in strike_rows)
    total_pe_vol = sum(r.pe.volume for r in strike_rows)
    pcr          = round(total_pe_oi / total_ce_oi, 4) if total_ce_oi else 0.0

    # ── ATM ───────────────────────────────────────────────────────────────
    atm_row   = min(strike_rows, key=lambda r: abs(r.strike - spot))
    atm_strike = atm_row.strike
    atm_ce_iv  = atm_row.ce.iv
    atm_pe_iv  = atm_row.pe.iv

    return OptionChainResult(
        symbol           = symbol,
        expiry           = expiry,
        all_expiries     = all_expiries,
        spot_price       = spot,
        timestamp        = datetime.now(timezone.utc).isoformat(),
        strikes          = strike_rows,
        total_ce_oi      = total_ce_oi,
        total_pe_oi      = total_pe_oi,
        total_ce_volume  = total_ce_vol,
        total_pe_volume  = total_pe_vol,
        pcr              = pcr,
        atm_strike       = atm_strike,
        atm_ce_iv        = atm_ce_iv,
        atm_pe_iv        = atm_pe_iv,
        fetched_from_cache = False,
    )


# ---------------------------------------------------------------------------
# Service (singleton)
# ---------------------------------------------------------------------------

class NSEOptionChainService:
    """
    Thread-safe singleton that combines:
      - _NSESession  (HTTP + cookie management)
      - _TTLCache    (in-memory response cache)
      - Data parsing (typed OptionChainResult)
    """

    def __init__(
        self,
        cache_ttl: float = _CACHE_TTL_SECS,
    ) -> None:
        self._http  = _NSESession()
        self._cache = _TTLCache(ttl=cache_ttl)

    # ------------------------------------------------------------------
    # Core fetch
    # ------------------------------------------------------------------

    def get_option_chain(
        self,
        symbol: str,
        expiry: Optional[str] = None,
        force_refresh: bool   = False,
    ) -> OptionChainResult:
        """
        Fetch (or return cached) full option chain for symbol.

        Args:
            symbol:        NSE symbol, e.g. "NIFTY", "RELIANCE".
            expiry:        Expiry date string as returned by NSE
                           (e.g. "25-Jul-2024"). None = nearest expiry.
            force_refresh: Bypass cache and always hit NSE.

        Returns:
            OptionChainResult with fetched_from_cache flag set accordingly.

        Raises:
            NSEFetchError  if the API is unreachable after all retries.
            NSEDataError   if the response is malformed.
        """
        symbol = symbol.upper().strip()
        cache_expiry = expiry or "__nearest__"

        if not force_refresh:
            cached = self._cache.get(symbol, cache_expiry)
            if cached is not None:
                cached.fetched_from_cache = True
                monitor.record_cache_hit(symbol)
                return cached

        monitor.record_cache_miss(symbol)

        url = (
            _URL_INDEX_CHAIN if symbol in INDEX_SYMBOLS else _URL_EQUITY_CHAIN
        )

        logger.info("[%s] Fetching option chain (expiry=%s)", symbol, expiry or "nearest")

        monitor.record_fetch_start(symbol)
        t0 = time.monotonic()

        # ── Escalating retry loop for malformed payloads ──────────────────
        # NSESession.get() handles network-level retries internally.
        # Here we add a second retry layer specifically for malformed/alternate
        # JSON payloads — each attempt escalates the recovery strategy.
        _MAX_PARSE_RETRIES = 3
        last_parse_exc: Optional[Exception] = None
        raw: Optional[dict] = None

        for parse_attempt in range(1, _MAX_PARSE_RETRIES + 1):
            try:
                raw = self._http.get(url, params={"symbol": symbol}, symbol=symbol)
            except NSEMarketClosedError as exc:
                # Don't retry — market is closed, no point
                monitor.record_fetch_failure(symbol)
                logger.warning(
                    "[%s] Market closed / empty response — skipping retries. (%s)",
                    symbol, exc,
                )
                raise
            except NSEFetchError as exc:
                monitor.record_fetch_failure(symbol)
                raise
            except Exception as exc:
                monitor.record_fetch_failure(symbol)
                raise NSEFetchError(f"Unexpected error fetching {symbol}: {exc}") from exc

            # ── Structural validation (relaxed) ────────────────────────────
            struct_vr = validate_nse_json_structure(raw, symbol)
            if struct_vr.warnings:
                logger.info(
                    "[%s] Structural warnings (attempt %d/%d): %s",
                    symbol, parse_attempt, _MAX_PARSE_RETRIES,
                    "; ".join(w.message for w in struct_vr.warnings),
                )
            if not struct_vr.is_valid:
                # Hard structural failure — escalate
                err_msg = "; ".join(e.message for e in struct_vr.errors)
                logger.error(
                    "[%s] Structural validation failed (attempt %d/%d): %s  "
                    "top-level keys=%s",
                    symbol, parse_attempt, _MAX_PARSE_RETRIES, err_msg,
                    list(raw.keys()) if isinstance(raw, dict) else type(raw).__name__,
                )
                last_parse_exc = NSEMalformedPayloadError(
                    f"NSE structural validation failed for {symbol}: {err_msg}",
                    response_type="struct_invalid",
                )
                if parse_attempt == 1:
                    logger.info("[%s] Attempt 1 failed — refreshing cookies and retrying", symbol)
                    self._http.force_cookie_refresh()
                elif parse_attempt == 2:
                    wait = random.uniform(3.0, 8.0)
                    logger.info("[%s] Attempt 2 failed — backing off %.1fs then retrying", symbol, wait)
                    time.sleep(wait)
                else:
                    _write_debug_dump(symbol, raw, reason="struct_validation_failed")
                    monitor.record_fetch_failure(symbol)
                    raise NSERetryExhaustedError(
                        f"NSE payload for {symbol} failed structural validation after "
                        f"{_MAX_PARSE_RETRIES} attempts. Last error: {err_msg}"
                    ) from last_parse_exc
                continue

            # ── Try to parse ───────────────────────────────────────────────
            try:
                result = _parse_raw_chain(raw, symbol, expiry)
            except NSEMalformedPayloadError as exc:
                logger.error(
                    "[%s] Payload extraction failed (attempt %d/%d): %s  "
                    "top-level keys=%s",
                    symbol, parse_attempt, _MAX_PARSE_RETRIES, exc,
                    list(raw.keys()) if isinstance(raw, dict) else "?",
                )
                last_parse_exc = exc
                if parse_attempt == 1:
                    self._http.force_cookie_refresh()
                elif parse_attempt == 2:
                    wait = random.uniform(3.0, 8.0)
                    time.sleep(wait)
                else:
                    _write_debug_dump(symbol, raw, reason=f"malformed_{exc.response_type}")
                    monitor.record_fetch_failure(symbol)
                    raise NSERetryExhaustedError(
                        f"NSE payload for {symbol} could not be parsed after "
                        f"{_MAX_PARSE_RETRIES} attempts. Last: {exc}"
                    ) from exc
                continue
            except NSEDataError:
                # Other data errors (e.g. zero valid strikes) — no retry benefit
                monitor.record_fetch_failure(symbol)
                raise

            # ── Parse succeeded — break retry loop ─────────────────────────
            break
        else:
            # All parse attempts exhausted (shouldn't normally reach here)
            monitor.record_fetch_failure(symbol)
            raise NSERetryExhaustedError(
                f"NSE payload for {symbol} could not be parsed after {_MAX_PARSE_RETRIES} attempts."
            ) from last_parse_exc

        latency_ms = (time.monotonic() - t0) * 1000

        # ── Validate parsed chain ─────────────────────────────────────────
        chain_vr = validate_parsed_chain(result, symbol)
        monitor.record_validation_result(
            symbol,
            is_valid=chain_vr.is_valid,
            warning_count=len(chain_vr.warnings),
        )
        if not chain_vr.is_valid:
            err_msg = "; ".join(e.message for e in chain_vr.errors)
            logger.error(
                "[%s] Parsed chain failed validation (corruption_score=%.2f): %s",
                symbol, chain_vr.corruption_score, err_msg,
            )
            monitor.record_fetch_failure(symbol)
            raise NSEDataError(
                f"Parsed option chain validation failed for {symbol}: {err_msg}"
            )

        self._cache.set(symbol, cache_expiry, result)
        monitor.record_fetch_success(symbol, latency_ms=latency_ms)

        logger.info(
            "[%s] Fetched %d strikes for expiry %s (spot=%.2f pcr=%.3f latency=%.0fms "
            "warnings=%d struct_warnings=%d)",
            symbol, len(result.strikes), result.expiry, result.spot_price, result.pcr,
            latency_ms, len(chain_vr.warnings), len(struct_vr.warnings),
        )
        return result

    # ------------------------------------------------------------------
    # Helper methods
    # ------------------------------------------------------------------

    def get_expiries(self, symbol: str) -> list[str]:
        """
        Return all available expiry dates for symbol, ordered nearest first.

        Fetches the chain (cache-friendly — reuses cached data if fresh).
        """
        result = self.get_option_chain(symbol)
        return result.all_expiries

    def get_nearest_expiry(self, symbol: str) -> str:
        """Return the nearest expiry date string for symbol."""
        expiries = self.get_expiries(symbol)
        if not expiries:
            raise NSEDataError(f"No expiries found for {symbol}")
        return expiries[0]

    def get_atm_strike(
        self,
        symbol: str,
        expiry: Optional[str] = None,
    ) -> float:
        """
        Return the at-the-money strike (closest to current spot price).

        Uses cached chain when available.
        """
        result = self.get_option_chain(symbol, expiry=expiry)
        return result.atm_strike

    def get_spot_price(self, symbol: str) -> float:
        """Return the current spot price for symbol from option chain data."""
        return self.get_option_chain(symbol).spot_price

    def invalidate_cache(self, symbol: str, expiry: str = "") -> int:
        """Remove cached entries for symbol (or a specific expiry). Returns count."""
        return self._cache.invalidate(symbol.upper(), expiry)

    def cache_stats(self) -> dict:
        """Return cache hit/miss statistics."""
        return self._cache.stats()

    def is_market_open(self) -> bool:
        """
        Return True if NSE is currently in trading hours (Mon–Fri 09:15–15:30 IST).
        Used by callers to decide whether to fetch live vs skip.
        """
        now_utc  = datetime.now(timezone.utc)
        if now_utc.weekday() >= 5:
            return False
        now_ist  = now_utc.timestamp() + _IST_OFFSET_SECS
        ist_dt   = datetime.utcfromtimestamp(now_ist)
        open_m   = _MARKET_OPEN_IST[0]  * 60 + _MARKET_OPEN_IST[1]
        close_m  = _MARKET_CLOSE_IST[0] * 60 + _MARKET_CLOSE_IST[1]
        current  = ist_dt.hour * 60 + ist_dt.minute
        return open_m <= current < close_m


# ---------------------------------------------------------------------------
# Module-level singleton + convenience functions
# ---------------------------------------------------------------------------

_service: Optional[NSEOptionChainService] = None
_service_lock = threading.Lock()


def _get_service() -> NSEOptionChainService:
    """Lazy-initialise the singleton (avoids NSE HTTP calls at import time)."""
    global _service
    if _service is None:
        with _service_lock:
            if _service is None:
                _service = NSEOptionChainService()
    return _service


def get_option_chain(symbol: str, expiry: Optional[str] = None) -> OptionChainResult:
    """Fetch (or return cached) option chain for symbol."""
    return _get_service().get_option_chain(symbol, expiry=expiry)


def get_expiries(symbol: str) -> list[str]:
    """Return all available expiry date strings for symbol."""
    return _get_service().get_expiries(symbol)


def get_nearest_expiry(symbol: str) -> str:
    """Return the nearest expiry date string for symbol."""
    return _get_service().get_nearest_expiry(symbol)


def get_atm_strike(symbol: str, expiry: Optional[str] = None) -> float:
    """Return the ATM strike for symbol (closest to spot)."""
    return _get_service().get_atm_strike(symbol, expiry=expiry)
