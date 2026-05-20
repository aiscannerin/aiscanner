"""
Market data API routes.

All endpoints require a valid JWT (logged-in user).
No plan gating here — these are informational/utility endpoints.

Response shape (standard across the app):
    { success: true, message: "<string>", data: { ... } }

success() helper signature: success(data=None, message="Success", ...)

Endpoints:
    GET /api/market-data/universes
    GET /api/market-data/sectors
    GET /api/market-data/stocks?universe=<slug>&sector=<sector>&industry=<industry>
    GET /api/market-data/candles?symbol=<NSE_SYMBOL>&timeframe=<tf>&limit=<n>
"""

from flask import request
from flask_jwt_extended import jwt_required

from app.api.market_data import market_data_bp
from app.providers.yfinance_provider import get_candles
from app.services import universe_service
from app.utils.response import error, success


# ── GET /api/market-data/universes ────────────────────────────────────────────

@market_data_bp.get("/universes")
@jwt_required()
def list_universes():
    """Return all active universes with their stock counts."""
    universes = universe_service.get_all_universes()
    return success(
        data={"universes": universes},
        message="Universes fetched.",
    )


# ── GET /api/market-data/sectors ──────────────────────────────────────────────

@market_data_bp.get("/sectors")
@jwt_required()
def list_sectors():
    """Return all distinct sector names present in nse_stocks."""
    sectors = universe_service.get_all_sectors()
    return success(
        data={"sectors": sectors, "count": len(sectors)},
        message="Sectors fetched.",
    )


# ── GET /api/market-data/stocks ───────────────────────────────────────────────

@market_data_bp.get("/stocks")
@jwt_required()
def list_stocks():
    """
    Return stocks filtered by universe slug, sector, or industry.

    Query params (at least one required):
        universe=nifty50
        sector=BANKING
        industry=PRIVATE SECTOR BANK

    Returns up to 1000 stocks.
    """
    universe_slug = request.args.get("universe", "").strip()
    sector        = request.args.get("sector", "").strip()
    industry      = request.args.get("industry", "").strip()

    if not any([universe_slug, sector, industry]):
        return error(
            "Provide at least one filter: universe, sector, or industry.",
            400,
            error_code="FILTER_REQUIRED",
        )

    if universe_slug:
        symbols = universe_service.get_symbols_for_universe(universe_slug)
        return success(
            data={"symbols": symbols, "count": len(symbols), "universe": universe_slug},
            message=f"Stocks for universe '{universe_slug}'.",
        )

    if sector:
        stocks = universe_service.get_stocks_by_sector(sector)
        return success(
            data={"stocks": stocks[:1000], "count": len(stocks), "sector": sector},
            message=f"Stocks for sector '{sector}'.",
        )

    stocks = universe_service.get_stocks_by_industry(industry)
    return success(
        data={"stocks": stocks[:1000], "count": len(stocks), "industry": industry},
        message=f"Stocks for industry '{industry}'.",
    )


# ── GET /api/market-data/candles ──────────────────────────────────────────────

_VALID_TIMEFRAMES = {"15m", "1h", "4h", "1d", "1w"}
_MAX_LIMIT        = 500


@market_data_bp.get("/candles")
@jwt_required()
def get_candles_route():
    """
    Return OHLCV candles for a single NSE symbol.

    Query params:
        symbol=RELIANCE        (NSE symbol, .NS appended automatically)
        timeframe=1d           (15m | 1h | 4h | 1d | 1w, default: 1d)
        limit=200              (max 500, default: 200)
    """
    symbol    = request.args.get("symbol", "").strip().upper()
    timeframe = request.args.get("timeframe", "1d").strip()
    try:
        limit = min(int(request.args.get("limit", 200)), _MAX_LIMIT)
    except ValueError:
        limit = 200

    if not symbol:
        return error("symbol is required.", 400, error_code="SYMBOL_REQUIRED")

    if timeframe not in _VALID_TIMEFRAMES:
        return error(
            f"Invalid timeframe '{timeframe}'. Must be one of: {', '.join(sorted(_VALID_TIMEFRAMES))}.",
            400,
            error_code="INVALID_TIMEFRAME",
        )

    yf_symbol = f"{symbol}.NS" if not symbol.endswith(".NS") else symbol
    candles = get_candles(yf_symbol, timeframe=timeframe, limit=limit)

    return success(
        data={
            "symbol": symbol,
            "yfinance_symbol": yf_symbol,
            "timeframe": timeframe,
            "count": len(candles),
            "candles": candles,
        },
        message=f"Candles for {symbol} ({timeframe}).",
    )
