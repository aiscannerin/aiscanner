"""
Tests for scan_snapshot_service.py
====================================
All tests use an in-memory SQLite database via a lightweight Flask app context.
No NSE network calls, no external dependencies.

Coverage
--------
  TestSaveSnapshot
    test_save_with_results_persists          — valid scan saved successfully
    test_save_without_results_skips          — market-closed run not saved
    test_save_returns_none_on_empty_results  — empty results → None
    test_save_stores_full_payload            — payload_json round-trips
    test_save_stores_metrics                 — avg_fetch_ms / scan_elapsed_ms columns
    test_save_stores_market_status_open      — market_status inferred as "open"
    test_save_market_closed_no_results_skips — market-closed skip path

  TestGetLatestSnapshot
    test_get_latest_returns_most_recent      — newest row returned
    test_get_latest_threshold_filter         — threshold filter works
    test_get_latest_no_match_falls_back_to_any — wrong threshold → any-threshold fallback
    test_get_latest_empty_db_returns_none    — empty table → None

  TestGetSnapshotHistory
    test_history_ordered_newest_first        — descending order
    test_history_limit_respected             — limit param obeyed
    test_history_empty_db_returns_empty_list — empty table → []
    test_history_returns_meta_not_payload    — payload absent from history items

  TestFallbackBehaviour
    test_fallback_age_minutes_positive       — age > 0 after creation
    test_stale_snapshot_age_correct          — age reported in minutes correctly
    test_no_snapshot_load_returns_none       — load_snapshot_payload(None) → None
    test_payload_round_trips                 — save then load gives identical dict
"""

from __future__ import annotations

import json
import sys
import os
import importlib.util
import time as _time
import pytest

# ---------------------------------------------------------------------------
# Bootstrap: build a minimal Flask + SQLAlchemy app using SQLite in-memory.
# This avoids importing the real app (which needs redis, postgres, etc.)
# ---------------------------------------------------------------------------

from flask import Flask
from flask_sqlalchemy import SQLAlchemy

# Create a throwaway db instance (tests must not share state with production)
_test_db = SQLAlchemy()


def _make_app() -> Flask:
    app = Flask(__name__)
    app.config["SQLALCHEMY_DATABASE_URI"] = "sqlite:///:memory:"
    app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False
    app.config["TESTING"] = True
    _test_db.init_app(app)
    return app


# ---------------------------------------------------------------------------
# Stub out the production `app.extensions.db` with our test db, then load
# the model and service modules by file path so they use _test_db.
# ---------------------------------------------------------------------------

# 1. Register fake app.extensions module
import types as _types

_ext_mod = _types.ModuleType("app.extensions")
_ext_mod.db = _test_db
sys.modules["app.extensions"] = _ext_mod

# 2. Load the model
_ROOT = os.path.join(os.path.dirname(__file__), "..")


def _load(rel: str):
    path    = os.path.normpath(os.path.join(_ROOT, rel))
    name    = rel.replace("/", ".").replace("\\", ".").replace(".py", "")
    spec    = importlib.util.spec_from_file_location(name, path)
    mod     = importlib.util.module_from_spec(spec)
    mod.__name__    = name
    mod.__package__ = name.rsplit(".", 1)[0] if "." in name else name
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


_snapshot_model_mod = _load("app/models/scan_snapshot.py")
ScanSnapshot = _snapshot_model_mod.ScanSnapshot

# 3. Register model under canonical import path so the service finds it
_model_pkg = _types.ModuleType("app.models.scan_snapshot")
_model_pkg.ScanSnapshot = ScanSnapshot
sys.modules["app.models.scan_snapshot"] = _model_pkg

# 4. Load the service
_svc_mod = _load("app/services/scan_snapshot_service.py")

save_scan_snapshot    = _svc_mod.save_scan_snapshot
get_latest_snapshot   = _svc_mod.get_latest_snapshot
get_snapshot_history  = _svc_mod.get_snapshot_history
load_snapshot_payload = _svc_mod.load_snapshot_payload
count_snapshots       = _svc_mod.count_snapshots


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture()
def app():
    application = _make_app()
    # Register the model table so create_all knows about it
    with application.app_context():
        _test_db.create_all()
    yield application
    with application.app_context():
        _test_db.drop_all()


