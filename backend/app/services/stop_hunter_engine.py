"""
Stop Hunter Pro — engine v3

Strict sequence enforcement:
  HTF: liquidity sweep → displacement → post-sweep FVG → ChoCH/MSS
       → OB 1.0 activation → OB retest
  LTF: sweep → ChoCH → OB 2.0 → entry confirmed

Classifications:
  confirmed  — full HTF + LTF sequence complete, score >= 70
  watchlist  — HTF sequence + OB active; waiting for retest or LTF confirmation
  near_miss  — sweep found; HTF sequence incomplete
  rejected   — no sweep / out-of-order / stale (filtered out, not stored)

Scoring (100 pts):
  HTF sweep quality           20
  Displacement strength       15
  Post-sweep FVG              10
  ChoCH/MSS clarity           15
  OB quality                  10
  HTF retest                  10
  LTF confirmation            15
  R:R / target clarity         5

Grades:
  A+ = 90+   A = 80-89   B+ = 70-79   B = 60-69   C = below 60
"""

import logging
from typing import Optional

logger = logging.getLogger(__name__)

# ── Constants ──────────────────────────────────────────────────────────────────

_SWEEP_LOOKBACK        = 80
_DEFAULT_SWING_LENGTH  = 5
_DEFAULT_MAX_SETUP_AGE = 50
_DEFAULT_MAX_LIQ_AGE   = 150
_ATR_PERIOD            = 14
_DEFAULT_MIN_DISP_ATR  = 0.5   # displacement body >= N * ATR
_DEFAULT_MIN_CHOCH_ATR = 0.25  # ChoCH close-break >= N * ATR
_EQUAL_LEVEL_TOL       = 0.0025
_EQUAL_LEVEL_PROX      = 0.01

# ── Phase 1 constants ──────────────────────────────────────────────────────────
_DEFAULT_MIN_BODY_PCT      = 0.60   # displacement body / (high-low) >= this
_DEFAULT_MIN_CLOSE_PCT     = 0.70   # displacement close position in range
_DEFAULT_MIN_FVG_ATR       = 0.15   # FVG gap must be >= this * ATR
_DEFAULT_INTERNAL_PIVOT    = 3      # LTF ChoCH pivot length (internal structure)
_EQH_EQL_TOLERANCE         = 0.002  # 0.2% tolerance for equal-high/low grouping
_EQH_EQL_MIN_TOUCHES       = 2      # minimum swing touches to qualify as EQH/EQL
_SESSION_INTRADAY_TF       = {"15m", "1h", "4h"}  # timeframes with prev-day/week levels

# Liquidity source strength weights (used in ranking)
_LIQ_STRENGTH = {
    "swing":          1.0,
    "eqh":            2.5,
    "eql":            2.5,
    "prev_day_high":  2.0,
    "prev_day_low":   2.0,
    "prev_week_high": 3.0,
    "prev_week_low":  3.0,
}


# ── Public entry point ─────────────────────────────────────────────────────────

def analyse_symbol(
    symbol:      str,
    candles:     list[dict],
    timeframe:   str,
    filters:     dict,
    ltf_candles: Optional[list[dict]] = None,
) -> Optional[dict]:
    """
    Run Stop Hunter Pro analysis on a single symbol.

    Args:
        symbol:      NSE symbol (e.g. "RELIANCE")
        candles:     HTF OHLCV dicts sorted oldest→newest
        timeframe:   "15m" | "1h" | "4h" | "1d" | "1w"
        filters:     dict from scan request
        ltf_candles: optional lower-timeframe OHLCV for LTF confirmation

    Returns result dict or None.
    """
    # ── 1. Sort & validate ────────────────────────────────────────────────────
    candles = sorted(candles, key=lambda c: c["timestamp"])
    sort_applied = True

    if len(candles) < 30:
        logger.debug("%s: not enough candles (%d)", symbol, len(candles))
        return None

    # ── 2. Parse filters ──────────────────────────────────────────────────────
    swing_length      = int(filters.get("swing_length",          _DEFAULT_SWING_LENGTH))
    max_setup_age     = int(filters.get("max_setup_age",         _DEFAULT_MAX_SETUP_AGE))
    max_liq_age       = int(filters.get("max_liquidity_age",     _DEFAULT_MAX_LIQ_AGE))
    min_disp_atr      = float(filters.get("min_displacement_atr",_DEFAULT_MIN_DISP_ATR))
    min_choch_atr     = float(filters.get("min_choch_atr",       _DEFAULT_MIN_CHOCH_ATR))
    require_fvg       = bool(filters.get("require_fvg",          True))
    require_retest    = bool(filters.get("require_retest",        False))
    require_ltf       = bool(filters.get("require_ltf",          False))
    include_near_miss = bool(filters.get("include_near_miss",     True))
    max_choch_bars    = int(filters.get("max_choch_bars",         25))
    debug_mode        = bool(filters.get("debug_mode",            False))

    # ── Phase 1 filter params ─────────────────────────────────────────────────
    min_body_pct       = float(filters.get("min_body_pct",       _DEFAULT_MIN_BODY_PCT))
    min_close_pct      = float(filters.get("min_close_pct",      _DEFAULT_MIN_CLOSE_PCT))
    min_fvg_atr        = float(filters.get("min_fvg_atr",        _DEFAULT_MIN_FVG_ATR))
    internal_pivot_len = int(filters.get("internal_pivot_length", _DEFAULT_INTERNAL_PIVOT))
    # Present mode: only newest setup per symbol. Historical: allow stale.
    scan_mode          = str(filters.get("scan_mode", "present"))   # "present" | "historical"
    use_eqh_eql        = bool(filters.get("use_eqh_eql",          True))
    use_session_levels = bool(filters.get("use_session_levels",    True))

    # ── Phase 2 candidate mode ────────────────────────────────────────────────
    # "fast"       — break on first confirmed/watchlist (original behaviour)
    # "best_setup" — evaluate up to N candidates, return highest-quality result
    candidate_mode      = str(filters.get("candidate_mode",       "fast"))
    max_sweep_cands     = int(filters.get("max_sweep_candidates",  5))

    n = len(candles)

    # ── 3. ATR ────────────────────────────────────────────────────────────────
    atr = _compute_atr(candles, _ATR_PERIOD)
    if atr <= 0:
        return None

    # ── 4. Swing highs / lows ─────────────────────────────────────────────────
    sh_idxs = _find_swing_highs(candles, swing_length)
    sl_idxs = _find_swing_lows(candles,  swing_length)

    if not sh_idxs and not sl_idxs:
        return None

    # ── 5a. Build extra liquidity levels (EQH/EQL + session) ─────────────────
    extra_levels: list[dict] = []
    if use_eqh_eql:
        extra_levels += _find_eqh_eql_levels(candles, sh_idxs, sl_idxs)
    if use_session_levels and timeframe in _SESSION_INTRADAY_TF:
        extra_levels += _find_prev_session_levels(candles, timeframe)

    # ── 5b. Find all sweeps in lookback window ────────────────────────────────
    all_sweeps = _find_all_sweeps(
        candles, sh_idxs, sl_idxs,
        lookback=_SWEEP_LOOKBACK, max_liq_age=max_liq_age,
        extra_levels=extra_levels,
    )
    if not all_sweeps:
        return None

    # ── 6. Rank sweeps (freshness + quality + liq_strength) ───────────────────
    all_sweeps = _rank_sweeps(all_sweeps, candles, atr)

    # ── 7. Try sweep candidates → select best result ──────────────────────────
    # Priority order for selection: confirmed > watchlist > near_miss
    #
    # fast mode:
    #   Iterate sweeps in rank order; break at first confirmed/watchlist found.
    #   Collect best near_miss seen so far as fallback.
    #   O(first_actionable_rank) — original behaviour.
    #
    # best_setup mode:
    #   Phase A — evaluate top N candidates by sweep geometry (deep comparison).
    #   Phase B — if no confirmed/watchlist in phase A, continue iterating until
    #             the first one is found (guarantees no regression vs fast mode).
    #   Then select by: classification priority > score > sequence quality > age.
    #   O(max(N, first_actionable_rank)) — never regresses below fast mode.

    _CL_RANK = {"confirmed": 0, "watchlist": 1, "near_miss": 2}

    def _run_sweep(rank_i, sweep_info):
        """Build one setup; return (rank_i, result) or None."""
        sa    = (n - 1) - sweep_info["sweep_idx"]
        stale = (scan_mode != "historical") and (sa > max_setup_age)
        r = _build_setup(
            symbol, candles, n, sweep_info,
            sh_idxs, sl_idxs, atr, timeframe, filters,
            max_choch_bars, require_fvg, require_retest, require_ltf,
            min_disp_atr, min_choch_atr,
            min_body_pct, min_close_pct, min_fvg_atr, internal_pivot_len,
            ltf_candles, sort_applied, debug_mode, stale, sa,
        )
        return (rank_i, r) if r is not None else None

    candidate_results = []   # list of (rank_i, result_dict)
    candidates_tested = 0

    def _has_actionable():
        return any(_CL_RANK.get(r["classification"], 99) <= 1
                   for _, r in candidate_results)

    if candidate_mode == "best_setup":
        # Phase A: evaluate top N by sweep geometry
        for rank_i, sw in enumerate(all_sweeps[:max_sweep_cands]):
            out = _run_sweep(rank_i, sw)
            candidates_tested += 1
            if out is not None:
                candidate_results.append(out)

        # Phase B: if still no actionable, extend until first confirmed/watchlist
        if not _has_actionable():
            for rank_i, sw in enumerate(all_sweeps[max_sweep_cands:],
                                        start=max_sweep_cands):
                out = _run_sweep(rank_i, sw)
                candidates_tested += 1
                if out is not None:
                    candidate_results.append(out)
                    if out[1]["classification"] in ("confirmed", "watchlist"):
                        break   # found one — stop extending
    else:
        # fast mode: iterate until first confirmed/watchlist
        for rank_i, sw in enumerate(all_sweeps):
            out = _run_sweep(rank_i, sw)
            candidates_tested += 1
            if out is not None:
                candidate_results.append(out)
                if out[1]["classification"] in ("confirmed", "watchlist"):
                    break

    if not candidate_results:
        return None

    # ── Select best candidate ──────────────────────────────────────────────────
    def _candidate_key(item):
        _, r = item
        cl_p  = _CL_RANK.get(r["classification"], 99)
        score = r.get("score", 0.0)
        age   = r.get("setup_age", 9999)
        seq   = 0 if r.get("sequence_valid") else 1
        entry = 0 if r.get("ltf_ob") else 1
        # lower is better: class priority → sequence → entry → desc score → age
        return (cl_p, seq, entry, -score, age)

    candidate_results.sort(key=_candidate_key)
    selected_rank, result = candidate_results[0]

    if result["classification"] == "near_miss" and not include_near_miss:
        return None

    # ── Attach candidate debug info to result ──────────────────────────────────
    # Sort summary by classification priority then score (best first)
    summary_sorted = sorted(candidate_results, key=_candidate_key)
    candidate_summary = []
    for crank, cr in summary_sorted[:5]:
        sw = cr.get("sweep_detail", {})
        candidate_summary.append({
            "rank":             crank + 1,
            "liq_source":       sw.get("liq_source",   "swing"),
            "liq_strength":     sw.get("liq_strength",  1.0),
            "direction":        cr.get("direction"),
            "sweep_idx":        sw.get("sweep_idx"),
            "classification":   cr.get("classification"),
            "score":            cr.get("score"),
            "stage_label":      cr.get("current_stage_label"),
            "rejection_reason": cr.get("rejection_reason"),
        })

    dt = result.get("debug_trace", {})
    dt["candidate_mode"]          = candidate_mode
    dt["candidates_tested"]       = candidates_tested
    dt["selected_candidate_rank"] = selected_rank + 1   # 1-based
    dt["selected_liq_source"]     = result.get("sweep_detail", {}).get("liq_source", "swing")
    dt["selected_liq_strength"]   = result.get("sweep_detail", {}).get("liq_strength", 1.0)
    dt["candidate_summary"]       = candidate_summary

    return result


