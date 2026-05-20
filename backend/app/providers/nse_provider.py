"""
NSE data provider.

Responsible for fetching and parsing raw data from NSE's public CSV endpoints.
All functions return plain Python data structures — no SQLAlchemy models.

⚠ NSE Rate-limiting / Blocking
NSE's website actively blocks automated HTTP requests from non-browser User-Agents
and from IPs outside India.  This provider sends realistic browser headers and
caches responses to disk.  Despite this, fetches may still fail in some environments
(cloud VMs, Windows without a local browser session, etc.).

Fallback strategy:
  1.  Try live fetch with a spoofed browser UA and session cookies.
  2.  If that fails, look for a locally cached copy in CACHE_DIR.
  3.  If no cache exists, log a warning and return an empty list.
  Callers should always check whether the result is empty before persisting.

Manual import alternative (recommended for production bootstrapping):
  1.  Download https://www.nseindia.com/market-data/securities-available-for-trading
      → "Download CSV" button while logged in to the NSE website in your browser.
  2.  Save as  backend/data/nse_equity_securities.csv
  3.  Run  flask nse import-industry-csv  (reads from backend/data/)
"""

import csv
import io
import logging
import os
import time
from pathlib import Path
from typing import Optional

import requests

logger = logging.getLogger(__name__)

# ── Configuration ──────────────────────────────────────────────────────────────

# Directory for cached CSV responses. Created automatically if missing.
_BASE_DIR = Path(__file__).resolve().parent.parent.parent   # backend/
CACHE_DIR  = _BASE_DIR / "data" / "nse_cache"

# URLs (as of 2025 — NSE restructures these periodically)
_EQUITY_SECURITIES_URL = (
    "https://www.nseindia.com/api/equity-stockIndices?index=SECURITIES%20IN%20F%26O"
)
# The proper CSV for all equity listings:
_EQUITY_LIST_CSV_URL = (
    "https://archives.nseindia.com/content/equities/EQUITY_L.csv"
)
# Index constituent endpoint (replace INDEX_NAME with URL-encoded index name)
_INDEX_CONSTITUENT_URL = (
    "https://www.nseindia.com/api/equity-stockIndices?index={index_name}"
)

# Browser-like headers to reduce chance of being blocked
_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-IN,en;q=0.9",
    "Accept-Encoding": "gzip, deflate, br",
    "Connection": "keep-alive",
    "Referer": "https://www.nseindia.com/",
}

_REQUEST_TIMEOUT = 20          # seconds
_SESSION_WARM_URL = "https://www.nseindia.com/"   # warm up cookies before API call


# ── Session management ─────────────────────────────────────────────────────────

def _make_session() -> requests.Session:
    """
    Create a requests session with browser-like headers.
    Performs a warm-up GET to nseindia.com to obtain session cookies
    (NSE API rejects cookie-less requests).
    """
    session = requests.Session()
    session.headers.update(_HEADERS)
    try:
        session.get(_SESSION_WARM_URL, timeout=_REQUEST_TIMEOUT)
        time.sleep(1)   # brief pause — mimics real browser behaviour
    except Exception as exc:
        logger.warning("NSE session warm-up failed: %s", exc)
    return session


# ── Caching helpers ────────────────────────────────────────────────────────────

def _cache_path(filename: str) -> Path:
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    return CACHE_DIR / filename


def _read_cache(filename: str) -> Optional[str]:
    p = _cache_path(filename)
    if p.exists():
        logger.info("NSE provider: using cached file %s", p)
        return p.read_text(encoding="utf-8")
    return None


def _write_cache(filename: str, content: str) -> None:
    _cache_path(filename).write_text(content, encoding="utf-8")
    logger.info("NSE provider: cached response to %s", _cache_path(filename))


# ── Equity master CSV (EQUITY_L.csv from NSE archives) ────────────────────────