@pytest.fixture()
def ctx(app):
    """Push an app context for the duration of a test."""
    with app.app_context():
        yield


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _scan_response(
    n_results: int = 3,
    n_closed:  int = 0,
    avg_fetch_ms:   float = 310.0,
    scan_elapsed_ms: float = 4200.0,
) -> dict:
    """Build a minimal run_scanner()-shaped response dict."""
    results = [
        {
            "symbol":        f"SYM{i}",
            "spot_price":    1000.0 + i,
            "max_pain":      1010.0 + i,
            "distance_pct":  3.5,
            "reversal_score": 70,
        }
        for i in range(n_results)
    ]
    closed = [f"CLOSED{i}" for i in range(n_closed)]
    return {
        "results":       results,
        "errors":        [],
        "below_threshold": [],
        "market_closed": closed,
        "summary": {
            "total_scanned": n_results + n_closed,
            "total_hits":    n_results,
        },
        "metrics": {
            "avg_fetch_ms":    avg_fetch_ms,
            "scan_elapsed_ms": scan_elapsed_ms,
            "fetch_success":   n_results,
            "market_closed":   n_closed,
        },
    }


# ===========================================================================
# TestSaveSnapshot
# ===========================================================================

class TestSaveSnapshot:

    def test_save_with_results_persists(self, ctx):
        resp = _scan_response(n_results=3)
        snap = save_scan_snapshot(resp, threshold=2.0)
        assert snap is not None
        assert snap.id is not None

    def test_save_without_results_skips(self, ctx):
        resp = _scan_response(n_results=0, n_closed=5)
        snap = save_scan_snapshot(resp, threshold=2.0)
        assert snap is None

    def test_save_returns_none_on_empty_results(self, ctx):
        resp = _scan_response(n_results=0, n_closed=0)
        snap = save_scan_snapshot(resp, threshold=2.0)
        assert snap is None

    def test_save_stores_full_payload(self, ctx):
        resp = _scan_response(n_results=2)
        snap = save_scan_snapshot(resp, threshold=2.0)
        assert snap is not None
        payload = load_snapshot_payload(snap)
        assert payload is not None
        assert len(payload["results"]) == 2

    def test_save_stores_metrics(self, ctx):
        resp = _scan_response(avg_fetch_ms=315.5, scan_elapsed_ms=9800.0)
        snap = save_scan_snapshot(resp, threshold=2.0)
        assert snap is not None
        assert abs(snap.avg_fetch_ms - 315.5) < 0.01
        assert abs(snap.scan_elapsed_ms - 9800.0) < 0.01

    def test_save_stores_market_status_open(self, ctx):
        resp = _scan_response(n_results=5)
        snap = save_scan_snapshot(resp, threshold=2.0)
        assert snap is not None
        assert snap.market_status == "open"

    def test_save_market_closed_no_results_skips(self, ctx):
        # Market-closed-only run must NOT be persisted
        resp = _scan_response(n_results=0, n_closed=10)
        snap = save_scan_snapshot(resp, threshold=2.0)
        assert snap is None

    def test_save_stores_symbol_count(self, ctx):
        resp = _scan_response(n_results=7)
        snap = save_scan_snapshot(resp, threshold=2.0)
        assert snap.symbol_count == 7

    def test_save_stores_threshold(self, ctx):
        resp = _scan_response(n_results=2)
        snap = save_scan_snapshot(resp, threshold=4.0)
        assert snap.threshold == 4.0


# ===========================================================================
# TestGetLatestSnapshot
# ===========================================================================

class TestGetLatestSnapshot:

    def test_get_latest_returns_most_recent(self, ctx):
        save_scan_snapshot(_scan_response(n_results=1), threshold=2.0)
        _time.sleep(0.01)   # ensure distinct created_at
        save_scan_snapshot(_scan_response(n_results=3), threshold=2.0)
        snap = get_latest_snapshot()
        assert snap is not None
        assert snap.symbol_count == 3

    def test_get_latest_threshold_filter(self, ctx):
        save_scan_snapshot(_scan_response(n_results=2), threshold=2.0)
        save_scan_snapshot(_scan_response(n_results=5), threshold=4.0)
        snap = get_latest_snapshot(threshold=4.0)
        assert snap is not None
        assert snap.threshold == 4.0
        assert snap.symbol_count == 5

    def test_get_latest_no_match_falls_back_to_any(self, ctx):
        # Service falls back to newest row when approx-threshold match fails.
        save_scan_snapshot(_scan_response(n_results=2), threshold=2.0)
        snap = get_latest_snapshot(threshold=6.0)  # no 6% snapshot saved
        # any-threshold fallback kicks in — still returns the 2.0 row
        assert snap is not None
        assert snap.threshold == 2.0

    def test_get_latest_empty_db_returns_none(self, ctx):
        snap = get_latest_snapshot()
        assert snap is None

    def test_get_latest_none_threshold_ignores_filter(self, ctx):
        save_scan_snapshot(_scan_response(n_results=4), threshold=0.0)
        snap = get_latest_snapshot(threshold=None)
        assert snap is not None
        assert snap.symbol_count == 4


# ===========================================================================
# TestGetSnapshotHistory
# ===========================================================================