# ── Internal: full setup builder for one sweep ────────────────────────────────

def _build_setup(
    symbol, candles, n, sweep_info,
    sh_idxs, sl_idxs, atr, timeframe, filters,
    max_choch_bars, require_fvg, require_retest, require_ltf,
    min_disp_atr, min_choch_atr,
    min_body_pct, min_close_pct, min_fvg_atr, internal_pivot_len,
    ltf_candles, sort_applied, debug_mode, stale, setup_age,
):
    """
    Attempt to build a full HTF+LTF setup from a single sweep event.
    Returns result dict (classification may be near_miss) or None.
    """
    direction = sweep_info["direction"]
    sweep_idx = sweep_info["sweep_idx"]

    # ── Step 1: Displacement candle after sweep ────────────────────────────────
    # Phase 1: adds body_pct and close_pct quality filters
    disp_info = _detect_displacement(
        candles, sweep_idx, direction, atr, min_disp_atr,
        min_body_pct=min_body_pct, min_close_pct=min_close_pct,
    )

    # ── Step 2: Post-sweep FVG (must start AFTER sweep) ───────────────────────
    # Phase 1: adds ATR-size quality gate; FVG must be inside displacement/ChoCH leg
    fvg_start = sweep_idx + 2
    fvg_end   = min(n, sweep_idx + 40)
    fvg_info  = _find_fvg(candles, fvg_start, fvg_end, direction,
                          min_atr_mult=min_fvg_atr, atr=atr)

    # ── Step 3: HTF ChoCH / MSS — swing structure only ────────────────────────
    # Phase 1: HTF ChoCH requires confirmed swing reference (no close-based fallback)
    choch_info = _find_choch(
        candles, sweep_info, sh_idxs, sl_idxs,
        max_bars=max_choch_bars,
        min_break_atr=min_choch_atr, atr=atr,
        require_swing_ref=True,          # HTF must use swing structure
    )
    choch_idx = choch_info.get("choch_idx")

    # ── Step 4: HTF OB 1.0 (last opposing candle before displacement) ─────────
    ob_info = _find_htf_ob(
        candles, sweep_idx, disp_info.get("displacement_idx"), direction,
    )

    # ── Step 5: HTF OB retest (only after ChoCH + OB active) ─────────────────
    retest_scan_start = (choch_idx + 1) if choch_idx is not None else None
    retest_info = {"retested": False, "retest_idx": None, "zone_type": None}
    if choch_info.get("confirmed") and ob_info.get("found") and retest_scan_start is not None:
        retest_info = _check_htf_retest(candles, ob_info, retest_scan_start, direction)

    # ── Step 6: LTF confirmation (only if HTF retest done) ────────────────────
    ltf_result = {"ltf_available": False, "ltf_sweep": False,
                  "ltf_choch": False, "ltf_ob": False,
                  "ltf_sweep_detail": {}, "ltf_choch_detail": {}, "ltf_ob_detail": {}}
    if retest_info.get("retested") and ltf_candles:
        ltf_result = _analyse_ltf(ltf_candles, direction, ob_info, atr,
                                  internal_pivot_len=internal_pivot_len)

    # ── Step 7: Equal levels bonus ────────────────────────────────────────────
    eq_levels = _check_equal_levels(
        candles, sh_idxs, sl_idxs, sweep_info["liq_level"],
    )

    # ── Step 8: Score ─────────────────────────────────────────────────────────
    score, score_breakdown = _calculate_score(
        sweep_info, disp_info, fvg_info, choch_info,
        ob_info, retest_info, ltf_result, eq_levels,
    )

    # ── Step 9: Classify ──────────────────────────────────────────────────────
    classification, rejection_reason = _classify_setup(
        sweep_info, disp_info, fvg_info, choch_info, ob_info,
        retest_info, ltf_result,
        require_fvg, require_retest, require_ltf, score, stale,
    )

    if classification == "rejected":
        return None  # skip this sweep entirely

    # Stale setups: demote confirmed/watchlist → near_miss
    if stale and classification in ("confirmed", "watchlist"):
        classification = "near_miss"
        rejection_reason = "stale_setup"

    # ── Step 10: Grade ────────────────────────────────────────────────────────
    grade = _grade_from_score(score, classification)

    # ── Step 11: Trade levels ─────────────────────────────────────────────────
    levels = _calculate_levels(
        candles, sweep_info, ob_info, ltf_result, retest_info, direction,
    )

    # ── Step 12: Assemble result ──────────────────────────────────────────────
    return _assemble_result(
        symbol, timeframe, direction, classification, grade, score,
        sweep_info, disp_info, fvg_info, choch_info, ob_info, retest_info,
        ltf_result, eq_levels, levels, score_breakdown,
        setup_age, stale, rejection_reason, sort_applied, atr, n,
        choch_idx, retest_scan_start,
        sh_idxs, sl_idxs,
    )


# ── ATR ────────────────────────────────────────────────────────────────────────

def _compute_atr(candles: list[dict], period: int = 14) -> float:
    """Simple ATR (SMA of True Range over last `period` bars)."""
    if len(candles) < period + 1:
        return 0.0
    trs = []
    for i in range(1, len(candles)):
        h  = candles[i]["high"]
        lo = candles[i]["low"]
        pc = candles[i - 1]["close"]
        trs.append(max(h - lo, abs(h - pc), abs(lo - pc)))
    recent = trs[-period:]
    return sum(recent) / len(recent) if recent else 0.0


# ── Swing detection ────────────────────────────────────────────────────────────

def _find_swing_highs(candles: list[dict], length: int) -> list[int]:
    """Confirmed swing highs. Last `length` bars cannot be pivots."""
    n, idxs = len(candles), []
    for i in range(length, n - length):
        h = candles[i]["high"]
        if (all(candles[j]["high"] < h for j in range(i - length, i)) and
                all(candles[j]["high"] < h for j in range(i + 1, i + length + 1))):
            idxs.append(i)
    return idxs


def _find_swing_lows(candles: list[dict], length: int) -> list[int]:
    """Confirmed swing lows. Last `length` bars cannot be pivots."""
    n, idxs = len(candles), []
    for i in range(length, n - length):
        lo = candles[i]["low"]
        if (all(candles[j]["low"] > lo for j in range(i - length, i)) and
                all(candles[j]["low"] > lo for j in range(i + 1, i + length + 1))):
            idxs.append(i)
    return idxs


# ── Phase 1: EQH / EQL liquidity levels ──────────────────────────────────────

