"""
Dhan Scrip Master Service
=========================
Downloads Dhan's instrument list (scrip master CSV) and builds a lookup of
trading symbol -> (security_id, underlying_segment) for use as the
UnderlyingScrip / UnderlyingSeg parameters of the Dhan Option Chain API.

We only need the *underlying* security IDs:
  - Indices  (NIFTY, BANKNIFTY, FINNIFTY ...): SEM_SEGMENT == 'I'  -> seg 'IDX_I'
  - Equities (RELIANCE, TCS ...):              SEM_SEGMENT == 'E'  -> seg 'NSE_EQ'

The CSV is ~5MB; we cache the parsed map to disk (JSON) and refresh once a day.

CSV columns (compact master):
  SEM_EXM_EXCH_ID, SEM_SEGMENT, SEM_SMST_SECURITY_ID, SEM_INSTRUMENT_NAME,
  SEM_EXPIRY_CODE, SEM_TRADING_SYMBOL, SEM_LOT_UNITS, SEM_CUSTOM_SYMBOL,
  SEM_EXPIRY_DATE, SEM_STRIKE_PRICE, SEM_OPTION_TYPE, SEM_TICK_SIZE,
  SEM_EXPIRY_FLAG, SEM_EXCH_INSTRUMENT_TYPE, SEM_SERIES, SM_SYMBOL_NAME
"""

from __future__ import annotations

import csv
import io
import json
import logging
import os
import threading
import time

from curl_cffi import requests as _http  # already a project dependency

logger = logging.getLogger(__name__)

_CSV_URL = "https://images.dhan.co/api-data/api-scrip-master.csv"

# Cache file lives under backend/data/
_DATA_DIR   = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(__file__))), "data"
)
_CACHE_PATH = os.path.join(_DATA_DIR, "dhan_scrip_master.json")
_CACHE_TTL  = 24 * 3600   # refresh once per day

# Map Dhan SEM_SEGMENT letter -> Option Chain API UnderlyingSeg value
_SEGMENT_API = {
    "I": "IDX_I",     # index
    "E": "NSE_EQ",    # equity cash
}

_lock = threading.Lock()
_map: dict[str, dict] | None = None    # symbol -> {"security_id": int, "segment": str}
_loaded_at: float = 0.0


def _download_and_parse() -> dict[str, dict]:
    """Download the scrip master CSV and build the underlying lookup map."""
    logger.info("[DHAN-SCRIP] Downloading scrip master from %s", _CSV_URL)
    resp = _http.get(_CSV_URL, timeout=60)
    resp.raise_for_status()
    text = resp.text

    reader = csv.DictReader(io.StringIO(text))
    result: dict[str, dict] = {}

    for row in reader:
        exch = (row.get("SEM_EXM_EXCH_ID") or "").strip()
        seg  = (row.get("SEM_SEGMENT") or "").strip()
        inst = (row.get("SEM_INSTRUMENT_NAME") or "").strip().upper()
        if exch != "NSE":
            continue

        api_seg = _SEGMENT_API.get(seg)
        if api_seg is None:
            continue

        # Only underlyings: indices (INDEX) and equities (EQUITY)
        if seg == "I" and inst != "INDEX":
            continue
        if seg == "E" and inst != "EQUITY":
            continue

        try:
            sec_id = int(str(row.get("SEM_SMST_SECURITY_ID")).strip())
        except (TypeError, ValueError):
            continue

        symbol = (row.get("SEM_TRADING_SYMBOL") or "").strip().upper()
        if not symbol:
            continue

        # Equity wins ties only if symbol not already an index. Index entries
        # are added first by being uncommon; to be safe, don't overwrite an
        # existing index entry with an equity of the same trading symbol.
        if symbol in result and result[symbol]["segment"] == "IDX_I":
            continue

        result[symbol] = {"security_id": sec_id, "segment": api_seg}

    logger.info("[DHAN-SCRIP] Parsed %d NSE underlyings (index + equity)", len(result))
    return result


def _save_cache(data: dict[str, dict]) -> None:
    try:
        os.makedirs(_DATA_DIR, exist_ok=True)
        with open(_CACHE_PATH, "w", encoding="utf-8") as fh:
            json.dump({"saved_at": time.time(), "map": data}, fh)
    except Exception as exc:
        logger.warning("[DHAN-SCRIP] Could not write cache: %s", exc)


def _load_cache() -> tuple[dict[str, dict] | None, float]:
    try:
        with open(_CACHE_PATH, "r", encoding="utf-8") as fh:
            blob = json.load(fh)
        return blob.get("map") or {}, float(blob.get("saved_at", 0))
    except FileNotFoundError:
        return None, 0.0
    except Exception as exc:
        logger.warning("[DHAN-SCRIP] Could not read cache: %s", exc)
        return None, 0.0


def _ensure_loaded(force: bool = False) -> dict[str, dict]:
    global _map, _loaded_at
    with _lock:
        now = time.time()
        if not force and _map is not None and (now - _loaded_at) < _CACHE_TTL:
            return _map

        # Try disk cache first (survives restarts)
        if not force:
            disk_map, saved_at = _load_cache()
            if disk_map and (now - saved_at) < _CACHE_TTL:
                _map = disk_map
                _loaded_at = saved_at
                logger.info("[DHAN-SCRIP] Loaded %d underlyings from disk cache", len(disk_map))
                return _map

        # Download fresh
        try:
            fresh = _download_and_parse()
            if fresh:
                _map = fresh
                _loaded_at = now
                _save_cache(fresh)
                return _map
        except Exception as exc:
            logger.error("[DHAN-SCRIP] Download failed: %s", exc)
            # Fall back to whatever we have (stale disk or in-memory)
            disk_map, _ = _load_cache()
            if disk_map:
                _map = disk_map
                _loaded_at = now
                logger.warning("[DHAN-SCRIP] Using stale cache (%d entries)", len(disk_map))
                return _map
            if _map is not None:
                return _map
            raise

        return _map or {}


def lookup(symbol: str) -> dict | None:
    """
    Return {"security_id": int, "segment": "IDX_I"|"NSE_EQ"} for a symbol,
    or None if not found.
    """
    symbol = (symbol or "").strip().upper()
    m = _ensure_loaded()
    return m.get(symbol)


def refresh() -> int:
    """Force a re-download. Returns the number of underlyings loaded."""
    m = _ensure_loaded(force=True)
    return len(m)