def fetch_equity_list_csv() -> Optional[str]:
    """
    Fetch the full NSE equity list CSV from the NSE archives mirror.
    Returns raw CSV text, or None on failure.

    NSE archives (archives.nseindia.com) are more reliably accessible than
    the main website API.  This CSV is updated each trading day.

    Columns (approximate): SYMBOL, NAME OF COMPANY, SERIES, DATE OF LISTING,
    PAID UP VALUE, MARKET LOT, ISIN NUMBER, FACE VALUE
    """
    cache_file = "EQUITY_L.csv"
    cached = _read_cache(cache_file)
    if cached:
        return cached

    try:
        logger.info("NSE provider: fetching EQUITY_L.csv from NSE archives...")
        session = _make_session()
        resp = session.get(_EQUITY_LIST_CSV_URL, timeout=_REQUEST_TIMEOUT)
        resp.raise_for_status()
        content = resp.text
        _write_cache(cache_file, content)
        return content
    except Exception as exc:
        logger.error("NSE provider: failed to fetch EQUITY_L.csv — %s", exc)
        return None


def parse_equity_list_csv(csv_text: str) -> list[dict]:
    """
    Parse the EQUITY_L.csv text.

    Returns a list of dicts:
        {
            "symbol": str,
            "company_name": str,
            "series": str,
            "isin": str,
            "yfinance_symbol": str,   # symbol + ".NS"
        }
    """
    results = []
    reader = csv.DictReader(io.StringIO(csv_text))
    for row in reader:
        # Normalise key names — NSE sometimes adds trailing spaces
        row = {k.strip(): v.strip() for k, v in row.items() if k}
        symbol = row.get("SYMBOL", "").strip().upper()
        if not symbol:
            continue
        results.append({
            "symbol": symbol,
            "company_name": row.get("NAME OF COMPANY", "") or row.get("COMPANY NAME", ""),
            "series": row.get("SERIES", "EQ"),
            "isin": row.get("ISIN NUMBER", "") or row.get("ISIN", ""),
            "yfinance_symbol": f"{symbol}.NS",
        })
    logger.info("NSE provider: parsed %d equity records", len(results))
    return results


# ── Industry classification CSV ────────────────────────────────────────────────

def parse_industry_csv(csv_text: str) -> list[dict]:
    """
    Parse NSE's industry classification CSV.

    NSE provides this as a downloadable CSV from:
    https://www.nseindia.com/market-data/securities-available-for-trading
    (manual download required — save to backend/data/nse_industry.csv)

    Expected columns (NSE format):
        Symbol, Series, Company Name, ISIN, Macro Sector, Sector, Industry, Basic Industry

    Returns a list of dicts with those fields, keyed by symbol.
    """
    results = []
    reader = csv.DictReader(io.StringIO(csv_text))
    for row in reader:
        row = {k.strip(): v.strip() for k, v in row.items() if k}
        symbol = row.get("Symbol", "").strip().upper()
        if not symbol:
            continue
        results.append({
            "symbol": symbol,
            "series": row.get("Series", ""),
            "company_name": row.get("Company Name", ""),
            "isin": row.get("ISIN", ""),
            "macro_sector": row.get("Macro Sector", ""),
            "sector": row.get("Sector", ""),
            "industry": row.get("Industry", ""),
            "basic_industry": row.get("Basic Industry", ""),
        })
    logger.info("NSE provider: parsed %d industry records", len(results))
    return results


# ── Index constituent fetching ────────────────────────────────────────────────

# Map of universe slug → NSE index name (as used in the API)
SECTORAL_INDEX_MAP = {
    "nifty50":      "NIFTY 50",
    "nifty100":     "NIFTY 100",
    "nifty500":     "NIFTY 500",
    "nifty_bank":   "NIFTY BANK",
    "nifty_it":     "NIFTY IT",
    "nifty_pharma": "NIFTY PHARMA",
    "nifty_auto":   "NIFTY AUTO",
    "nifty_fno":    "SECURITIES IN F&O",
    "nifty_midcap": "NIFTY MIDCAP 100",
    "nifty_smallcap": "NIFTY SMALLCAP 100",
}