def _find_eqh_eql_levels(
    candles: list[dict],
    sh_idxs: list[int],
    sl_idxs: list[int],
    tolerance: float = _EQH_EQL_TOLERANCE,
    min_touches: int = _EQH_EQL_MIN_TOUCHES,
) -> list[dict]:
    """
    Detect equal-high and equal-low liquidity clusters.

    Groups confirmed swing pivots that are within `tolerance` (0.2%) of each
    other.  A group with >= min_touches members forms a strong EQH or EQL level
    — institutional liquidity sitting above/below multiple equal pivots.

    Returns a list of extra liquidity-level dicts compatible with _find_all_sweeps.
    """
    levels: list[dict] = []

    def _cluster(idxs: list[int], price_key: str, liq_type: str, src: str) -> list[dict]:
        visited = set()
        result  = []
        prices  = [(i, candles[i][price_key]) for i in idxs]
        for a_idx, (ia, pa) in enumerate(prices):
            if ia in visited:
                continue
            group = [(ia, pa)]
            for ib, pb in prices[a_idx + 1:]:
                if ib not in visited and pa > 0 and abs(pa - pb) / pa <= tolerance:
                    group.append((ib, pb))
            if len(group) >= min_touches:
                for gi, gp in group:
                    visited.add(gi)
                # Level = the most-recent member of the cluster
                latest_idx   = max(i for i, _ in group)
                avg_price    = sum(p for _, p in group) / len(group)
                result.append({
                    "liq_source":  src,
                    "liq_type":    liq_type,
                    "liq_level":   round(avg_price, 4),
                    "liq_idx":     latest_idx,
                    "liq_strength": _LIQ_STRENGTH[src],
                    "touches":     len(group),
                })
        return result

    levels += _cluster(sh_idxs, "high", "buy_side",  "eqh")
    levels += _cluster(sl_idxs, "low",  "sell_side", "eql")
    return levels


def _find_prev_session_levels(
    candles: list[dict],
    timeframe: str,
) -> list[dict]:
    """
    Extract previous-day and previous-week high/low levels from intraday candles.

    These are strong institutional reference levels (NY/London session boxes,
    weekly range).  Only meaningful for intraday timeframes (15m, 1h, 4h).

    Returns a list of extra liquidity-level dicts.
    """
    from datetime import datetime, timezone

    levels: list[dict] = []
    if not candles:
        return levels

    # Parse timestamps to dates/weeks
    def _parse_ts(ts: str):
        try:
            # Handle both naive and tz-aware ISO strings
            ts_clean = ts.replace("Z", "+00:00")
            dt = datetime.fromisoformat(ts_clean)
            return dt.date(), dt.isocalendar()[1]   # (date, week_number)
        except Exception:
            return None, None

    # Build daily and weekly OHLC from candle data
    day_data:  dict[object, dict] = {}
    week_data: dict[object, dict] = {}

    for i, c in enumerate(candles):
        day, week = _parse_ts(c["timestamp"])
        if day is None:
            continue
        for key, data in [(day, day_data), (week, week_data)]:
            if key not in data:
                data[key] = {"high": c["high"], "low": c["low"], "last_idx": i}
            else:
                if c["high"] > data[key]["high"]:
                    data[key]["high"] = c["high"]
                if c["low"]  < data[key]["low"]:
                    data[key]["low"]  = c["low"]
                data[key]["last_idx"] = i

    sorted_days  = sorted(day_data.keys())
    sorted_weeks = sorted(week_data.keys())
    n = len(candles)

    # Previous day
    if len(sorted_days) >= 2:
        prev_day = sorted_days[-2]
        pd_data  = day_data[prev_day]
        levels.append({
            "liq_source": "prev_day_high", "liq_type": "buy_side",
            "liq_level":  round(pd_data["high"], 4),
            "liq_idx":    pd_data["last_idx"],
            "liq_strength": _LIQ_STRENGTH["prev_day_high"],
        })
        levels.append({
            "liq_source": "prev_day_low", "liq_type": "sell_side",
            "liq_level":  round(pd_data["low"], 4),
            "liq_idx":    pd_data["last_idx"],
            "liq_strength": _LIQ_STRENGTH["prev_day_low"],
        })

    # Previous week
    if len(sorted_weeks) >= 2:
        prev_week = sorted_weeks[-2]
        pw_data   = week_data[prev_week]
        levels.append({
            "liq_source": "prev_week_high", "liq_type": "buy_side",
            "liq_level":  round(pw_data["high"], 4),
            "liq_idx":    pw_data["last_idx"],
            "liq_strength": _LIQ_STRENGTH["prev_week_high"],
        })
        levels.append({
            "liq_source": "prev_week_low", "liq_type": "sell_side",
            "liq_level":  round(pw_data["low"], 4),
            "liq_idx":    pw_data["last_idx"],
            "liq_strength": _LIQ_STRENGTH["prev_week_low"],
        })

    return levels


# ── Equal levels (bonus scoring only, kept for backward compat) ────────────────

def _check_equal_levels(
    candles, sh_idxs, sl_idxs,
    liq_level,
    proximity_pct=_EQUAL_LEVEL_PROX,
    tolerance_pct=_EQUAL_LEVEL_TOL,
) -> dict:
    """Check equal-high / equal-low clusters near the swept level."""
    def _has_equal(idxs, key):
        if len(idxs) < 2:
            return False
        nearby = [
            i for i in idxs
            if liq_level > 0 and abs(candles[i][key] - liq_level) / liq_level <= proximity_pct
        ]
        if len(nearby) < 2:
            return False
        levels = [candles[i][key] for i in nearby]
        for a in range(len(levels)):
            for b in range(a + 1, len(levels)):
                if levels[a] > 0 and abs(levels[a] - levels[b]) / levels[a] <= tolerance_pct:
                    return True
        return False

    return {
        "equal_highs": _has_equal(sh_idxs, "high"),
        "equal_lows":  _has_equal(sl_idxs, "low"),
    }


# ── Sweep detection (all sweeps) ───────────────────────────────────────────────

def _find_all_sweeps(
    candles, sh_idxs, sl_idxs,
    lookback=_SWEEP_LOOKBACK, max_liq_age=_DEFAULT_MAX_LIQ_AGE,
    extra_levels: Optional[list] = None,
) -> list[dict]:
    """
    Find ALL liquidity sweeps in the last `lookback` bars.

    Phase 1 extension: also checks extra_levels (EQH/EQL, prev-day/week) in
    addition to ordinary swing highs/lows.  Each bar produces at most one sweep.
    Priority per bar: bearish (buy-side) > bullish (sell-side), and
    extra_levels are checked AFTER swing levels for the same bar.

    Each sweep carries liq_source and liq_strength for ranking.
    """
    n     = len(candles)
    start = max(1, n - lookback)
    sweeps: list[dict] = []
    extra = extra_levels or []

    # Sort swing lists descending (most recent first) for fast lookup
    sh_recent = sorted(sh_idxs, reverse=True)
    sl_recent = sorted(sl_idxs, reverse=True)

    # Build fast lookup for extra levels by type
    extra_buy  = sorted([e for e in extra if e["liq_type"] == "buy_side"],
                        key=lambda e: e["liq_idx"], reverse=True)
    extra_sell = sorted([e for e in extra if e["liq_type"] == "sell_side"],
                        key=lambda e: e["liq_idx"], reverse=True)

    def _make_sweep(bar_idx, c, liq_idx, liq_level, liq_type, direction,
                    liq_source="swing", liq_strength=1.0) -> dict:
        if direction == "bearish":
            swept_wick = c["high"] - liq_level
            close_back = liq_level - c["close"]
            extreme    = c["high"]
        else:
            swept_wick = liq_level - c["low"]
            close_back = c["close"] - liq_level
            extreme    = c["low"]
        return {
            "direction":       direction,
            "sweep_idx":       bar_idx,
            "liq_idx":         liq_idx,
            "liq_level":       liq_level,
            "liq_type":        liq_type,
            "liq_source":      liq_source,
            "liq_strength":    liq_strength,
            "sweep_extreme":   extreme,
            "close":           c["close"],
            "swept_wick":      round(swept_wick, 4),
            "close_back_size": round(close_back, 4),
            "wick_size":       round(swept_wick, 4),   # legacy
        }

    for bar_idx in range(n - 1, start - 1, -1):
        c = candles[bar_idx]
        found = False

        # ── 1. Swing-high bearish sweep ────────────────────────────────────────
        for sh_i in sh_recent:
            if sh_i >= bar_idx:
                continue
            if bar_idx - sh_i > max_liq_age:
                break
            sh_level = candles[sh_i]["high"]
            if c["high"] > sh_level and c["close"] <= sh_level:
                sweeps.append(_make_sweep(bar_idx, c, sh_i, sh_level, "buy_side", "bearish"))
                found = True
                break

        if found:
            continue

        # ── 2. Extra-level bearish sweep (EQH / prev-day/week high) ───────────
        for el in extra_buy:
            if el["liq_idx"] >= bar_idx:
                continue
            if bar_idx - el["liq_idx"] > max_liq_age:
                break
            lvl = el["liq_level"]
            if c["high"] > lvl and c["close"] <= lvl:
                sweeps.append(_make_sweep(bar_idx, c, el["liq_idx"], lvl, "buy_side", "bearish",
                                          liq_source=el["liq_source"],
                                          liq_strength=el["liq_strength"]))
                found = True
                break

        if found:
            continue

        # ── 3. Swing-low bullish sweep ─────────────────────────────────────────
        for sl_i in sl_recent:
            if sl_i >= bar_idx:
                continue
            if bar_idx - sl_i > max_liq_age:
                break
            sl_level = candles[sl_i]["low"]
            if c["low"] < sl_level and c["close"] >= sl_level:
                sweeps.append(_make_sweep(bar_idx, c, sl_i, sl_level, "sell_side", "bullish"))
                found = True
                break

        if found:
            continue

        # ── 4. Extra-level bullish sweep (EQL / prev-day/week low) ────────────
        for el in extra_sell:
            if el["liq_idx"] >= bar_idx:
                continue
            if bar_idx - el["liq_idx"] > max_liq_age:
                break
            lvl = el["liq_level"]
            if c["low"] < lvl and c["close"] >= lvl:
                sweeps.append(_make_sweep(bar_idx, c, el["liq_idx"], lvl, "sell_side", "bullish",
                                          liq_source=el["liq_source"],
                                          liq_strength=el["liq_strength"]))
                break

    return sweeps


