"""
Scanner job service.

Routes:
  mock mode  → _run_mock_scan()   (random data, uses new classification names)
  live mode  → _run_live_scan()   (real candles + Stop Hunter Pro engine v3)

LTF timeframe map (HTF → LTF):
  1w → 1d
  1d → 4h
  4h → 1h
  1h → 15m
  15m → None (no LTF)
"""

import logging
import random
from datetime import datetime, timezone

from flask import current_app, g

from app.models.scan_job import ScanJobStatus
from app.repositories import scan_job_repository, scan_result_repository, tool_repository
from app.utils.response import error, success, paginated

logger = logging.getLogger(__name__)

# ── Constants ─────────────────────────────────────────────────────────────────

VALID_UNIVERSES  = {"NIFTY50", "NIFTY100", "NIFTY500", "FNO"}
VALID_TIMEFRAMES = {"15m", "1h", "4h", "1d", "1w"}
VALID_MODES      = {"mock", "live"}

# Maps scanner universe names → universe_service slug
_UNIVERSE_TO_SLUG: dict[str, str] = {
    "NIFTY50":  "nifty50",
    "NIFTY100": "nifty100",
    "NIFTY500": "nifty500",
    "FNO":      "nifty_fno",
}

# HTF → LTF timeframe mapping
_LTF_MAP: dict[str, str | None] = {
    "1w":  "1d",
    "1d":  "4h",
    "4h":  "1h",
    "1h":  "15m",
    "15m": None,
}

_LIVE_SYMBOL_DEFAULT = 10
_LIVE_SYMBOL_CAP     = 25

_UNIVERSE_SYMBOLS: dict[str, list[str]] = {
    "NIFTY50": [
        "RELIANCE", "TCS", "HDFCBANK", "INFY", "ICICIBANK",
        "HINDUNILVR", "ITC", "SBIN", "BHARTIARTL", "KOTAKBANK",
    ],
    "NIFTY100": [
        "RELIANCE", "TCS", "HDFCBANK", "INFY", "ICICIBANK",
        "HINDUNILVR", "ITC", "SBIN", "BHARTIARTL", "KOTAKBANK",
        "LT", "AXISBANK", "ASIANPAINT", "MARUTI", "BAJFINANCE",
    ],
    "NIFTY500": [
        "RELIANCE", "TCS", "HDFCBANK", "INFY", "ICICIBANK",
        "ITC", "SBIN", "BHARTIARTL", "KOTAKBANK", "LT",
        "AXISBANK", "ASIANPAINT", "MARUTI", "BAJFINANCE", "WIPRO",
        "ULTRACEMCO", "NTPC", "POWERGRID", "ONGC", "COALINDIA",
    ],
    "FNO": [
        "RELIANCE", "TCS", "INFY", "ICICIBANK", "HDFCBANK",
        "SBIN", "AXISBANK", "BAJFINANCE", "LT", "KOTAKBANK",
    ],
}

_SETUP_TYPES_CONFIRMED = [
    "Stop Hunt + Full LTF Confirm",
    "Liquidity Sweep + ChoCH + OB + LTF Entry",
    "Institutional Stop Run + LTF OB 2.0",
]
_SETUP_TYPES_WATCHLIST = [
    "Liquidity Sweep + ChoCH + HTF OB Active",
    "Stop Hunt + OB Retest Pending",
    "Equal Highs/Lows Sweep + ChoCH",
]
_SETUP_TYPES_NEAR_MISS = [
    "Sweep Only — Awaiting ChoCH",
    "Displacement — No ChoCH",
    "Near Miss — Incomplete HTF Sequence",
]

_REASONS = [
    "Price swept equal highs, grabbed buy-side liquidity, bearish displacement and ChoCH confirmed.",
    "Order block formed after displacement; FVG left unfilled; LTF sweep and ChoCH confirm institutional entry.",
    "HTF OB respected; LTF ChoCH and OB 2.0 align — high-probability institutional entry zone.",
    "Inducement above prior swing high triggered retail longs; smart money reversal with imbalance.",
    "Price swept weekly equal lows; bullish rejection wick; LTF confirmation aligns.",
]


# ── Start scan ────────────────────────────────────────────────────────────────