class TestGetSnapshotHistory:

    def test_history_ordered_newest_first(self, ctx):
        save_scan_snapshot(_scan_response(n_results=1), threshold=2.0)
        _time.sleep(0.01)
        save_scan_snapshot(_scan_response(n_results=4), threshold=2.0)
        history = get_snapshot_history(limit=10)
        assert len(history) == 2
        assert history[0]["symbol_count"] == 4   # newest first
        assert history[1]["symbol_count"] == 1

    def test_history_limit_respected(self, ctx):
        for i in range(5):
            save_scan_snapshot(_scan_response(n_results=i + 1), threshold=2.0)
        history = get_snapshot_history(limit=3)
        assert len(history) == 3

    def test_history_empty_db_returns_empty_list(self, ctx):
        history = get_snapshot_history()
        assert history == []

    def test_history_returns_meta_not_payload(self, ctx):
        save_scan_snapshot(_scan_response(n_results=2), threshold=2.0)
        history = get_snapshot_history()
        assert len(history) == 1
        item = history[0]
        # Must have meta fields
        assert "id" in item
        assert "created_at" in item
        assert "age_minutes" in item
        assert "threshold" in item
        assert "symbol_count" in item
        # Must NOT have payload
        assert "payload_json" not in item
        assert "data" not in item


# ===========================================================================
# TestFallbackBehaviour
# ===========================================================================

class TestFallbackBehaviour:

    def test_fallback_age_minutes_positive(self, ctx):
        snap = save_scan_snapshot(_scan_response(n_results=2), threshold=2.0)
        assert snap is not None
        assert snap.age_minutes() >= 0.0

    def test_stale_snapshot_age_correct(self, ctx):
        """age_minutes should reflect elapsed wall-clock time."""
        snap = save_scan_snapshot(_scan_response(n_results=1), threshold=2.0)
        _time.sleep(0.1)
        # Age should be at least 0.1s = 0.001666 min — just check > 0
        assert snap.age_minutes() > 0.0

    def test_no_snapshot_load_returns_none(self, ctx):
        result = load_snapshot_payload(None)
        assert result is None

    def test_payload_round_trips(self, ctx):
        original = _scan_response(n_results=3, avg_fetch_ms=512.0)
        snap = save_scan_snapshot(original, threshold=2.0)
        assert snap is not None
        recovered = load_snapshot_payload(snap)
        assert recovered is not None
        # Core fields survive round-trip
        assert len(recovered["results"]) == 3
        assert recovered["metrics"]["avg_fetch_ms"] == 512.0

    def test_to_meta_contains_expected_keys(self, ctx):
        snap = save_scan_snapshot(_scan_response(n_results=2), threshold=2.0)
        meta = snap.to_meta()
        for key in ("id", "created_at", "age_minutes", "threshold",
                    "symbol_count", "avg_fetch_ms", "scan_elapsed_ms",
                    "market_status"):
            assert key in meta, f"Missing key: {key}"

    def test_snapshot_fallback_latest_then_any_threshold(self, ctx):
        """Simulates the route's two-step lookup: approx match → any-threshold."""
        save_scan_snapshot(_scan_response(n_results=5), threshold=2.0)
        # Exact miss — but service now falls back to any-threshold internally
        snap = get_latest_snapshot(threshold=4.0)
        assert snap is not None   # any-threshold fallback finds the 2.0 row
        assert snap.symbol_count == 5

    def test_approx_threshold_matches_close_float(self, ctx):
        """2.0001 should match a row stored at 2.0 (within epsilon=0.01)."""
        save_scan_snapshot(_scan_response(n_results=3), threshold=2.0)
        snap = get_latest_snapshot(threshold=2.0001)
        assert snap is not None
        assert snap.threshold == 2.0

    def test_approx_threshold_no_match_outside_epsilon(self, ctx):
        """4.5 should NOT approx-match a row stored at 2.0 (> epsilon),
        but the any-threshold fallback should still find it."""
        save_scan_snapshot(_scan_response(n_results=3), threshold=2.0)
        snap = get_latest_snapshot(threshold=4.5)
        # any-threshold fallback runs → still returns the 2.0 row
        assert snap is not None
        assert snap.threshold == 2.0


# ===========================================================================
# TestCountSnapshots
# ===========================================================================

class TestCountSnapshots:

    def test_count_zero_when_empty(self, ctx):
        assert count_snapshots() == 0

    def test_count_after_one_save(self, ctx):
        save_scan_snapshot(_scan_response(n_results=2), threshold=2.0)
        assert count_snapshots() == 1

    def test_count_after_multiple_saves(self, ctx):
        for i in range(4):
            save_scan_snapshot(_scan_response(n_results=i + 1), threshold=2.0)
        assert count_snapshots() == 4

    def test_count_does_not_count_skipped(self, ctx):
        # Empty results → skipped → count stays 0
        save_scan_snapshot(_scan_response(n_results=0, n_closed=5), threshold=2.0)
        assert count_snapshots() == 0