def _rank_sweeps(sweeps: list[dict], candles: list[dict], atr: float) -> list[dict]:
    """
    Rank sweeps: fresh + strong close-back + high liq_strength preferred.

    Score = -(age * 0.08)          freshness penalty
          + cb_ratio * 3.0         close-back quality
          + min(wick_atr, 3) * 0.8 wick significance
          + liq_strength * 0.3     EQH/EQL/session levels tiebreaker (not override)
    """
    n = len(candles)

    def _score(s):
        age          = (n - 1) - s["sweep_idx"]
        wick         = s.get("swept_wick",      0) or 0
        cb           = s.get("close_back_size", 0) or 0
        total        = wick + cb
        cb_ratio     = (cb / total) if total > 0 else 0.5
        wick_atr     = (wick / atr) if atr > 0 else 0
        liq_strength = s.get("liq_strength", 1.0)
        return (-(age * 0.08)
                + cb_ratio * 3.0
                + min(wick_atr, 3.0) * 0.8
                + liq_strength * 0.3)

    return sorted(sweeps, key=_score, reverse=True)


# ── Displacement ───────────────────────────────────────────────────────────────

def _detect_displacement(
    candles, sweep_idx, direction, atr, min_atr_mult,
    search_bars=20,
    min_body_pct: float = _DEFAULT_MIN_BODY_PCT,
    min_close_pct: float = _DEFAULT_MIN_CLOSE_PCT,
) -> dict:
    """
    Find the FIRST strong candle in the expected direction after the sweep.

    Phase 1 quality filters (in addition to existing ATR body gate):
    - body_pct  : body / (high - low) >= min_body_pct (default 60%)
                  Filters out doji/spinning-top candles whose body is small
                  relative to total range — not true displacement.
    - close_pct : close position in range must be >= min_close_pct (default 70%)
                  Bullish displacement: close in top 30% of candle range.
                  Bearish displacement: close in bottom 30% of candle range.
    """
    base = {"found": False, "displacement_idx": None, "body_size": None,
            "atr_ratio": None, "body_pct": None, "direction": None}
    n     = len(candles)
    limit = min(n, sweep_idx + search_bars + 1)

    for i in range(sweep_idx + 1, limit):
        c      = candles[i]
        body   = abs(c["close"] - c["open"])
        rng    = c["high"] - c["low"]

        # ATR gate (existing)
        if body < min_atr_mult * atr:
            continue

        # Body-percentage gate (Phase 1)
        body_pct = (body / rng) if rng > 0 else 0.0
        if body_pct < min_body_pct:
            continue

        if direction == "bullish" and c["close"] > c["open"]:
            # Close must be in top (1 - min_close_pct) of the range
            close_pos = (c["close"] - c["low"]) / rng if rng > 0 else 1.0
            if close_pos < min_close_pct:
                continue
            return {
                "found":            True,
                "displacement_idx": i,
                "body_size":        round(body, 4),
                "atr_ratio":        round(body / atr, 2),
                "body_pct":         round(body_pct, 3),
                "direction":        "bullish",
            }
        if direction == "bearish" and c["close"] < c["open"]:
            # Close must be in bottom (1 - min_close_pct) of the range
            close_pos = (c["high"] - c["close"]) / rng if rng > 0 else 1.0
            if close_pos < min_close_pct:
                continue
            return {
                "found":            True,
                "displacement_idx": i,
                "body_size":        round(body, 4),
                "atr_ratio":        round(body / atr, 2),
                "body_pct":         round(body_pct, 3),
                "direction":        "bearish",
            }

    return base


# ── Fair Value Gap ─────────────────────────────────────────────────────────────

def _find_fvg(
    candles, start, end, direction,
    min_atr_mult: float = _DEFAULT_MIN_FVG_ATR,
    atr: float = 0.0,
) -> dict:
    """
    Search for Fair Value Gaps in [start, end).
    All three FVG candles must be AFTER the sweep (caller ensures start >= sweep+2).
    Returns the LARGEST qualifying gap found in the window.

    Bearish FVG: candles[i].high < candles[i-2].low  (gap below)
    Bullish FVG: candles[i].low  > candles[i-2].high (gap above)

    Phase 1: gap must be >= min_atr_mult * ATR (default 0.15 ATR).
    Tiny noise gaps are ignored.
    """
    base = {"found": False, "fvg_idx": None,
            "zone_high": None, "zone_low": None,
            "gap_size": None, "gap_pct": None}

    end       = min(end, len(candles))
    start     = max(start, 2)
    min_gap   = min_atr_mult * atr if atr > 0 else 0.0
    best_gap  = 0.0
    best_fvg  = None

    for i in range(start, end):
        if direction == "bearish":
            gap_high = candles[i - 2]["low"]
            gap_low  = candles[i]["high"]
            if gap_low < gap_high:
                gap = gap_high - gap_low
                if gap >= min_gap and gap > best_gap:
                    best_gap = gap
                    mid = (gap_high + gap_low) / 2
                    best_fvg = {
                        "found":     True,
                        "fvg_idx":   i,
                        "zone_high": round(gap_high, 4),
                        "zone_low":  round(gap_low,  4),
                        "gap_size":  round(gap, 4),
                        "gap_pct":   round(gap / mid * 100, 3) if mid else 0,
                    }
        else:  # bullish
            gap_low  = candles[i - 2]["high"]
            gap_high = candles[i]["low"]
            if gap_high > gap_low:
                gap = gap_high - gap_low
                if gap >= min_gap and gap > best_gap:
                    best_gap = gap
                    mid = (gap_high + gap_low) / 2
                    best_fvg = {
                        "found":     True,
                        "fvg_idx":   i,
                        "zone_high": round(gap_high, 4),
                        "zone_low":  round(gap_low,  4),
                        "gap_size":  round(gap, 4),
                        "gap_pct":   round(gap / mid * 100, 3) if mid else 0,
                    }

    return best_fvg if best_fvg else base


# ── ChoCH / MSS ────────────────────────────────────────────────────────────────

def _find_choch(
    candles, sweep_info, sh_idxs, sl_idxs,
    max_bars, min_break_atr, atr,
    require_swing_ref: bool = False,
) -> dict:
    """
    Find Change of Character after a sweep.

    Bullish ChoCH: first close ABOVE a meaningful prior swing HIGH (formed before sweep).
    Bearish ChoCH: first close BELOW a meaningful prior swing LOW (formed before sweep).

    Phase 1 — require_swing_ref (default False):
    - True  (HTF): reference MUST be a confirmed swing pivot. If none found,
                   ChoCH is not confirmed. No close-based fallback.
    - False (LTF): also accepts internal structure (close-based min/max fallback).
    """
    direction = sweep_info["direction"]
    sweep_idx = sweep_info["sweep_idx"]
    n         = len(candles)
    min_break = min_break_atr * atr

    base = {
        "confirmed":        False,
        "choch_idx":        None,
        "choch_level":      None,
        "bars_after_sweep": None,
        "reference_type":   None,
        "break_amount":     None,
    }

    if sweep_idx == 0:
        return base

    window_start = max(0, sweep_idx - max_bars)
    ref_level    = None
    ref_type     = None

    if direction == "bearish":
        candidates = [i for i in sl_idxs if window_start <= i < sweep_idx]
        if candidates:
            ref_idx   = candidates[-1]
            ref_level = candles[ref_idx]["low"]
            ref_type  = "swing_low"
        elif not require_swing_ref:
            # LTF internal structure fallback
            window    = candles[window_start:sweep_idx]
            ref_level = min(c["close"] for c in window) if window else None
            ref_type  = "min_close_fallback"

        if ref_level is None:
            return {**base, "reference_type": ref_type}

        for i in range(sweep_idx + 1, min(n, sweep_idx + max_bars + 1)):
            brk = ref_level - candles[i]["close"]
            if candles[i]["close"] < ref_level and brk >= min_break:
                return {
                    "confirmed":        True,
                    "choch_idx":        i,
                    "choch_level":      round(ref_level, 4),
                    "bars_after_sweep": i - sweep_idx,
                    "reference_type":   ref_type,
                    "break_amount":     round(brk, 4),
                }

    else:  # bullish
        candidates = [i for i in sh_idxs if window_start <= i < sweep_idx]
        if candidates:
            ref_idx   = candidates[-1]
            ref_level = candles[ref_idx]["high"]
            ref_type  = "swing_high"
        elif not require_swing_ref:
            # LTF internal structure fallback
            window    = candles[window_start:sweep_idx]
            ref_level = max(c["close"] for c in window) if window else None
            ref_type  = "max_close_fallback"

        if ref_level is None:
            return {**base, "reference_type": ref_type}

        for i in range(sweep_idx + 1, min(n, sweep_idx + max_bars + 1)):
            brk = candles[i]["close"] - ref_level
            if candles[i]["close"] > ref_level and brk >= min_break:
                return {
                    "confirmed":        True,
                    "choch_idx":        i,
                    "choch_level":      round(ref_level, 4),
                    "bars_after_sweep": i - sweep_idx,
                    "reference_type":   ref_type,
                    "break_amount":     round(brk, 4),
                }

    return {**base, "reference_type": ref_type}