def start_scan(data: dict):
    """Called from POST /api/scanners/stop-hunter-pro/start after tool access verified."""
    universe  = (data.get("universe")  or "").strip().upper()
    timeframe = (data.get("timeframe") or "").strip().lower()
    mode      = (data.get("mode")      or "mock").strip().lower()
    filters   = data.get("filters") or {}
    if not isinstance(filters, dict):
        filters = {}

    field_errors = []
    if universe not in VALID_UNIVERSES:
        field_errors.append({
            "field": "universe",
            "message": f"Must be one of: {', '.join(sorted(VALID_UNIVERSES))}.",
        })
    if timeframe not in VALID_TIMEFRAMES:
        field_errors.append({
            "field": "timeframe",
            "message": f"Must be one of: {', '.join(sorted(VALID_TIMEFRAMES))}.",
        })
    if mode not in VALID_MODES:
        field_errors.append({
            "field": "mode",
            "message": "Must be 'mock' or 'live'.",
        })
    if field_errors:
        return error("Validation failed.", 400, errors=field_errors)

    tool = g.current_tool

    if mode == "mock":
        return _start_mock(tool, universe, timeframe, filters, mode)
    else:
        return _start_live(tool, universe, timeframe, filters, mode)


# ── Mock path ─────────────────────────────────────────────────────────────────

def _start_mock(tool, universe, timeframe, filters, mode):
    symbols = _UNIVERSE_SYMBOLS.get(universe, [])
    job = scan_job_repository.create(
        user_id=g.current_user.id,
        tool_id=tool.id,
        universe=universe,
        timeframe=timeframe,
        filters=filters,
        total_symbols=len(symbols),
    )
    try:
        _run_mock_scan(job, symbols, timeframe)
    except Exception as exc:
        current_app.logger.error("Mock scan failed for job %s: %s", job.id, exc)
        scan_job_repository.mark_failed(job)
        return error("Scan failed unexpectedly. Please try again.", 500)

    job = scan_job_repository.get_by_id(job.id)
    return success(
        data={
            "job_id":            str(job.id),
            "status":            job.status,
            "universe":          job.universe,
            "timeframe":         job.timeframe,
            "total_symbols":     job.total_symbols,
            "completed_symbols": job.completed_symbols,
            "mode":              mode,
            "scan_health":       job.scan_health_json,
        },
        message="Scan completed. Retrieve results using the job_id.",
        status_code=201,
    )


# ── Live path ─────────────────────────────────────────────────────────────────

def _start_live(tool, universe, timeframe, filters, mode):
    symbols, symbol_source = _resolve_live_symbols(universe, filters)

    if not symbols:
        return error(
            "No symbols could be resolved for this universe/sector. "
            "Run `flask nse sync-stocks` and `flask nse sync-universes` first, "
            "or specify filters.sector to scan a classified sector.",
            422,
            error_code="NO_SYMBOLS",
        )

    ltf_timeframe   = _LTF_MAP.get(timeframe)
    candidate_mode_ = str(filters.get("candidate_mode", "fast"))
    scan_mode_str   = str(filters.get("scan_mode", "present"))

    job = scan_job_repository.create(
        user_id        = g.current_user.id,
        tool_id        = tool.id,
        universe       = universe,
        timeframe      = timeframe,
        filters        = filters,
        total_symbols  = len(symbols),
        scanner_name   = "stop-hunter-pro",
        ltf            = ltf_timeframe,
        scan_mode      = scan_mode_str,
        candidate_mode = candidate_mode_,
    )

    try:
        _run_live_scan(job, symbols, symbol_source, timeframe, filters)
    except Exception as exc:
        current_app.logger.error("Live scan failed for job %s: %s", job.id, exc)
        scan_job_repository.mark_failed(job)
        return error("Live scan failed unexpectedly. Please try again.", 500)

    job = scan_job_repository.get_by_id(job.id)

    if job.status == ScanJobStatus.FAILED:
        return error(
            "Live scan could not fetch candle data for any symbol. "
            "This may be a network or yfinance issue. Try again later.",
            503,
            error_code="LIVE_DATA_UNAVAILABLE",
        )

    return success(
        data={
            "job_id":            str(job.id),
            "status":            job.status,
            "universe":          job.universe,
            "timeframe":         job.timeframe,
            "total_symbols":     job.total_symbols,
            "completed_symbols": job.completed_symbols,
            "mode":              mode,
            "symbol_source":     symbol_source,
            "scan_health":       job.scan_health_json,
        },
        message="Stop Hunter Pro scan completed.",
        status_code=201,
    )