def fetch_index_constituents(universe_slug: str) -> list[str]:
    """
    Fetch constituent symbols for a known NSE index.

    Returns a list of NSE symbols (strings), e.g. ["RELIANCE", "TCS", ...].
    Returns [] on any error — callers must handle empty results.

    This endpoint is the JSON API, not a CSV.  Each data item has a "symbol" key.
    """
    index_name = SECTORAL_INDEX_MAP.get(universe_slug)
    if not index_name:
        logger.warning("NSE provider: no index mapping for slug '%s'", universe_slug)
        return []

    cache_file = f"index_{universe_slug}.json"
    cached = _read_cache(cache_file)
    if cached:
        return _parse_index_json(cached)

    url = _INDEX_CONSTITUENT_URL.format(index_name=requests.utils.quote(index_name))
    try:
        logger.info("NSE provider: fetching constituents for '%s'...", index_name)
        session = _make_session()
        # NSE requires the Referer header for this specific endpoint
        session.headers["Referer"] = (
            f"https://www.nseindia.com/market-data/live-equity-market?symbol={index_name}"
        )
        resp = session.get(url, timeout=_REQUEST_TIMEOUT)
        resp.raise_for_status()
        _write_cache(cache_file, resp.text)
        return _parse_index_json(resp.text)
    except Exception as exc:
        logger.error(
            "NSE provider: failed to fetch index '%s' — %s", index_name, exc
        )
        return []


def _parse_index_json(json_text: str) -> list[str]:
    import json
    try:
        data = json.loads(json_text)
        items = data.get("data", [])
        symbols = []
        for item in items:
            sym = item.get("symbol", "").strip().upper()
            if sym and sym != "-":
                symbols.append(sym)
        return symbols
    except Exception as exc:
        logger.error("NSE provider: failed to parse index JSON — %s", exc)
        return []


# ── Industry classification via niftyindices.com constituent CSVs ─────────────
#
# niftyindices.com (run by NSE Indices Ltd.) publishes constituent CSVs for
# every NIFTY index.  These CSVs are publicly accessible without cookies or
# session warm-up.  Each CSV has the columns:
#       Company Name, Industry, Symbol, Series, ISIN Code
#
# "Industry" here is NSE's own classification label (e.g. "Financial Services",
# "Information Technology", "Healthcare").  We write it to both `sector` and
# `industry` fields — sector is what powers the `list-sectors` CLI command.
#
# Primary host : https://niftyindices.com/IndexConstituent/<filename>
# Fallback host: https://archives.nseindia.com/content/indices/<filename>

_NIFTYINDICES_BASE = "https://niftyindices.com/IndexConstituent/"
_NSE_ARCHIVES_IDX  = "https://archives.nseindia.com/content/indices/"

# Ordered by descending coverage so that broader indices are processed first.
# Sectoral indices fill in any symbols not present in the broad ones.
# Each entry: (label_for_logging, csv_filename)
CLASSIFICATION_CSVS: list[tuple[str, str]] = [
    ("NIFTY 500",              "ind_nifty500list.csv"),
    ("NIFTY Midcap 150",       "ind_niftymidcap150list.csv"),
    ("NIFTY Smallcap 250",     "ind_niftysmallcap250list.csv"),
    ("NIFTY Bank",             "ind_niftybanklist.csv"),
    ("NIFTY IT",               "ind_niftyitlist.csv"),
    ("NIFTY Pharma",           "ind_niftypharmalist.csv"),
    ("NIFTY Auto",             "ind_niftyautolist.csv"),
    ("NIFTY FMCG",             "ind_niftyfmcglist.csv"),
    ("NIFTY Media",            "ind_niftymedialist.csv"),
    ("NIFTY Metal",            "ind_niftymetallist.csv"),
    ("NIFTY Oil & Gas",        "ind_niftyoilgaslist.csv"),
    ("NIFTY Realty",           "ind_niftyrealtylist.csv"),
    ("NIFTY Fin Services",     "ind_niftyfinancialservices25-50list.csv"),
]