# ── HTF Order Block 1.0 ────────────────────────────────────────────────────────

def _find_htf_ob(candles, sweep_idx, displacement_idx, direction) -> dict:
    """
    HTF OB 1.0 = last opposing candle BEFORE the displacement impulse.

    Search window: [max(0, sweep_idx - 2), displacement_idx) exclusive.
    Scan backward from displacement_idx - 1 to sweep_idx - 2.

    Bullish OB: last BEARISH candle in the window (becomes support).
    Bearish OB: last BULLISH candle in the window (becomes resistance).

    If displacement_idx is None (no displacement found), use sweep_idx + 5 as fallback.
    """
    base = {"found": False, "ob_idx": None, "zone_high": None,
            "zone_low": None, "ob_type": None}

    impulse_start  = sweep_idx - 2
    search_end_idx = displacement_idx if displacement_idx is not None else (sweep_idx + 5)
    search_end_idx = min(search_end_idx, len(candles) - 1)
    search_start   = max(0, impulse_start)

    for i in range(search_end_idx - 1, search_start - 1, -1):
        c      = candles[i]
        is_bull = c["close"] > c["open"]
        is_bear = c["close"] < c["open"]

        if direction == "bullish" and is_bear:
            return {
                "found":     True,
                "ob_idx":    i,
                "zone_high": round(c["high"], 4),
                "zone_low":  round(c["low"],  4),
                "ob_type":   "bearish_ob",
            }
        if direction == "bearish" and is_bull:
            return {
                "found":     True,
                "ob_idx":    i,
                "zone_high": round(c["high"], 4),
                "zone_low":  round(c["low"],  4),
                "ob_type":   "bullish_ob",
            }

    return base


# ── HTF OB Retest ─────────────────────────────────────────────────────────────

def _check_htf_retest(candles, ob_info, retest_scan_start, direction) -> dict:
    """
    After ChoCH + OB activation, check if price re-enters the HTF OB zone.

    Bullish retest: candle low <= zone_high  AND  close >= zone_low
    Bearish retest: candle high >= zone_low  AND  close <= zone_high
    """
    base = {"retested": False, "retest_idx": None, "zone_type": None}
    if not ob_info.get("found") or retest_scan_start is None:
        return base

    zone_high = ob_info["zone_high"]
    zone_low  = ob_info["zone_low"]
    n         = len(candles)

    for i in range(retest_scan_start, n):
        c = candles[i]
        if direction == "bullish":
            if c["low"] <= zone_high and c["close"] >= zone_low:
                return {"retested": True, "retest_idx": i, "zone_type": "htf_ob"}
        else:
            if c["high"] >= zone_low and c["close"] <= zone_high:
                return {"retested": True, "retest_idx": i, "zone_type": "htf_ob"}

    return base


# ── LTF Confirmation ──────────────────────────────────────────────────────────

def _analyse_ltf(
    ltf_candles, direction, htf_ob_info, htf_atr,
    internal_pivot_len: int = _DEFAULT_INTERNAL_PIVOT,
) -> dict:
    """
    Run LTF confirmation sequence after HTF retest.

    Sequence: LTF sweep (same direction) → LTF ChoCH → LTF OB 2.0 → entry ready.

    Phase 1: LTF ChoCH uses require_swing_ref=False (internal structure allowed).
    internal_pivot_len controls the swing pivot length for LTF (default 3).
    """
    empty = {
        "ltf_available":    False,
        "ltf_sweep":        False, "ltf_sweep_detail":  {},
        "ltf_choch":        False, "ltf_choch_detail":  {},
        "ltf_ob":           False, "ltf_ob_detail":     {},
    }

    if not ltf_candles or len(ltf_candles) < 20:
        return empty

    ltf_candles = sorted(ltf_candles, key=lambda c: c["timestamp"])
    ltf_atr     = _compute_atr(ltf_candles, _ATR_PERIOD)
    if ltf_atr <= 0:
        return {**empty, "ltf_available": True}

    ltf_sh = _find_swing_highs(ltf_candles, internal_pivot_len)
    ltf_sl = _find_swing_lows(ltf_candles,  internal_pivot_len)

    # ── LTF sweep: same direction as HTF, last 40 LTF bars ──
    all_ltf_sweeps = _find_all_sweeps(
        ltf_candles, ltf_sh, ltf_sl, lookback=40, max_liq_age=60,
    )
    same_dir = [s for s in all_ltf_sweeps if s["direction"] == direction]

    if not same_dir:
        return {"ltf_available": True,
                "ltf_sweep": False, "ltf_sweep_detail": {},
                "ltf_choch": False, "ltf_choch_detail": {},
                "ltf_ob":    False, "ltf_ob_detail":    {}}

    ltf_sweep_info = _rank_sweeps(same_dir, ltf_candles, ltf_atr)[0]

    # ── LTF ChoCH — internal structure allowed (require_swing_ref=False) ──
    ltf_choch = _find_choch(
        ltf_candles, ltf_sweep_info, ltf_sh, ltf_sl,
        max_bars=15, min_break_atr=0.2, atr=ltf_atr,
        require_swing_ref=False,
    )

    # ── LTF displacement ──
    ltf_disp_idx = None
    if ltf_choch.get("confirmed"):
        ltf_disp = _detect_displacement(
            ltf_candles, ltf_sweep_info["sweep_idx"],
            direction, ltf_atr, 0.3,
        )
        ltf_disp_idx = ltf_disp.get("displacement_idx")

    # ── LTF OB 2.0 ──
    ltf_ob_base = {"found": False, "ob_idx": None,
                   "zone_high": None, "zone_low": None, "ob_type": None}
    ltf_ob = ltf_ob_base
    if ltf_choch.get("confirmed"):
        ltf_ob = _find_htf_ob(
            ltf_candles, ltf_sweep_info["sweep_idx"], ltf_disp_idx, direction,
        )

    return {
        "ltf_available":   True,
        "ltf_sweep":       True,
        "ltf_sweep_detail": ltf_sweep_info,
        "ltf_choch":       ltf_choch.get("confirmed", False),
        "ltf_choch_detail": ltf_choch,
        "ltf_ob":          ltf_ob.get("found", False),
        "ltf_ob_detail":   ltf_ob,
    }


# ── Scoring ────────────────────────────────────────────────────────────────────

def _calculate_score(
    sweep_info, disp_info, fvg_info, choch_info,
    ob_info, retest_info, ltf_result, eq_levels,
) -> tuple[float, dict]:
    """
    Score 0-100.

    HTF sweep quality      20
    Displacement strength  15
    Post-sweep FVG         10
    ChoCH/MSS clarity      15
    OB quality             10
    HTF retest             10
    LTF confirmation       15
    R:R / target clarity    5
    """
    bd = {
        "htf_sweep_quality":    0.0,
        "displacement_strength": 0.0,
        "fvg_quality":           0.0,
        "choch_clarity":         0.0,
        "ob_quality":            0.0,
        "htf_retest":            0.0,
        "ltf_confirmation":      0.0,
        "rr_clarity":            0.0,
    }

    direction = sweep_info.get("direction", "")

    # 1. HTF sweep quality (max 20)
    liq_score    = 8.0  # base
    liq_strength = sweep_info.get("liq_strength", 1.0)
    liq_source   = sweep_info.get("liq_source",   "swing")
    # Source bonus: EQH/EQL and session levels score higher than plain swings
    if liq_source in ("eqh", "eql"):
        liq_score += 4.0
    elif liq_source in ("prev_week_high", "prev_week_low"):
        liq_score += 3.5
    elif liq_source in ("prev_day_high", "prev_day_low"):
        liq_score += 2.5
    else:
        liq_score += 1.0  # plain swing
    # Equal-level cluster bonus (backward compat with existing eq_levels check)
    if eq_levels.get("equal_highs") and direction == "bearish":
        liq_score = min(liq_score + 1.5, 16.0)
    elif eq_levels.get("equal_lows") and direction == "bullish":
        liq_score = min(liq_score + 1.5, 16.0)
    # Close-back quality
    wick = sweep_info.get("swept_wick",      0) or 0
    cb   = sweep_info.get("close_back_size", 0) or 0
    tot  = wick + cb
    if tot > 0:
        liq_score += (cb / tot) * 4.0   # up to +4 for tight close-back
    bd["htf_sweep_quality"] = min(round(liq_score, 2), 20.0)

    # 2. Displacement strength (max 15)
    if disp_info.get("found"):
        atr_ratio = disp_info.get("atr_ratio", 0) or 0
        d_score   = 8.0 + min(atr_ratio, 3.5) * 2.0  # 8 base + up to 7
        bd["displacement_strength"] = min(round(d_score, 2), 15.0)

    # 3. Post-sweep FVG (max 10)
    if fvg_info.get("found"):
        gap_pct = fvg_info.get("gap_pct", 0) or 0
        bd["fvg_quality"] = min(round(7.0 + gap_pct * 0.6, 2), 10.0)

    # 4. ChoCH/MSS clarity (max 15)
    if choch_info.get("confirmed"):
        bars = choch_info.get("bars_after_sweep", 99) or 99
        if   bars <= 2:  c = 15.0
        elif bars <= 5:  c = 13.0
        elif bars <= 10: c = 10.0
        else:            c = 7.0
        if choch_info.get("reference_type") in ("swing_low", "swing_high"):
            c = min(c + 2.0, 15.0)
        bd["choch_clarity"] = c

    # 5. OB quality (max 10)
    if ob_info.get("found"):
        bd["ob_quality"] = 10.0

    # 6. HTF retest (max 10)
    if retest_info.get("retested"):
        bd["htf_retest"] = 10.0

    # 7. LTF confirmation (max 15)
    if ltf_result.get("ltf_available"):
        ltf_s = 0.0
        if ltf_result.get("ltf_sweep"): ltf_s += 4.0
        if ltf_result.get("ltf_choch"): ltf_s += 6.0
        if ltf_result.get("ltf_ob"):    ltf_s += 5.0
        bd["ltf_confirmation"] = ltf_s

    # 8. R:R clarity (max 5) — 2R target always valid if OB/levels available
    if ob_info.get("found") or ltf_result.get("ltf_ob"):
        bd["rr_clarity"] = 5.0
    elif choch_info.get("confirmed"):
        bd["rr_clarity"] = 2.0

    total = round(min(sum(bd.values()), 100.0), 2)
    return total, bd