# ── Job status ────────────────────────────────────────────────────────────────

def get_job_status(job_id: str):
    job = _get_owned_job(job_id)
    if isinstance(job, tuple):
        return job
    return success(data=job.to_dict())


# ── Job results ───────────────────────────────────────────────────────────────

def get_job_results(job_id: str, page: int, per_page: int):
    job = _get_owned_job(job_id)
    if isinstance(job, tuple):
        return job

    if job.status not in (ScanJobStatus.COMPLETED, ScanJobStatus.RUNNING):
        return error(
            f"Results are not available. Job status: {job.status}.",
            400,
            error_code="JOB_NOT_READY",
        )

    results, total = scan_result_repository.get_paginated(
        scan_job_id=job.id,
        page=page,
        per_page=per_page,
    )
    return paginated(
        items=[r.to_dict() for r in results],
        total=total,
        page=page,
        per_page=per_page,
    )


# ── Cancel job ────────────────────────────────────────────────────────────────

def cancel_job(job_id: str):
    job = _get_owned_job(job_id)
    if isinstance(job, tuple):
        return job

    cancellable = {ScanJobStatus.QUEUED, ScanJobStatus.RUNNING}
    if job.status not in cancellable:
        return error(
            f"Cannot cancel a job with status '{job.status}'. "
            "Only queued or running jobs can be cancelled.",
            409,
            error_code="JOB_NOT_CANCELLABLE",
        )

    scan_job_repository.mark_cancelled(job)
    return success(message="Scan job cancelled.")


# ── Recent jobs ───────────────────────────────────────────────────────────────

def get_recent_jobs():
    jobs = scan_job_repository.get_recent_for_user(g.current_user.id, limit=20)
    return success(data=[j.to_dict() for j in jobs])


# ── Internal: owned-job guard ─────────────────────────────────────────────────

def _get_owned_job(job_id: str):
    job = scan_job_repository.get_by_id(job_id)
    if not job:
        return error("Scan job not found.", 404, error_code="JOB_NOT_FOUND")
    if str(job.user_id) != str(g.current_user.id):
        return error("This job does not belong to your account.", 403, error_code="JOB_OWNERSHIP_MISMATCH")
    return job


# ── Internal: symbol resolution ───────────────────────────────────────────────

def _resolve_live_symbols(universe: str, filters: dict) -> tuple[list[str], str]:
    from app.services import universe_service
    from app.providers import nse_provider

    max_syms = _LIVE_SYMBOL_DEFAULT
    try:
        max_syms = min(int(filters.get("max_symbols", _LIVE_SYMBOL_DEFAULT)), _LIVE_SYMBOL_CAP)
    except (TypeError, ValueError):
        pass

    slug   = _UNIVERSE_TO_SLUG.get(universe, universe.lower())
    sector = (filters.get("sector") or "").strip()

    if sector:
        stocks = universe_service.get_stocks_by_sector(sector)
        syms   = [s["symbol"] for s in stocks if s.get("symbol")][:max_syms]
        if syms:
            return syms, f"sector:{sector}"
        logger.warning("live resolve: sector '%s' matched 0 stocks — falling through", sector)

    syms = universe_service.get_symbols_for_universe(slug)[:max_syms]
    if syms:
        return syms, f"db-universe:{slug}"

    syms = nse_provider.fetch_index_constituents(slug)[:max_syms]
    if syms:
        return syms, f"live-fetch:{slug}"

    fallback = _UNIVERSE_SYMBOLS.get(universe, _UNIVERSE_SYMBOLS["NIFTY50"])[:max_syms]
    logger.warning("live resolve: all dynamic sources failed for '%s' — using hardcoded fallback", universe)
    return fallback, "hardcoded-fallback"


# ── Internal: mock scanner ────────────────────────────────────────────────────

