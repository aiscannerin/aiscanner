"""
Dhan Option Chain Service
=========================
Fetches option-chain data from the Dhan HQ v2 API using a *user's* own
credentials (client_id + access_token) and returns the SAME typed
OptionChainResult used by the rest of the app — a drop-in replacement for the
(Akamai-blocked) NSE fetcher.

Dhan API:
  POST https://api.dhan.co/v2/optionchain
       headers: access-token, client-id, Content-Type: application/json
       body:    {"UnderlyingScrip": <int>, "UnderlyingSeg": "IDX_I"|"NSE_EQ",
                 "Expiry": "YYYY-MM-DD"}
  POST https://api.dhan.co/v2/optionchain/expirylist
       body:    {"UnderlyingScrip": <int>, "UnderlyingSeg": ...}

Rate limit: 1 request per 3 seconds *per access token*. We enforce that
spacing per client_id inside this module so callers don't have to.
"""

from __future__ import annotations

import logging
import threading
import time
from datetime import datetime, timezone
from typing import Optional

from curl_cffi import requests as _http

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
from app.services import dhan_scrip_master_service as scrip

logger = logging.getLogger(__name__)

_URL_CHAIN   = "https://api.dhan.co/v2/optionchain"
_URL_EXPIRY  = "https://api.dhan.co/v2/optionchain/expirylist"

_REQUEST_TIMEOUT = 20
_RATE_GAP_SECS   = 3.1          # Dhan: 1 request / 3s per token (small buffer)

# Per-token rate-limit state: client_id -> last_call_monotonic
_rate_lock = threading.Lock()
_last_call: dict[str, float] = {}

# Expiry-list cache (expiries don't change intraday): key=(client_id,symbol)
_expiry_cache: dict[tuple[str, str], tuple[list[str], float]] = {}
_EXPIRY_TTL = 6 * 3600


class DhanCredentialError(NSEFetchError):
    """Raised when Dhan rejects the credentials (bad/expired token)."""


def _throttle(client_id: str) -> None:
    """Block until at least _RATE_GAP_SECS has elapsed since this token's last call."""
    with _rate_lock:
        last = _last_call.get(client_id, 0.0)
        wait = _RATE_GAP_SECS - (time.monotonic() - last)
        if wait > 0:
            time.sleep(wait)
        _last_call[client_id] = time.monotonic()


def _headers(client_id: str, access_token: str) -> dict:
    return {
        "access-token": access_token,
        "client-id":    client_id,
        "Content-Type": "application/json",
        "Accept":       "application/json",
    }


def _post(url: str, body: dict, client_id: str, access_token: str) -> dict:
    _throttle(client_id)
    try:
        resp = _http.post(
            url, json=body, headers=_headers(client_id, access_token),
            timeout=_REQUEST_TIMEOUT,
        )
    except Exception as exc:
        raise NSEFetchError(f"Dhan request failed: {exc}") from exc

    if resp.status_code in (401, 403):
        raise DhanCredentialError(
            f"Dhan rejected credentials (HTTP {resp.status_code}). "
            "Access token may be invalid or expired — reconnect your Dhan account."
        )
    if resp.status_code == 429:
        raise NSEFetchError("Dhan rate limit hit (HTTP 429) — slow down.")
    if not resp.ok:
        raise NSEFetchError(f"Dhan HTTP {resp.status_code}: {resp.text[:200]}")

    try:
        data = resp.json()
    except ValueError as exc:
        raise NSEDataError(f"Dhan returned non-JSON: {resp.text[:200]}") from exc

    # Dhan envelope: {"status": "success"|"failure", "data": {...}, "remarks": ...}
    status = str(data.get("status", "")).lower()
    if status and status not in ("success", "ok"):
        remarks = data.get("remarks") or data.get("message") or data
        msg = str(remarks)
        if any(k in msg.lower() for k in ("token", "auth", "client", "invalid")):
            raise DhanCredentialError(f"Dhan auth error: {msg[:200]}")
        raise NSEDataError(f"Dhan error: {msg[:200]}")

    return data


def get_expiries(symbol: str, client_id: str, access_token: str) -> list[str]:
    """Return all expiry dates (YYYY-MM-DD) for symbol, nearest first."""
    symbol = symbol.upper().strip()
    key = (client_id, symbol)
    cached = _expiry_cache.get(key)
    if cached and (time.monotonic() - cached[1]) < _EXPIRY_TTL:
        return cached[0]

    info = scrip.lookup(symbol)
    if info is None:
        raise NSEDataError(f"Symbol {symbol} not found in Dhan scrip master")

    data = _post(
        _URL_EXPIRY,
        {"UnderlyingScrip": info["security_id"], "UnderlyingSeg": info["segment"]},
        client_id, access_token,
    )
    expiries = data.get("data") or []
    if not isinstance(expiries, list) or not expiries:
        raise NSEDataError(f"No expiries returned by Dhan for {symbol}")

    expiries = sorted(str(e) for e in expiries)   # YYYY-MM-DD sorts chronologically
    _expiry_cache[key] = (expiries, time.monotonic())
    return expiries