# Broad macro-sector groupings derived from the "Industry" label in the CSVs.
# Used to populate nse_stocks.macro_sector.
_MACRO_MAP: dict[str, str] = {
    "financial services":                     "FINANCIAL SERVICES",
    "banking":                                "FINANCIAL SERVICES",
    "insurance":                              "FINANCIAL SERVICES",
    "information technology":                 "INFORMATION TECHNOLOGY",
    "technology":                             "INFORMATION TECHNOLOGY",
    "it-software":                            "INFORMATION TECHNOLOGY",
    "healthcare":                             "HEALTHCARE",
    "pharmaceuticals":                        "HEALTHCARE",
    "pharma":                                 "HEALTHCARE",
    "automobile and auto components":         "AUTOMOBILE",
    "automobile":                             "AUTOMOBILE",
    "auto":                                   "AUTOMOBILE",
    "fast moving consumer goods":             "CONSUMER GOODS",
    "fmcg":                                   "CONSUMER GOODS",
    "consumer durables":                      "CONSUMER GOODS",
    "consumer services":                      "CONSUMER SERVICES",
    "textiles":                               "CONSUMER GOODS",
    "oil gas & consumable fuels":             "ENERGY",
    "oil gas":                                "ENERGY",
    "power":                                  "ENERGY",
    "metals & mining":                        "MATERIALS",
    "metals":                                 "MATERIALS",
    "mining":                                 "MATERIALS",
    "chemicals":                              "MATERIALS",
    "forest materials":                       "MATERIALS",
    "capital goods":                          "INDUSTRIALS",
    "construction":                           "INDUSTRIALS",
    "infrastructure":                         "INDUSTRIALS",
    "realty":                                 "REAL ESTATE",
    "real estate":                            "REAL ESTATE",
    "media entertainment & publication":      "COMMUNICATION SERVICES",
    "media":                                  "COMMUNICATION SERVICES",
    "telecommunications":                     "COMMUNICATION SERVICES",
    "telecom":                                "COMMUNICATION SERVICES",
    "services":                               "SERVICES",
    "agriculture":                            "AGRICULTURE",
    "diversified":                            "DIVERSIFIED",
}


def _derive_macro_sector(industry_label: str) -> str:
    """
    Derive a broad macro-sector string from an NSE industry label.
    Returns empty string if no mapping found (caller should store NULL).
    """
    key = industry_label.strip().lower()
    # Exact match first
    if key in _MACRO_MAP:
        return _MACRO_MAP[key]
    # Partial match — check if key contains any known keyword
    for k, v in _MACRO_MAP.items():
        if k in key or key in k:
            return v
    return ""


def fetch_classification_csv(filename: str) -> Optional[str]:
    """
    Fetch a single niftyindices.com constituent CSV by filename.

    Tries niftyindices.com first, then archives.nseindia.com as fallback.
    Uses a per-file disk cache to avoid re-fetching on every run.
    Returns raw CSV text, or None on total failure.
    """
    cache_file = f"classif_{filename}"
    # No cache hit check here — always fetch fresh for classification
    # (cache is only for EQUITY_L.csv which changes daily)

    _headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/124.0.0.0 Safari/537.36"
        ),
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "en-IN,en;q=0.9",
        "Referer": "https://niftyindices.com/",
    }

    for base_url in (_NIFTYINDICES_BASE, _NSE_ARCHIVES_IDX):
        url = base_url + filename
        try:
            resp = requests.get(url, headers=_headers, timeout=_REQUEST_TIMEOUT)
            resp.raise_for_status()
            text = resp.text.strip()
            # Validate: first line must be the known header (not an HTML error page)
            first = text.splitlines()[0] if text else ""
            if "Company Name" in first and "Symbol" in first:
                logger.info(
                    "NSE provider: fetched %s from %s (%d lines)",
                    filename, base_url, len(text.splitlines()),
                )
                return text
            else:
                logger.warning(
                    "NSE provider: %s from %s looks like HTML, skipping",
                    filename, base_url,
                )
        except Exception as exc:
            logger.warning("NSE provider: %s from %s failed — %s", filename, base_url, exc)

    return None