# ── Classification ─────────────────────────────────────────────────────────────

def _classify_setup(
    sweep_info, disp_info, fvg_info, choch_info, ob_info,
    retest_info, ltf_result,
    require_fvg, require_retest, require_ltf,
    score, stale,
) -> tuple[str, Optional[str]]:
    """
    Returns (classification, rejection_reason).

    confirmed  — full sequence: HTF + LTF complete, score >= 70
    watchlist  — HTF: sweep+disp+ChoCH+OB, missing retest or LTF, score >= 45
    near_miss  — sweep done but key HTF steps incomplete, score >= 20
    rejected   — no displacement (if hard requirement) or score < 20
    """
    has_disp   = disp_info.get("found",    False)
    has_fvg    = fvg_info.get("found",     False)
    has_choch  = choch_info.get("confirmed", False)
    has_ob     = ob_info.get("found",      False)
    has_retest = retest_info.get("retested", False)
    has_ltf_all = (ltf_result.get("ltf_sweep") and
                   ltf_result.get("ltf_choch") and
                   ltf_result.get("ltf_ob"))

    # Hard reject: score too low
    if score < 10:
        return "rejected", "score_too_low"

    # FVG requirement gate
    fvg_ok    = has_fvg    if require_fvg    else True
    retest_ok = has_retest if require_retest else True
    ltf_ok    = has_ltf_all if require_ltf  else True

    # ── Confirmed ──────────────────────────────────────────────────────────────
    # Full HTF sequence + LTF OB 2.0 formed + score >= 70
    if (has_disp and fvg_ok and has_choch and has_ob and
            has_retest and has_ltf_all and score >= 70):
        return "confirmed", None

    # ── Watchlist ──────────────────────────────────────────────────────────────
    # HTF OB active, waiting for retest / LTF
    if has_disp and has_choch and has_ob and score >= 45:
        return "watchlist", None

    # Partial watchlist: ChoCH confirmed but no OB yet
    if has_choch and score >= 40:
        return "watchlist", "no_ob_yet"

    # ── Near miss ──────────────────────────────────────────────────────────────
    # Sweep found + some partial HTF structure
    if score >= 20:
        return "near_miss", "incomplete_htf_sequence"

    return "rejected", "too_weak"


# ── Grade ─────────────────────────────────────────────────────────────────────

def _grade_from_score(score: float, classification: str) -> str:
    if classification == "near_miss":
        return "NM"
    if score >= 90: return "A+"
    if score >= 80: return "A"
    if score >= 70: return "B+"
    if score >= 60: return "B"
    return "C"


# ── Trade Levels ──────────────────────────────────────────────────────────────

def _calculate_levels(
    candles, sweep_info, ob_info, ltf_result, retest_info, direction,
) -> dict:
    """
    Entry priority: LTF OB 2.0 > HTF OB 1.0 (after retest) > last close.
    SL: below/above sweep extreme with 0.2% buffer.
    T1 = 2R,  T2 = 3.5R.
    """
    last_close    = candles[-1]["close"]
    sweep_extreme = sweep_info["sweep_extreme"]

    ltf_ob = ltf_result.get("ltf_ob_detail", {}) if ltf_result else {}

    # ── Entry ──
    if ltf_result and ltf_result.get("ltf_ob") and ltf_ob.get("found"):
        entry        = ltf_ob["zone_low"] if direction == "bullish" else ltf_ob["zone_high"]
        entry_source = "ltf_ob_2"
    elif ob_info.get("found") and retest_info.get("retested"):
        entry        = ob_info["zone_low"] if direction == "bullish" else ob_info["zone_high"]
        entry_source = "htf_ob_retest"
    elif ob_info.get("found"):
        entry        = ob_info["zone_low"] if direction == "bullish" else ob_info["zone_high"]
        entry_source = "htf_ob_pending"
    else:
        entry        = last_close
        entry_source = "last_close"

    entry = round(float(entry), 4)

    # ── Stop loss ──
    if direction == "bullish":
        stop_loss = round(sweep_extreme * 0.998, 4)   # 0.2% below sweep low
        risk      = entry - stop_loss
    else:
        stop_loss = round(sweep_extreme * 1.002, 4)   # 0.2% above sweep high
        risk      = stop_loss - entry

    if risk <= 0:
        risk = abs(entry * 0.005)   # fallback: 0.5% of price

    # ── Targets: T1 = 2R, T2 = 3.5R ──
    if direction == "bullish":
        t1 = round(entry + risk * 2.0, 4)
        t2 = round(entry + risk * 3.5, 4)
    else:
        t1 = round(entry - risk * 2.0, 4)
        t2 = round(entry - risk * 3.5, 4)

    return {
        "entry":        entry,
        "entry_source": entry_source,
        "stop_loss":    round(stop_loss, 4),
        "target_1":     t1,
        "target_2":     t2,
        "risk":         round(risk, 4),
    }


# ── Stage label ───────────────────────────────────────────────────────────────

def _derive_stage_label(
    classification, disp_info, choch_info, ob_info,
    retest_info, ltf_result,
) -> str:
    """
    Return a human-readable current-stage string.

    Strict sequential gating:  each stage requires all prior stages.
    near_miss is handled separately so a fallback OB (found without
    displacement/ChoCH) does not report a misleading "OB 1.0 Active" label.
    """
    has_disp   = disp_info.get("found",      False)
    has_choch  = choch_info.get("confirmed", False)
    has_ob     = ob_info.get("found",        False)
    has_retest = retest_info.get("retested", False)
    has_ltf_sw = ltf_result.get("ltf_sweep", False)
    has_ltf_ch = ltf_result.get("ltf_choch", False)
    has_ltf_ob = ltf_result.get("ltf_ob",    False)

    # ── near_miss: describe what is actually present (no OB/retest stages) ──
    if classification == "near_miss":
        if has_disp and has_choch:
            return "Disp + ChoCH — OB Pending"
        if has_disp:
            return "Displacement — ChoCH Pending"
        return "Sweep Only — Incomplete Structure"

    # ── watchlist / confirmed: sequential gates ────────────────────────────
    # LTF stages require retest; retest requires OB+ChoCH.
    if classification == "confirmed" and has_ltf_ob:
        return "LTF OB 2.0 — Entry Ready"
    if has_ltf_ch and has_retest:
        return "LTF ChoCH — OB 2.0 Pending"
    if has_ltf_sw and has_retest:
        return "LTF Sweep — ChoCH Pending"
    if has_retest and has_ob and has_choch:
        return "HTF OB Retested — Awaiting LTF"
    # OB active: show even when displacement body% filter failed (LT case) —
    # the engine already classified this as watchlist, so label must agree.
    if has_ob and has_choch:
        return "OB 1.0 Active — Awaiting Retest"
    if has_ob:
        return "OB 1.0 Active — Awaiting Retest"
    if has_choch and has_disp:
        return "ChoCH Confirmed — No OB Yet"
    if has_choch:
        return "ChoCH Confirmed — Awaiting OB"
    if has_disp:
        return "Displacement — ChoCH Pending"
    return "Monitoring"


# ── Watchlist level ───────────────────────────────────────────────────────────

_WL_LABELS = {
    "L1": "L1 — Awaiting HTF Retest",
    "L2": "L2 — Awaiting LTF Sweep",
    "L3": "L3 — Awaiting LTF ChoCH",
    "L4": "L4 — Awaiting LTF OB 2.0",
}