def _parse_oc(oc: dict, spot: float, symbol: str, expiry: str,
              all_expiries: list[str]) -> OptionChainResult:
    """Convert Dhan's strike-keyed `oc` object into an OptionChainResult."""
    strike_rows: list[StrikeRow] = []

    for strike_str, sides in oc.items():
        strike = _safe_float(strike_str)
        if strike <= 0:
            continue
        ce_raw = (sides or {}).get("ce") or {}
        pe_raw = (sides or {}).get("pe") or {}

        # Skip rows with no data on either side
        if not ce_raw and not pe_raw:
            continue

        def leg(raw: dict) -> OptionLeg:
            greeks = raw.get("greeks") or {}
            oi   = _safe_int(raw.get("oi"))
            prev = _safe_int(raw.get("previous_oi"))
            return OptionLeg(
                oi        = oi,
                oi_change = oi - prev,
                volume    = _safe_int(raw.get("volume")),
                iv        = _safe_float(raw.get("implied_volatility")),
                ltp       = _safe_float(raw.get("last_price")),
                bid       = _safe_float(raw.get("top_bid_price")),
                ask       = _safe_float(raw.get("top_ask_price")),
                delta     = _safe_float(greeks.get("delta")),
                theta     = _safe_float(greeks.get("theta")),
                vega      = _safe_float(greeks.get("vega")),
            )

        strike_rows.append(StrikeRow(strike=strike, ce=leg(ce_raw), pe=leg(pe_raw)))

    strike_rows.sort(key=lambda r: r.strike)
    if not strike_rows:
        raise NSEMarketClosedError(
            f"Dhan returned no option-chain rows for {symbol} — "
            "market may be closed or no data yet"
        )

    total_ce_oi  = sum(r.ce.oi for r in strike_rows)
    total_pe_oi  = sum(r.pe.oi for r in strike_rows)
    total_ce_vol = sum(r.ce.volume for r in strike_rows)
    total_pe_vol = sum(r.pe.volume for r in strike_rows)
    pcr          = round(total_pe_oi / total_ce_oi, 4) if total_ce_oi else 0.0

    atm_row    = min(strike_rows, key=lambda r: abs(r.strike - spot)) if spot > 0 else strike_rows[len(strike_rows) // 2]
    atm_strike = atm_row.strike

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
        atm_ce_iv        = atm_row.ce.iv,
        atm_pe_iv        = atm_row.pe.iv,
        fetched_from_cache = False,
    )


def get_option_chain(
    symbol: str,
    client_id: str,
    access_token: str,
    expiry: Optional[str] = None,
) -> OptionChainResult:
    """
    Fetch the full option chain for symbol from Dhan and return an
    OptionChainResult. If expiry is None, the nearest expiry is used.
    """
    symbol = symbol.upper().strip()
    info = scrip.lookup(symbol)
    if info is None:
        raise NSEDataError(f"Symbol {symbol} not found in Dhan scrip master")

    all_expiries = get_expiries(symbol, client_id, access_token)
    chosen = expiry if (expiry and expiry in all_expiries) else all_expiries[0]

    data = _post(
        _URL_CHAIN,
        {
            "UnderlyingScrip": info["security_id"],
            "UnderlyingSeg":   info["segment"],
            "Expiry":          chosen,
        },
        client_id, access_token,
    )

    inner = data.get("data") or {}
    spot  = _safe_float(inner.get("last_price"))
    oc    = inner.get("oc") or {}
    if not oc:
        raise NSEMarketClosedError(
            f"Dhan returned empty option chain for {symbol} (expiry {chosen})"
        )

    return _parse_oc(oc, spot, symbol, chosen, all_expiries)


def validate_credentials(client_id: str, access_token: str) -> tuple[bool, str | None]:
    """
    Cheap credential check — fetch the NIFTY expiry list. Returns (ok, error).
    """
    try:
        get_expiries("NIFTY", client_id, access_token)
        return True, None
    except DhanCredentialError as exc:
        return False, str(exc)
    except Exception as exc:
        # Reached Dhan but some other issue — credentials themselves may be fine
        return False, f"Could not verify: {exc}"
