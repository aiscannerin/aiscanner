"""
Universe service.

Orchestrates NSE stock master sync, universe population, and sector-based
universe generation.  All public functions are safe to call from CLI commands
or API routes — they handle their own DB commits.

Key public functions:
    sync_nse_equity_master()      ← fetch + upsert all equity symbols
    import_industry_csv(path)     ← enrich sector data from a local CSV
    sync_sectoral_universes()     ← build universes from NSE index API
    sync_default_universes()      ← ensure built-in universes exist in DB
    get_symbols_for_universe(slug) ← called by scanner at scan time
    get_all_sectors()             ← for market-data API
    get_stocks_by_sector(sector)  ← for market-data API
"""

import logging
from pathlib import Path
from typing import Optional

from app.extensions import db
from app.providers import nse_provider
from app.repositories.nse_stock_repository import NseStockRepository
from app.repositories.nse_universe_repository import NseUniverseRepository

logger = logging.getLogger(__name__)

# ── Repository singletons (stateless — safe to share) ─────────────────────────
_stock_repo    = NseStockRepository()
_universe_repo = NseUniverseRepository()

# ── Built-in universe definitions ──────────────────────────────────────────────
# These are always created in the DB (even if their memberships are empty).
_DEFAULT_UNIVERSES = [
    {
        "slug": "nifty50",
        "name": "NIFTY 50",
        "description": "The 50 large-cap companies listed on NSE forming the NIFTY 50 index.",
        "source": "index",
    },
    {
        "slug": "nifty100",
        "name": "NIFTY 100",
        "description": "Top 100 companies by market capitalisation on NSE.",
        "source": "index",
    },
    {
        "slug": "nifty500",
        "name": "NIFTY 500",
        "description": "Top 500 companies on NSE — broad market universe.",
        "source": "index",
    },
    {
        "slug": "nifty_bank",
        "name": "NIFTY Bank",
        "description": "India's most liquid banking sector stocks on NSE.",
        "source": "index",
    },
    {
        "slug": "nifty_it",
        "name": "NIFTY IT",
        "description": "Top information technology companies on NSE.",
        "source": "index",
    },
    {
        "slug": "nifty_pharma",
        "name": "NIFTY Pharma",
        "description": "Pharmaceutical and life sciences companies on NSE.",
        "source": "index",
    },
    {
        "slug": "nifty_auto",
        "name": "NIFTY Auto",
        "description": "Automobile and auto ancillary companies on NSE.",
        "source": "index",
    },
    {
        "slug": "nifty_fno",
        "name": "NSE F&O",
        "description": "All NSE stocks available for Futures & Options trading.",
        "source": "index",
    },
    {
        "slug": "nifty_midcap",
        "name": "NIFTY Midcap 100",
        "description": "Top 100 mid-capitalisation companies on NSE.",
        "source": "index",
    },
    {
        "slug": "nifty_smallcap",
        "name": "NIFTY Smallcap 100",
        "description": "Top 100 small-capitalisation companies on NSE.",
        "source": "index",
    },
]


# ── Public API ─────────────────────────────────────────────────────────────────

def sync_nse_equity_master() -> dict:
    """
    Fetch EQUITY_L.csv from NSE archives and upsert into nse_stocks table.

    Returns a summary dict:
        { "total": int, "created": int, "updated": int, "error": str|None }
    """
    csv_text = nse_provider.fetch_equity_list_csv()
    if not csv_text:
        msg = (
            "NSE equity list fetch returned no data.  "
            "Try running `flask nse import-industry-csv` with a manually "
            "downloaded CSV instead."
        )
        logger.error(msg)
        return {"total": 0, "created": 0, "updated": 0, "error": msg}

    records = nse_provider.parse_equity_list_csv(csv_text)
    if not records:
        return {"total": 0, "created": 0, "updated": 0, "error": "CSV parsed 0 records."}

    created = updated = 0
    active_symbols: set[str] = set()

    for rec in records:
        symbol = rec["symbol"]
        active_symbols.add(symbol)
        _, was_created = _stock_repo.upsert(symbol, {
            "company_name": rec.get("company_name"),
            "series":       rec.get("series", "EQ"),
            "isin":         rec.get("isin") or None,
            "yfinance_symbol": nse_provider.to_yfinance_symbol(symbol),
            "is_active": True,
        })
        if was_created:
            created += 1
        else:
            updated += 1

    # Mark symbols no longer in the list as inactive
    deactivated = _stock_repo.deactivate_missing(active_symbols)
    db.session.commit()

    logger.info(
        "sync_nse_equity_master: total=%d created=%d updated=%d deactivated=%d",
        len(records), created, updated, deactivated,
    )
    return {
        "total": len(records),
        "created": created,
        "updated": updated,
        "deactivated": deactivated,
        "error": None,
    }