def _derive_watchlist_level(
    classification: str,
    ob_info:      dict,
    retest_info:  dict,
    ltf_result:   dict,
) -> tuple[str | None, str | None]:
    """
    Return (watchlist_level, watchlist_level_label) for watchlist setups only.

    Levels are mutually exclusive and ordered: L1 < L2 < L3 < L4.
    Only the lowest unfulfilled milestone is returned.

    L1 — HTF OB active,  HTF retest NOT done
    L2 — HTF retest done, LTF sweep NOT done
    L3 — LTF sweep done,  LTF ChoCH NOT done
    L4 — LTF ChoCH done,  LTF OB 2.0 NOT done
    """
    if classification != "watchlist":
        return None, None

    has_ob     = ob_info.get("found",       False)
    has_retest = retest_info.get("retested", False)
    has_ltf_sw = ltf_result.get("ltf_sweep", False)
    has_ltf_ch = ltf_result.get("ltf_choch", False)
    has_ltf_ob = ltf_result.get("ltf_ob",    False)

    if has_ltf_ob:
        # Full LTF sequence present but score < 70 kept this as watchlist.
        # All milestones done — classify as L4 with a "score below threshold" note.
        return "L4", "L4 — LTF OB 2.0 Formed (Score Below Threshold)"
    elif has_ltf_ch:
        lvl = "L4"
    elif has_ltf_sw:
        lvl = "L3"
    elif has_retest:
        lvl = "L2"
    elif has_ob:
        lvl = "L1"
    else:
        # OB not yet confirmed (rare edge: ChoCH passed, OB search failed)
        lvl = "L1"

    return lvl, _WL_LABELS[lvl]


# ── Quality flags ─────────────────────────────────────────────────────────────

# Severity order for sorting / display priority (lower index = shown first)
_FLAG_SEVERITY_ORDER = {"severe": 0, "warn": 1, "positive": 2, "info": 3}


def _derive_quality_flags(
    classification: str,
    score:          float,
    stale:          bool,
    sweep_info:     dict,
    disp_info:      dict,
    fvg_info:       dict,
    ob_info:        dict,
    retest_info:    dict,
    ltf_result:     dict,
    atr:            float,
) -> list[dict]:
    """
    Return a compact list of quality flag dicts for transparency.
    Does NOT change classification, score, or trade plan type.

    Each flag: {"id": str, "label": str, "severity": str, "detail": str}
    Severities: "severe" | "warn" | "info" | "positive"
    """
    flags = []

    def add(fid, label, severity, detail):
        flags.append({"id": fid, "label": label, "severity": severity, "detail": detail})

    liq_source = sweep_info.get("liq_source", "swing")
    wick       = sweep_info.get("swept_wick",      0) or 0
    cb         = sweep_info.get("close_back_size", 0) or 0
    gap_pct    = fvg_info.get("gap_pct",           0) or 0
    ltf_ob     = ltf_result.get("ltf_ob",          False)
    ltf_sw     = ltf_result.get("ltf_sweep",       False)

    # ── Severe ────────────────────────────────────────────────────────────────
    if stale:
        add("stale_setup", "Stale Setup", "severe",
            f"Setup age exceeds max_setup_age — demoted to near_miss.")

    # ── Warning ───────────────────────────────────────────────────────────────
    if not disp_info.get("found"):
        add("no_displacement", "No Displacement", "warn",
            "Displacement candle did not meet ATR-size or body% threshold after sweep.")

    if wick > 0 and cb < wick * 0.3:
        ratio = cb / wick if wick > 0 else 0
        add("weak_close_back", "Weak Close-Back", "warn",
            f"Close-back ({cb:.2f}) is {ratio*100:.0f}% of swept wick ({wick:.2f}). "
            f"Conviction threshold is 30%.")

    if not ob_info.get("found"):
        add("missing_ob", "Missing OB", "warn",
            "No order block found in the pre-displacement zone.")

    if fvg_info.get("found") and 0 < gap_pct < 0.15:
        add("small_fvg", "Small FVG", "warn",
            f"FVG gap {gap_pct:.3f}% is small — above minimum but may be noise.")

    if classification == "watchlist" and ltf_ob:
        # Two distinct reasons a watchlist can have the full LTF sequence:
        # (a) score < 70  — all gates met, quality score the only blocker
        # (b) score >= 70 but HTF gate failed (e.g. no displacement / no retest)
        has_disp_   = disp_info.get("found", False)
        has_retest_ = retest_info.get("retested", False)
        if score < 70:
            add("score_below_confirmed_threshold", "Score Below Threshold", "warn",
                f"Full LTF sequence present but score {score:.1f} < 70 (confirmed threshold).")
        else:
            # Identify which HTF gate is the specific blocker
            if not has_disp_:
                blocker = "no displacement"
            elif not has_retest_:
                blocker = "HTF retest not yet done"
            else:
                blocker = "HTF sequence gate"
            add("htf_sequence_gap", "HTF Sequence Gap", "warn",
                f"LTF sequence complete and score {score:.1f} meets threshold, "
                f"but confirmed gate blocked: {blocker}.")

    # ── Informational ─────────────────────────────────────────────────────────
    _SESSION_SRCS = {"prev_day_high", "prev_day_low", "prev_week_high", "prev_week_low"}
    if liq_source in _SESSION_SRCS:
        src_label = liq_source.replace("_", " ").replace("prev ", "Prev ").title()
        add("session_level_sweep", f"Session Level ({src_label})", "info",
            f"Liquidity swept at a {src_label} — institutional reference level.")

    if liq_source in {"eqh", "eql"}:
        kind = "Equal Highs" if liq_source == "eqh" else "Equal Lows"
        add("eqh_eql_sweep", f"{kind} Sweep", "info",
            f"Liquidity swept at a cluster of {kind.lower()} — multi-touch level.")

    if classification == "watchlist" and not ltf_sw:
        add("ltf_pending", "LTF Pending", "info",
            "LTF sweep not yet detected — awaiting lower-timeframe confirmation start.")

    # ── Positive ──────────────────────────────────────────────────────────────
    if classification == "confirmed" and score >= 80:
        add("excellent_sequence", "Excellent Sequence", "positive",
            f"Full HTF + LTF sequence confirmed with score {score:.1f}. "
            f"All structural gates passed.")

    # Sort: severe → warn → positive → info
    flags.sort(key=lambda f: _FLAG_SEVERITY_ORDER.get(f["severity"], 99))
    return flags


# ── Trade plan metadata ───────────────────────────────────────────────────────

def _derive_trade_plan(
    classification: str,
    direction:      str,
    ob_info:        dict,
    retest_info:    dict,
    ltf_result:     dict,
    wl_level:       str | None,
    wl_label:       str | None,
    rejection_reason: str | None,
) -> dict:
    """
    Return trade_plan_* fields that give the drawer clear per-classification
    wording so users cannot confuse watchlist prep zones with confirmed entries.

    trade_plan_type:    "entry" | "preparation" | "no_trade"
    trade_plan_title:   section header string
    trade_plan_warning: prominent caution text (None for confirmed)
    invalidation_text:  what would cancel the setup
    """
    liq_side = "below the sweep low" if direction == "bullish" else "above the sweep high"

    if classification == "confirmed":
        return {
            "trade_plan_type":    "entry",
            "trade_plan_title":   "Entry Signal — Full Sequence Complete",
            "trade_plan_warning": None,
            "invalidation_text":  (
                f"Setup invalidated if price closes {liq_side} "
                "or LTF OB 2.0 zone is broken without reaction."
            ),
        }

    if classification == "watchlist":
        next_step = wl_label or (f"Watchlist {wl_level}" if wl_level else "Next milestone pending")
        ob_zone   = ""
        if ob_info.get("found"):
            zl = ob_info.get("zone_low");  zh = ob_info.get("zone_high")
            if zl and zh:
                ob_zone = f" OB zone: {zl:.2f}–{zh:.2f}."
        return {
            "trade_plan_type":    "preparation",
            "trade_plan_title":   "Preparation Zone — Not An Entry Signal",
            "trade_plan_warning": (
                f"Not an entry signal yet.  Waiting for: {next_step}.{ob_zone}"
            ),
            "invalidation_text":  (
                f"Setup invalidated if price closes {liq_side} "
                "or HTF OB zone is breached before retest completes."
            ),
        }

    # near_miss / rejected / anything else → no_trade
    rr_note = f"  Reason: {rejection_reason}." if rejection_reason else ""
    return {
        "trade_plan_type":    "no_trade",
        "trade_plan_title":   "No Trade — Confirmation Incomplete",
        "trade_plan_warning": (
            f"Missing structural confirmation.{rr_note}  "
            "Levels shown are diagnostic reference only — do not trade."
        ),
        "invalidation_text":  (
            "No active trade plan.  Monitor for sequence completion."
        ),
    }


# ── Reason string ─────────────────────────────────────────────────────────────