def parse_classification_csv(csv_text: str) -> list[dict]:
    """
    Parse a niftyindices.com constituent CSV.

    Columns: Company Name, Industry, Symbol, Series, ISIN Code

    Returns list of dicts:
        {
            "symbol":       str,
            "company_name": str,
            "isin":         str,
            "industry":     str,   # NSE's label, e.g. "Financial Services"
            "sector":       str,   # same value — the finest grain available here
            "macro_sector": str,   # derived from industry label
        }
    Rows where Symbol is empty or looks like HTML are skipped.
    """
    results = []
    try:
        reader = csv.DictReader(io.StringIO(csv_text))
        for row in reader:
            row = {k.strip(): v.strip() for k, v in row.items() if k}
            symbol = row.get("Symbol", "").strip().upper()
            if not symbol or len(symbol) > 20 or "<" in symbol:
                continue   # skip blank rows and any HTML bleed-through
            industry = row.get("Industry", "").strip()
            results.append({
                "symbol":       symbol,
                "company_name": row.get("Company Name", "").strip(),
                "isin":         row.get("ISIN Code", "").strip(),
                "industry":     industry,
                "sector":       industry,   # use industry as sector (same level in NSE hierarchy)
                "macro_sector": _derive_macro_sector(industry),
            })
    except Exception as exc:
        logger.error("NSE provider: parse_classification_csv error — %s", exc)
    return results


def fetch_all_classification_data() -> dict[str, dict]:
    """
    Fetch and merge industry classification data from all CLASSIFICATION_CSVS.

    Processes broader indices first so that a stock's classification from
    NIFTY 500 takes precedence over a narrower sectoral index.

    Returns:
        { "RELIANCE": {"industry": ..., "sector": ..., "macro_sector": ...,
                       "company_name": ..., "isin": ...}, ... }

    Stocks not found in any CSV will not appear in the result — caller
    should treat missing entries as "no classification available".
    """
    merged: dict[str, dict] = {}
    fetched = 0
    failed = 0

    for label, filename in CLASSIFICATION_CSVS:
        csv_text = fetch_classification_csv(filename)
        if not csv_text:
            logger.warning("NSE provider: could not fetch '%s' (%s)", label, filename)
            failed += 1
            continue

        records = parse_classification_csv(csv_text)
        new_symbols = 0
        for rec in records:
            sym = rec["symbol"]
            if sym not in merged:
                merged[sym] = {
                    "industry":     rec["industry"],
                    "sector":       rec["sector"],
                    "macro_sector": rec["macro_sector"],
                    "company_name": rec["company_name"],
                    "isin":         rec["isin"],
                }
                new_symbols += 1
            # If already present (from a broader index), don't overwrite —
            # broader index classification is preferred.

        fetched += 1
        logger.info(
            "NSE provider: %s — %d total rows, %d new symbols (running total: %d)",
            label, len(records), new_symbols, len(merged),
        )
        time.sleep(0.3)   # be polite

    logger.info(
        "NSE provider: fetch_all_classification_data done — "
        "%d CSVs fetched, %d failed, %d unique symbols classified",
        fetched, failed, len(merged),
    )
    return merged


# ── Symbol helpers ─────────────────────────────────────────────────────────────

def normalize_symbol(raw: str) -> str:
    """Strip whitespace, uppercase. NSE symbols are always uppercase."""
    return raw.strip().upper()


def to_yfinance_symbol(nse_symbol: str) -> str:
    """Convert NSE symbol to yfinance ticker. e.g. 'RELIANCE' → 'RELIANCE.NS'"""
    return f"{normalize_symbol(nse_symbol)}.NS"