def import_industry_csv(file_path: str | Path) -> dict:
    """
    Read a locally saved NSE industry classification CSV and enrich
    the nse_stocks table with sector / industry / macro_sector fields.

    The CSV must have columns:
        Symbol, Series, Company Name, ISIN, Macro Sector, Sector, Industry, Basic Industry

    Args:
        file_path: absolute path to the CSV file

    Returns:
        { "total": int, "updated": int, "skipped": int, "error": str|None }
    """
    try:
        text = Path(file_path).read_text(encoding="utf-8")
    except Exception as exc:
        msg = f"Could not read file {file_path}: {exc}"
        logger.error(msg)
        return {"total": 0, "updated": 0, "skipped": 0, "error": msg}

    records = nse_provider.parse_industry_csv(text)
    if not records:
        return {"total": 0, "updated": 0, "skipped": 0, "error": "CSV parsed 0 records."}

    updated = skipped = 0
    for rec in records:
        symbol = rec["symbol"]
        stock = _stock_repo.get_by_symbol(symbol)
        if not stock:
            # Symbol not in nse_stocks yet — upsert it
            stock, _ = _stock_repo.upsert(symbol, {
                "company_name":   rec.get("company_name"),
                "series":         rec.get("series", "EQ"),
                "isin":           rec.get("isin") or None,
                "yfinance_symbol": nse_provider.to_yfinance_symbol(symbol),
                "is_active": True,
            })

        stock.macro_sector  = rec.get("macro_sector") or None
        stock.sector        = rec.get("sector") or None
        stock.industry      = rec.get("industry") or None
        stock.basic_industry = rec.get("basic_industry") or None
        if rec.get("isin"):
            stock.isin = rec["isin"]
        updated += 1

    db.session.commit()
    logger.info("import_industry_csv: total=%d updated=%d skipped=%d", len(records), updated, skipped)
    return {"total": len(records), "updated": updated, "skipped": skipped, "error": None}


def sync_default_universes() -> dict:
    """
    Ensure all built-in universe rows exist in the DB (name/description/source).
    Does NOT sync their memberships — call sync_sectoral_universes() for that.

    Safe to run multiple times.
    Returns { "created": int, "existing": int }
    """
    created = existing = 0
    for defn in _DEFAULT_UNIVERSES:
        _, was_created = _universe_repo.upsert(defn["slug"], defn)
        if was_created:
            created += 1
        else:
            existing += 1
    db.session.commit()
    logger.info("sync_default_universes: created=%d existing=%d", created, existing)
    return {"created": created, "existing": existing}


def sync_industry_classification() -> dict:
    """
    Fetch industry classification data from niftyindices.com constituent CSVs
    and enrich nse_stocks with sector / industry / macro_sector.

    Sources (all publicly accessible, no login required):
        niftyindices.com/IndexConstituent/ind_nifty500list.csv   (500 stocks)
        niftyindices.com/IndexConstituent/ind_niftymidcap150list.csv
        niftyindices.com/IndexConstituent/ind_niftysmallcap250list.csv
        + 10 sectoral indices (Bank, IT, Pharma, Auto, FMCG, Media, Metal,
          Oil & Gas, Realty, Fin Services)

    Field mapping from CSV "Industry" column:
        nse_stocks.sector       ← Industry label  (e.g. "Financial Services")
        nse_stocks.industry     ← Industry label  (same — finest grain available)
        nse_stocks.macro_sector ← derived mapping (e.g. "FINANCIAL SERVICES")

    Stocks not found in any index CSV are skipped — their classification remains
    NULL.  Run `flask nse import-industry-csv` with a manually downloaded NSE
    classification CSV to cover all listed stocks.

    Returns:
        {
            "classified": int,   # stocks updated with sector data
            "skipped":    int,   # stocks in DB not found in any index CSV
            "not_in_db":  int,   # symbols in index CSVs not yet in nse_stocks
            "csv_fetched": int,
            "csv_failed":  int,
            "error":      str | None,
        }
    """
    from app.providers.nse_provider import (
        fetch_all_classification_data,
        CLASSIFICATION_CSVS,
    )

    logger.info("universe_service: starting sync_industry_classification")
    classification = fetch_all_classification_data()

    if not classification:
        msg = (
            "No classification data could be fetched from niftyindices.com or NSE archives.\n"
            "Manual fallback: download the NSE industry classification CSV from\n"
            "  https://www.nseindia.com/market-data/securities-available-for-trading\n"
            "Save it as  backend/data/nse_industry.csv  then run:\n"
            "  flask nse import-industry-csv\n\n"
            "Expected CSV columns:\n"
            "  Symbol, Series, Company Name, ISIN, Macro Sector, Sector, Industry, Basic Industry"
        )
        logger.error(msg)
        return {
            "classified": 0, "skipped": 0, "not_in_db": 0,
            "csv_fetched": 0, "csv_failed": len(CLASSIFICATION_CSVS),
            "error": msg,
        }

    classified = skipped = not_in_db = 0
    all_stocks = _stock_repo.get_all()
    stock_map  = {s.symbol: s for s in all_stocks}

    for symbol, data in classification.items():
        stock = stock_map.get(symbol)
        if not stock:
            not_in_db += 1
            # Auto-create a stub if the symbol is unknown — will be enriched later
            # by sync-stocks. We skip creation here to avoid polluting the DB with
            # stocks that may not be on NSE (could be BSE-only, delisted, etc.).
            continue

        changed = False
        for field in ("sector", "industry", "macro_sector"):
            val = data.get(field) or None
            if val and getattr(stock, field) != val:
                setattr(stock, field, val)
                changed = True

        # Also backfill company_name and isin if missing
        if not stock.company_name and data.get("company_name"):
            stock.company_name = data["company_name"]
            changed = True
        if not stock.isin and data.get("isin"):
            stock.isin = data["isin"]
            changed = True

        if changed:
            classified += 1

    # Count stocks in DB that had no match in any classification CSV
    for symbol, stock in stock_map.items():
        if symbol not in classification:
            if stock.is_active:
                skipped += 1

    db.session.commit()

    total_csvs = len(CLASSIFICATION_CSVS)
    logger.info(
        "sync_industry_classification: classified=%d skipped=%d not_in_db=%d",
        classified, skipped, not_in_db,
    )
    return {
        "classified":  classified,
        "skipped":     skipped,
        "not_in_db":   not_in_db,
        "csv_fetched": total_csvs,
        "csv_failed":  0,
        "error":       None,
    }