def _run_mock_scan(job, symbols: list[str], timeframe: str) -> None:
    """
    Synchronous mock scanner with new classification names and checklist fields.
    """
    from app.services.scan_health_service import compute_mock_scan_health
    scan_job_repository.mark_running(job, total_symbols=len(symbols))

    fired_count   = min(random.randint(5, 8), len(symbols))
    fired_symbols = random.sample(symbols, fired_count)

    result_rows = []
    for symbol in fired_symbols:
        direction = random.choice(["bullish", "bearish"])
        cl        = random.choices(
            ["confirmed", "watchlist", "near_miss"],
            weights=[30, 40, 30],
        )[0]

        if cl == "confirmed":
            setup_type = random.choice(_SETUP_TYPES_CONFIRMED)
            score      = round(random.uniform(70.0, 97.5), 2)
        elif cl == "watchlist":
            setup_type = random.choice(_SETUP_TYPES_WATCHLIST)
            score      = round(random.uniform(45.0, 72.0), 2)
        else:
            setup_type = random.choice(_SETUP_TYPES_NEAR_MISS)
            score      = round(random.uniform(20.0, 48.0), 2)

        grade     = _score_to_grade(score, cl)
        base_price = round(random.uniform(200, 3500), 2)
        sl_pct     = round(random.uniform(0.8, 2.5), 2) / 100
        t1_pct     = 2.0 * sl_pct   # 2R
        t2_pct     = 3.5 * sl_pct   # 3.5R

        if direction == "bullish":
            entry     = base_price
            stop_loss = round(entry * (1 - sl_pct), 2)
            target_1  = round(entry * (1 + t1_pct), 2)
            target_2  = round(entry * (1 + t2_pct), 2)
        else:
            entry     = base_price
            stop_loss = round(entry * (1 + sl_pct), 2)
            target_1  = round(entry * (1 - t1_pct), 2)
            target_2  = round(entry * (1 - t2_pct), 2)

        risk = abs(entry - stop_loss)

        has_disp   = cl in ("confirmed", "watchlist") or random.random() > 0.3
        has_fvg    = cl in ("confirmed", "watchlist") or random.random() > 0.4
        has_choch  = cl in ("confirmed", "watchlist") or random.random() > 0.5
        has_ob     = cl in ("confirmed", "watchlist") or random.random() > 0.5
        has_retest = cl == "confirmed" or (cl == "watchlist" and random.random() > 0.5)
        ltf_sweep  = cl == "confirmed"
        ltf_choch  = cl == "confirmed"
        ltf_ob     = cl == "confirmed"

        result_rows.append({
            "scan_job_id": job.id,
            "symbol":      symbol,
            "direction":   direction,
            "setup_type":  setup_type,
            "score":       score,
            "grade":       grade,
            "timeframe":   timeframe,
            "result_data": {
                "mode":           "mock",
                "classification": cl,
                "stale":          False,
                "sweep":          True,
                "displacement":   has_disp,
                "fvg":            has_fvg,
                "choch":          has_choch,
                "order_block":    has_ob,
                "retest":         has_retest,
                "ltf_sweep":      ltf_sweep,
                "ltf_choch":      ltf_choch,
                "ltf_ob":         ltf_ob,
                "setup_age":      random.randint(1, 25),
                "entry":          entry,
                "entry_source":   "ltf_ob_2" if ltf_ob else ("htf_ob_retest" if has_retest else "last_close"),
                "stop_loss":      stop_loss,
                "target_1":       target_1,
                "target_2":       target_2,
                "risk":           round(risk, 2),
                "reason":         random.choice(_REASONS),
                "htf_checklist": {
                    "liquidity_identified": True,
                    "sweep_confirmed":      True,
                    "displacement":         has_disp,
                    "fvg_formed":           has_fvg,
                    "choch_confirmed":      has_choch,
                    "ob_activated":         has_ob,
                    "ob_retest":            has_retest,
                },
                "ltf_checklist": {
                    "ltf_sweep":    ltf_sweep,
                    "ltf_choch":    ltf_choch,
                    "ltf_ob_formed": ltf_ob,
                    "entry_ready":  cl == "confirmed",
                },
                "sequence_valid": cl in ("confirmed", "watchlist"),
                "debug_trace": {
                    "mode":            "mock",
                    "symbol":          symbol,
                    "timeframe":       timeframe,
                    "candles_checked": random.randint(50, 200),
                    "score_breakdown": {
                        "htf_sweep_quality":    round(random.uniform(10, 20), 1),
                        "displacement_strength": round(random.uniform(0, 15), 1),
                        "fvg_quality":           round(random.uniform(0, 10), 1),
                        "choch_clarity":         round(random.uniform(0, 15), 1),
                        "ob_quality":            round(random.uniform(0, 10), 1),
                        "htf_retest":            round(random.uniform(0, 10), 1),
                        "ltf_confirmation":      round(random.uniform(0, 15), 1),
                        "rr_clarity":            round(random.uniform(0, 5),  1),
                    },
                },
            },
        })

    if result_rows:
        # ── Inject progression fields before persisting ────────────────────
        from app.services import progression as progression_svc
        from app.services import notification_service
        prev_map = scan_result_repository.get_latest_per_symbol(
            user_id=job.user_id,
            symbols=[row["symbol"] for row in result_rows],
        )
        for row in result_rows:
            prog = progression_svc.compute(
                curr_cl    = row.get("classification"),
                curr_wl    = row.get("watchlist_level"),
                curr_score = row.get("score"),
                prev_result = prev_map.get(row["symbol"]),
            )
            row.update(prog)
        saved = scan_result_repository.bulk_create(result_rows)
        # ── Create in-app notifications for high-value progressions ────────
        notif_count = notification_service.create_from_results(job, saved)
        if notif_count:
            logger.info("mock scan job %s: %d notification(s) created", job.id, notif_count)

    # ── Persist scan health for mock runs ─────────────────────────────────────
    health = compute_mock_scan_health(
        timeframe         = timeframe,
        symbols_requested = len(symbols),
        symbols_scanned   = len(fired_symbols),
    )
    scan_job_repository.save_scan_health(job, health)

    scan_job_repository.mark_completed(job, completed_symbols=len(symbols))