def _build_reason(
    sweep_info, disp_info, choch_info, fvg_info, ob_info,
    retest_info, ltf_result, score, stale,
) -> str:
    direction = sweep_info["direction"]
    liq_type  = sweep_info.get("liq_type", "").replace("_", " ")
    liq_level = sweep_info.get("liq_level", 0)

    parts = [
        f"{direction.capitalize()} stop hunt — {liq_type} liquidity swept at {liq_level:.2f}."
    ]
    if disp_info.get("found"):
        parts.append(f"Displacement {disp_info['atr_ratio']:.1f}× ATR at bar {disp_info['displacement_idx']}.")
    if choch_info.get("confirmed"):
        ref  = choch_info.get("reference_type", "")
        bars = choch_info.get("bars_after_sweep", 0)
        ref_str = " (swing ref)" if "swing" in ref else " (close ref)"
        parts.append(f"ChoCH confirmed in {bars}b{ref_str}.")
    else:
        parts.append("ChoCH pending.")
    if fvg_info.get("found"):
        parts.append(
            f"FVG {fvg_info['zone_low']:.2f}–{fvg_info['zone_high']:.2f} "
            f"({fvg_info.get('gap_pct', 0):.2f}% gap, post-sweep)."
        )
    if ob_info.get("found"):
        parts.append(
            f"HTF OB 1.0 {ob_info['zone_low']:.2f}–{ob_info['zone_high']:.2f}."
        )
    if retest_info.get("retested"):
        parts.append("HTF OB retest confirmed.")
    if ltf_result and ltf_result.get("ltf_sweep"):
        parts.append("LTF sweep confirmed.")
    if ltf_result and ltf_result.get("ltf_choch"):
        parts.append("LTF ChoCH confirmed.")
    if ltf_result and ltf_result.get("ltf_ob"):
        parts.append("LTF OB 2.0 formed — entry ready.")
    if stale:
        parts.append("⚠ Setup is stale.")
    parts.append(f"Score: {score:.0f}/100.")
    return " ".join(parts)


# ── Result assembler ──────────────────────────────────────────────────────────

def _assemble_result(
    symbol, timeframe, direction, classification, grade, score,
    sweep_info, disp_info, fvg_info, choch_info, ob_info, retest_info,
    ltf_result, eq_levels, levels, score_breakdown,
    setup_age, stale, rejection_reason, sort_applied, atr, n,
    choch_idx, retest_scan_start,
    sh_idxs, sl_idxs,
):
    reason = _build_reason(
        sweep_info, disp_info, choch_info, fvg_info, ob_info,
        retest_info, ltf_result, score, stale,
    )

    result = {
        # ── Top-level DB columns ──────────────────────────────────────────────
        "score":          round(score, 2),
        "grade":          grade,
        "classification": classification,
        "direction":      direction,

        # ── HTF confirmations ─────────────────────────────────────────────────
        "mode":        "live",
        "stale":       stale,
        "sweep":       True,
        "displacement": disp_info.get("found",        False),
        "fvg":          fvg_info.get("found",          False),
        "choch":        choch_info.get("confirmed",    False),
        "order_block":  ob_info.get("found",           False),
        "retest":       retest_info.get("retested",    False),

        # ── LTF confirmations ─────────────────────────────────────────────────
        "ltf_sweep": ltf_result.get("ltf_sweep", False),
        "ltf_choch": ltf_result.get("ltf_choch", False),
        "ltf_ob":    ltf_result.get("ltf_ob",    False),

        # ── Liquidity ─────────────────────────────────────────────────────────
        "liquidity_level": sweep_info["liq_level"],
        "liquidity_type":  sweep_info["liq_type"],

        # ── Trade levels ──────────────────────────────────────────────────────
        "entry":        levels["entry"],
        "entry_source": levels["entry_source"],
        "stop_loss":    levels["stop_loss"],
        "target_1":     levels["target_1"],
        "target_2":     levels["target_2"],
        "risk":         levels["risk"],

        # ── Setup meta ────────────────────────────────────────────────────────
        "reason":          reason,
        "setup_age":       setup_age,
        "candles_checked": n,
        "rejection_reason": rejection_reason,
        "sequence_valid":  classification in ("confirmed", "watchlist"),

        # ── Compatibility aliases (do NOT remove originals above) ─────────────
        # These let future features / alerts / saved-scan consumers use
        # standard names without breaking existing frontend field references.
        "setup_status":        classification,
        "status_reason":       rejection_reason or reason,
        "current_stage_label": _derive_stage_label(
            classification, disp_info, choch_info,
            ob_info, retest_info, ltf_result,
        ),

        # ── Watchlist level (L1–L4, null for non-watchlist) ───────────────────
        **dict(zip(
            ("watchlist_level", "watchlist_level_label"),
            _derive_watchlist_level(classification, ob_info, retest_info, ltf_result),
        )),

        # ── Trade plan metadata (drives drawer D · Trade Plan wording) ─────────
        **_derive_trade_plan(
            classification, direction,
            ob_info, retest_info, ltf_result,
            *_derive_watchlist_level(classification, ob_info, retest_info, ltf_result),
            rejection_reason,
        ),

        # ── Quality flags (transparency layer — does not change scoring) ───────
        "quality_flags": _derive_quality_flags(
            classification, score, stale,
            sweep_info, disp_info, fvg_info, ob_info, retest_info, ltf_result,
            atr,
        ),

        # ── Detail objects for drawer ─────────────────────────────────────────
        "sweep_detail":        sweep_info,
        "displacement_detail": disp_info,
        "choch_detail":        choch_info,
        "fvg_detail":          fvg_info,
        "ob_detail":           ob_info,
        "retest_detail":       retest_info,
        "ltf_detail":          ltf_result,
        "equal_levels":        eq_levels,

        # ── Checklists (structured for frontend drawer) ───────────────────────
        "htf_checklist": {
            "liquidity_identified": True,
            "sweep_confirmed":      True,
            "displacement":         disp_info.get("found",      False),
            "fvg_formed":           fvg_info.get("found",       False),
            "choch_confirmed":      choch_info.get("confirmed", False),
            "ob_activated":         ob_info.get("found",        False),
            "ob_retest":            retest_info.get("retested", False),
        },
        "ltf_checklist": {
            "ltf_sweep":    ltf_result.get("ltf_sweep", False),
            "ltf_choch":    ltf_result.get("ltf_choch", False),
            "ltf_ob_formed": ltf_result.get("ltf_ob",  False),
            "entry_ready":  classification == "confirmed",
        },

        # ── Unified checklist alias: checklist.htf / checklist.ltf ───────────
        # Mirrors htf_checklist + ltf_checklist under one key for API consumers.
        # htf_checklist and ltf_checklist are kept as-is for backward compat.
        "checklist": {
            "htf": {
                "liquidity_identified": True,
                "sweep_confirmed":      True,
                "displacement":         disp_info.get("found",      False),
                "fvg_formed":           fvg_info.get("found",       False),
                "choch_confirmed":      choch_info.get("confirmed", False),
                "ob_activated":         ob_info.get("found",        False),
                "ob_retest":            retest_info.get("retested", False),
            },
            "ltf": {
                "ltf_sweep":    ltf_result.get("ltf_sweep", False),
                "ltf_choch":    ltf_result.get("ltf_choch", False),
                "ltf_ob_formed": ltf_result.get("ltf_ob",  False),
                "entry_ready":  classification == "confirmed",
            },
        },

        # ── Debug trace ───────────────────────────────────────────────────────
        "debug_trace": {
            "mode":                "live",
            "symbol":              symbol,
            "timeframe":           timeframe,
            "candles_fetched":     n,
            "candle_sort_applied": sort_applied,
            "atr":                 round(atr, 4),
            "swing_highs_found":   len(sh_idxs),
            "swing_lows_found":    len(sl_idxs),
            # Phase 1 additions
            "liq_source":          sweep_info.get("liq_source",   "swing"),
            "liq_strength":        sweep_info.get("liq_strength",  1.0),
            "disp_body_pct":       disp_info.get("body_pct"),
            "sweeps_found":        None,   # filled post-hoc if needed
            # Sequence indices
            "sweep_idx":          sweep_info["sweep_idx"],
            "displacement_idx":   disp_info.get("displacement_idx"),
            "fvg_search_start":   sweep_info["sweep_idx"] + 2,
            "fvg_idx":            fvg_info.get("fvg_idx"),
            "choch_idx":          choch_idx,
            "ob_idx":             ob_info.get("ob_idx"),
            "retest_idx":         retest_info.get("retest_idx"),
            "retest_scan_start":  retest_scan_start,
            "ltf_sweep_idx":      ltf_result.get("ltf_sweep_detail", {}).get("sweep_idx"),
            "ltf_choch_idx":      ltf_result.get("ltf_choch_detail", {}).get("choch_idx"),
            "ltf_ob_idx":         ltf_result.get("ltf_ob_detail",    {}).get("ob_idx"),
            # Quality indicators
            "setup_age":           setup_age,
            "max_setup_age":       _DEFAULT_MAX_SETUP_AGE,
            "liquidity_age":       sweep_info["sweep_idx"] - sweep_info["liq_idx"],
            "max_liquidity_age":   _DEFAULT_MAX_LIQ_AGE,
            "displacement_atr_ratio": disp_info.get("atr_ratio"),
            "choch_reference_type":   choch_info.get("reference_type"),
            "choch_bars_after_sweep": choch_info.get("bars_after_sweep"),
            # Score
            "score_breakdown":   score_breakdown,
            "rejection_reason":  rejection_reason,
            "sequence_valid":    classification in ("confirmed", "watchlist"),
        },
    }

    return result