def sync_sectoral_universes(slugs: Optional[list[str]] = None) -> dict:
    """
    Fetch index constituents from NSE API and populate universe memberships.

    Args:
        slugs: list of universe slugs to sync. If None, syncs all in _DEFAULT_UNIVERSES.

    Returns:
        { slug: { "added": int, "skipped": int, "error": str|None }, ... }
    """
    if slugs is None:
        slugs = [u["slug"] for u in _DEFAULT_UNIVERSES if u["source"] == "index"]

    # Ensure universe rows exist
    sync_default_universes()

    results = {}
    for slug in slugs:
        universe = _universe_repo.get_by_slug(slug)
        if not universe:
            results[slug] = {"added": 0, "skipped": 0, "error": f"Universe '{slug}' not found."}
            continue

        symbols = nse_provider.fetch_index_constituents(slug)
        if not symbols:
            results[slug] = {
                "added": 0,
                "skipped": 0,
                "error": (
                    f"No constituents returned for '{slug}'. "
                    "NSE may be blocking the request.  "
                    "Manually add symbols via the industry CSV import."
                ),
            }
            continue

        pairs = [(sym, None) for sym in symbols]   # no weight data from this endpoint
        added, skipped = _universe_repo.replace_memberships(universe, pairs)
        _universe_repo.mark_synced(universe)
        db.session.commit()

        results[slug] = {"added": added, "skipped": skipped, "error": None}
        logger.info("sync_sectoral_universes: %s — added=%d skipped=%d", slug, added, skipped)

    return results


# ── Scanner-facing helpers ────────────────────────────────────────────────────

def get_symbols_for_universe(slug: str) -> list[str]:
    """
    Return NSE symbols for a universe slug.

    Falls back to the hardcoded list in scanner_job_service for backward
    compatibility if the DB universe is empty (i.e. sync hasn't run yet).
    Returns [] if neither source has data.
    """
    symbols = _universe_repo.get_symbols_for_universe(slug)
    if symbols:
        return symbols

    # Graceful fallback — return [] and let scanner_job_service use its own list
    logger.warning(
        "universe_service: universe '%s' is empty in DB — "
        "scanner will use its built-in fallback list.",
        slug,
    )
    return []


# ── Market-data API helpers ───────────────────────────────────────────────────

def get_all_sectors() -> list[str]:
    """Return all distinct sector names with at least one active stock."""
    return _stock_repo.get_distinct_sectors()


def get_all_industries() -> list[str]:
    return _stock_repo.get_distinct_industries()


def get_stocks_by_sector(sector: str) -> list[dict]:
    stocks = _stock_repo.get_by_sector(sector)
    return [s.to_dict() for s in stocks]


def get_stocks_by_industry(industry: str) -> list[dict]:
    stocks = _stock_repo.get_by_industry(industry)
    return [s.to_dict() for s in stocks]


def get_all_universes() -> list[dict]:
    universes = _universe_repo.get_all_active()
    result = []
    for u in universes:
        d = u.to_dict()
        d["stock_count"] = _universe_repo.count_members(u.slug)
        result.append(d)
    return result
