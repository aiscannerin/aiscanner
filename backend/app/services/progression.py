"""
Setup progression detection.

Compares the current scan result against the most-recently saved result for
the same symbol and derives:
  - progression_type
  - progression_label
  - progression_priority
  - previous_scan_result_id
  - previous_status
  - previous_watchlist_level
  - previous_score

All logic is pure — no DB access, no engine calls, no side-effects.
"""

# ── Level ranking ──────────────────────────────────────────────────────────────
# near_miss(0) < L1(1) < L2(2) < L3(3) < L4(4) < confirmed(5)

_LEVEL: dict = {
    "confirmed": 5,
    "L4":        4,
    "L3":        3,
    "L2":        2,
    "L1":        1,
    "near_miss": 0,
    None:        -1,
}

SCORE_CHANGE_THRESHOLD = 3.0   # ignore score deltas smaller than this


def _level(classification: str | None, watchlist_level: str | None) -> int:
    if classification == "confirmed":
        return _LEVEL["confirmed"]
    if classification == "watchlist":
        return _LEVEL.get(watchlist_level, _LEVEL["L1"])
    if classification == "near_miss":
        return _LEVEL["near_miss"]
    return _LEVEL[None]


def compute(
    curr_cl:    str   | None,
    curr_wl:    str   | None,
    curr_score: float | None,
    prev_result,               # ScanResult ORM object or None
) -> dict:
    """
    Return a dict of progression fields ready to merge into a result row dict.
    """

    # ── No previous result — brand-new symbol ─────────────────────────────────
    if prev_result is None:
        return _make("new_setup", "New Setup", 60, None, None, None, None)

    prev_cl    = prev_result.classification
    prev_wl    = prev_result.watchlist_level
    prev_score = (
        float(prev_result.score) if prev_result.score is not None else None
    )

    curr_lvl = _level(curr_cl, curr_wl)
    prev_lvl = _level(prev_cl, prev_wl)

    # ── Became confirmed ──────────────────────────────────────────────────────
    if curr_cl == "confirmed" and prev_cl != "confirmed":
        if prev_cl == "watchlist" and prev_wl:
            label = f"Improved {prev_wl} → Confirmed"
        else:
            label = "Became Confirmed"
        return _make("became_confirmed", label, 100,
                     prev_result, prev_cl, prev_wl, prev_score)

    # ── Improved watchlist level ───────────────────────────────────────────────
    if curr_cl == "watchlist" and prev_cl == "watchlist" and curr_lvl > prev_lvl:
        label = f"Improved {prev_wl or 'L1'} → {curr_wl or 'L1'}"
        return _make("improved_level", label, 80,
                     prev_result, prev_cl, prev_wl, prev_score)

    # ── Became watchlist (was near_miss) ──────────────────────────────────────
    if curr_cl == "watchlist" and prev_cl == "near_miss":
        wl_desc = f" ({curr_wl})" if curr_wl else ""
        return _make("became_watchlist", f"Became Watchlist{wl_desc}", 70,
                     prev_result, prev_cl, prev_wl, prev_score)

    # ── Degraded from confirmed ───────────────────────────────────────────────
    if prev_cl == "confirmed" and curr_cl != "confirmed":
        if curr_cl == "watchlist":
            dest  = curr_wl or "Watchlist"
            label = f"Degraded Confirmed → {dest}"
            prio  = -50
        else:
            label = "Degraded Confirmed → Near Miss"
            prio  = -60
        return _make("degraded_level", label, prio,
                     prev_result, prev_cl, prev_wl, prev_score)

    # ── Degraded watchlist level ───────────────────────────────────────────────
    if curr_cl == "watchlist" and prev_cl == "watchlist" and curr_lvl < prev_lvl:
        label = f"Degraded {prev_wl or 'L1'} → {curr_wl or 'L1'}"
        return _make("degraded_level", label, -30,
                     prev_result, prev_cl, prev_wl, prev_score)

    # ── Became near_miss (was watchlist) ──────────────────────────────────────
    if curr_cl == "near_miss" and prev_cl == "watchlist":
        label = f"Degraded {prev_wl or 'Watchlist'} → Near Miss" if prev_wl else "Became Near Miss"
        return _make("became_near_miss", label, -40,
                     prev_result, prev_cl, prev_wl, prev_score)

    # ── Score comparison (same classification + level) ────────────────────────
    if curr_score is not None and prev_score is not None:
        delta = curr_score - prev_score
        if delta >= SCORE_CHANGE_THRESHOLD:
            return _make("score_improved", f"Score +{delta:.1f}", 40,
                         prev_result, prev_cl, prev_wl, prev_score)
        if delta <= -SCORE_CHANGE_THRESHOLD:
            return _make("score_degraded", f"Score {delta:.1f}", -10,
                         prev_result, prev_cl, prev_wl, prev_score)

    # ── Unchanged ─────────────────────────────────────────────────────────────
    return _make("unchanged", "Unchanged", 20,
                 prev_result, prev_cl, prev_wl, prev_score)


# ── Private helper ─────────────────────────────────────────────────────────────

def _make(
    ptype:      str,
    plabel:     str,
    pprio:      int,
    prev,               # ScanResult | None
    prev_cl:    str | None,
    prev_wl:    str | None,
    prev_score: float | None,
) -> dict:
    return {
        "progression_type":         ptype,
        "progression_label":        plabel,
        "progression_priority":     pprio,
        "previous_scan_result_id":  prev.id if prev is not None else None,
        "previous_status":          prev_cl,
        "previous_watchlist_level": prev_wl,
        "previous_score":           prev_score,
    }