# ── Internal: live scanner ────────────────────────────────────────────────────

def _run_live_scan(
    job,
    symbols:       list[str],
    symbol_source: str,
    timeframe:     str,
    filters:       dict,
) -> None:
    """
    Live scan with HTF + LTF candles.

    Fetch flow (batch):
      1. Batch-fetch all HTF candles via get_candles_multi() — one yf.download() call
      2. Batch-fetch all LTF candles via get_candles_multi() — one yf.download() call
         (Redis cache is checked first; only cache-miss symbols hit the network)
      3. Per-symbol: run stop_hunter_engine.analyse_symbol(htf, ltf)
      4. Apply classification / min_score filters
      5. Write scan_result row
    """
    import time as _scan_time
    from app.providers.yfinance_provider import (
        get_candles_multi, reset_fetch_stats, get_fetch_stats,
    )
    from app.services import stop_hunter_engine

    scan_job_repository.mark_running(job, total_symbols=len(symbols))

    ltf_timeframe = _LTF_MAP.get(timeframe)      # may be None for 15m

    min_score              = None
    include_nm             = bool(filters.get("include_near_miss", True))
    classification_filter  = (filters.get("classification") or "").strip().lower() or None

    try:
        raw_min = filters.get("min_score")
        if raw_min is not None:
            min_score = float(raw_min)
    except (TypeError, ValueError):
        pass

    # ── Batch-fetch all candles upfront ───────────────────────────────────────
    reset_fetch_stats()
    fetch_t0 = _scan_time.monotonic()

    yf_syms = [f"{s}.NS" for s in symbols]

    logger.info(
        "live scan job %s: batch-fetching HTF (%s) for %d symbols",
        job.id, timeframe, len(yf_syms),
    )
    htf_batch = get_candles_multi(yf_syms, timeframe=timeframe, limit=200)

    ltf_batch: dict = {}
    if ltf_timeframe:
        logger.info(
            "live scan job %s: batch-fetching LTF (%s) for %d symbols",
            job.id, ltf_timeframe, len(yf_syms),
        )
        ltf_batch = get_candles_multi(yf_syms, timeframe=ltf_timeframe, limit=200)

    fetch_elapsed = _scan_time.monotonic() - fetch_t0
    fetch_stats   = get_fetch_stats()
    logger.info(
        "live scan job %s: fetch done %.1fs  hits=%d misses=%d errors=%d",
        job.id, fetch_elapsed,
        fetch_stats["cache_hits"], fetch_stats["cache_misses"], fetch_stats["fetch_errors"],
    )

    # ── Per-symbol engine loop ────────────────────────────────────────────────
    from app.services.scan_health_service import validate_candles, compute_scan_health

    result_rows:     list[dict] = []
    skipped:         list[dict] = []
    failed_symbols:  list[str]  = []   # symbols with insufficient/no HTF data
    candle_warnings: list[str]  = []   # collected from validate_candles()
    engine_t0 = _scan_time.monotonic()

    cl_counts = {"confirmed": 0, "watchlist": 0, "near_miss": 0, "no_result": 0}

    for symbol in symbols:
        yf_sym = f"{symbol}.NS"

        candles = htf_batch.get(yf_sym) or []
        if not candles or len(candles) < 30:
            skipped.append({
                "symbol": symbol,
                "reason": f"insufficient_htf_candles ({len(candles)})",
            })
            failed_symbols.append(symbol)
            cl_counts["no_result"] += 1
            continue

        # ── Candle validation (data integrity) ─────────────────────────────
        sym_warns = validate_candles(candles, symbol, timeframe)
        candle_warnings.extend(sym_warns)

        ltf_candles = ltf_batch.get(yf_sym) or None
        if ltf_candles and len(ltf_candles) < 20:
            ltf_candles = None

        # ── Run engine ──
        result = stop_hunter_engine.analyse_symbol(
            symbol, candles, timeframe, filters, ltf_candles,
        )

        if result is None:
            skipped.append({"symbol": symbol, "reason": "no_setup"})
            cl_counts["no_result"] += 1
            continue

        cl = result["classification"]

        # Near-miss filter
        if cl == "near_miss" and not include_nm:
            skipped.append({"symbol": symbol, "reason": "near_miss_excluded"})
            continue

        # Classification filter
        if classification_filter and cl != classification_filter:
            skipped.append({
                "symbol": symbol,
                "reason": f"classification '{cl}' excluded by filter '{classification_filter}'",
            })
            continue

        # Min score filter
        if min_score is not None and result["score"] < min_score:
            skipped.append({
                "symbol": symbol,
                "reason": f"score {result['score']:.1f} < min_score {min_score}",
            })
            continue

        cl_counts[cl] = cl_counts.get(cl, 0) + 1

        # ── Derive setup_type string ──
        direction = result["direction"]
        if cl == "confirmed":
            has_ltf = result.get("ltf_ob", False)
            setup_type = (
                "Stop Hunt + Full LTF Confirm"
                if has_ltf
                else "Stop Hunt + HTF Sequence Complete"
            )
        elif cl == "watchlist":
            has_ob = result.get("order_block", False)
            setup_type = (
                f"Watchlist — HTF OB Active ({direction.capitalize()})"
                if has_ob
                else f"Watchlist — ChoCH Confirmed ({direction.capitalize()})"
            )
        else:
            setup_type = "Near Miss — HTF Sweep Only"

        # ── Extract denormalised fields ────────────────────────────────────────
        db_ = result.get("debug_trace") or {}
        liq_src = db_.get("selected_liq_source") or db_.get("liq_source")

        # ── Build full result_data payload (canonical snapshot) ───────────────
        top_level_excl = {"score", "grade", "direction", "classification"}
        full_result_data = {k: v for k, v in result.items() if k not in top_level_excl}

        result_rows.append({
            # ── FK / identity ──────────────────────────────────────────────
            "scan_job_id":  job.id,
            "symbol":       symbol,
            "direction":    direction,
            "setup_type":   setup_type,
            "score":        result["score"],
            "grade":        result["grade"],
            "timeframe":    timeframe,
            # ── Denormalised queryable fields ──────────────────────────────
            "classification":        cl,
            "watchlist_level":       result.get("watchlist_level"),
            "watchlist_level_label": result.get("watchlist_level_label"),
            "current_stage_label":   result.get("current_stage_label"),
            "trade_plan_type":       result.get("trade_plan_type"),
            "liquidity_source":      liq_src,
            "entry":                 result.get("entry"),
            "stop_loss":             result.get("stop_loss"),
            "target_1":              result.get("target_1"),
            "target_2":              result.get("target_2"),
            "risk":                  result.get("risk"),
            "sequence_valid":        result.get("sequence_valid"),
            "entry_ready":           result.get("ltf_ob", False),
            # ── JSON payloads (explicit columns + full snapshot) ───────────
            "quality_flags": result.get("quality_flags"),
            "checklist": {
                "htf": result.get("htf_checklist"),
                "ltf": result.get("ltf_checklist"),
            },
            "debug_trace": result.get("debug_trace"),
            "result_data":  full_result_data,
        })

    scan_elapsed = _scan_time.monotonic() - engine_t0

    # ── Stamp skipped list + fetch metrics into debug_trace of each result ──
    for row in result_rows:
        dt = row.get("debug_trace")
        if isinstance(dt, dict):
            dt["skipped_symbols"] = skipped
            dt["symbol_source"]   = symbol_source
            dt["fetch_elapsed_s"] = round(fetch_elapsed, 2)
            dt["cache_hits"]      = fetch_stats["cache_hits"]
            dt["cache_misses"]    = fetch_stats["cache_misses"]
            dt["fetch_errors"]    = fetch_stats["fetch_errors"]

    if result_rows:
        # ── Inject progression fields before persisting ────────────────────
        from app.services import progression as progression_svc
        from app.services import notification_service
        prev_map = scan_result_repository.get_latest_per_symbol(
            user_id=job.user_id,
            symbols=[row["symbol"] for row in result_rows],
        )
        for row in result_rows:
            prog = progression_svc.compute(
                curr_cl    = row.get("classification"),
                curr_wl    = row.get("watchlist_level"),
                curr_score = row.get("score"),
                prev_result = prev_map.get(row["symbol"]),
            )
            row.update(prog)
        saved = scan_result_repository.bulk_create(result_rows)
        # ── Create in-app notifications for high-value progressions ────────
        notif_count = notification_service.create_from_results(job, saved)
        if notif_count:
            logger.info(
                "live scan job %s: %d notification(s) created", job.id, notif_count,
            )
        scan_job_repository.mark_completed(job, completed_symbols=len(symbols))
        scan_job_repository.update_run_stats(
            job,
            confirmed_count = cl_counts.get("confirmed", 0),
            watchlist_count = cl_counts.get("watchlist", 0),
            near_miss_count = cl_counts.get("near_miss", 0),
            no_result_count = cl_counts.get("no_result", 0),
            fetch_elapsed_s = fetch_elapsed,
            scan_elapsed_s  = scan_elapsed,
            cache_hits      = fetch_stats["cache_hits"],
            cache_misses    = fetch_stats["cache_misses"],
        )

        # ── Compute and persist scan health ────────────────────────────────
        symbols_scanned = len(symbols) - len(failed_symbols)
        health = compute_scan_health(
            timeframe         = timeframe,
            symbols_requested = len(symbols),
            symbols_scanned   = symbols_scanned,
            failed_symbols    = failed_symbols,
            fetch_stats       = fetch_stats,
            fetch_time_s      = fetch_elapsed,
            htf_batch         = htf_batch,
            ltf_batch         = ltf_batch if ltf_timeframe else None,
            candle_warnings   = candle_warnings,
        )
        scan_job_repository.save_scan_health(job, health)
        logger.info(
            "live scan job %s: health=%s requested=%d scanned=%d failed=%d cache_hit_rate=%.0f%%",
            job.id, health["data_quality"],
            health["symbols_requested"], health["symbols_scanned"],
            health["symbols_failed"], health["cache_hit_rate"] * 100,
        )

        logger.info(
            "live scan job %s: %d results, %d skipped  confirmed=%d wl=%d nm=%d",
            job.id, len(result_rows), len(skipped),
            cl_counts.get("confirmed", 0), cl_counts.get("watchlist", 0),
            cl_counts.get("near_miss", 0),
        )
    else:
        # Even on failure, persist a degraded health record
        health = compute_scan_health(
            timeframe         = timeframe,
            symbols_requested = len(symbols),
            symbols_scanned   = 0,
            failed_symbols    = list(symbols),
            fetch_stats       = fetch_stats,
            fetch_time_s      = fetch_elapsed,
            htf_batch         = htf_batch,
            ltf_batch         = ltf_batch if ltf_timeframe else None,
            candle_warnings   = candle_warnings,
            extra_warnings    = ["scan_failed: 0 symbols produced results"],
        )
        scan_job_repository.save_scan_health(job, health)
        scan_job_repository.mark_failed(job)
        logger.error(
            "live scan job %s: 0 results (all skipped/filtered). skipped=%d",
            job.id, len(skipped),
        )


# ── Shared utility ─────────────────────────────────────────────────────────────

def _score_to_grade(score: float, classification: str = "") -> str:
    """Map score + classification to letter grade."""
    if classification == "near_miss":
        return "NM"
    if score >= 90: return "A+"
    if score >= 80: return "A"
    if score >= 70: return "B+"
    if score >= 60: return "B"
    return "C"
