"""
Option Chain Fetch Monitor
===========================
Thread-safe in-memory metrics for the NSE option chain fetcher.

Usage (from nse_option_chain_service.py):
    from app.services.option_chain_monitor import monitor
    monitor.record_fetch_start(symbol)
    monitor.record_fetch_success(symbol, latency_ms=240)
    monitor.record_cache_hit(symbol)
    monitor.record_validation_result(symbol, is_valid=True, warning_count=0)
    monitor.record_retry(symbol)
    monitor.record_session_built()

The singleton `monitor` is safe to import at module level.
"""

from __future__ import annotations

import threading
import time
from collections import deque
from datetime import datetime, timezone
from typing import Optional


class _PerSymbolStats:
    """Lightweight per-symbol counters."""
    __slots__ = (
        "fetch_count", "fetch_success", "fetch_failure",
        "cache_hit", "cache_miss",
        "validation_pass", "validation_fail", "validation_warnings",
        "retry_count",
        "last_success_ts", "last_failure_ts",
    )

    def __init__(self) -> None:
        self.fetch_count         = 0
        self.fetch_success       = 0
        self.fetch_failure       = 0
        self.cache_hit           = 0
        self.cache_miss          = 0
        self.validation_pass     = 0
        self.validation_fail     = 0
        self.validation_warnings = 0
        self.retry_count         = 0
        self.last_success_ts: Optional[str] = None
        self.last_failure_ts:  Optional[str] = None

    def to_dict(self) -> dict:
        total_f = self.fetch_success + self.fetch_failure
        total_v = self.validation_pass + self.validation_fail
        total_c = self.cache_hit + self.cache_miss
        return {
            "fetch_count":      self.fetch_count,
            "fetch_success":    self.fetch_success,
            "fetch_failure":    self.fetch_failure,
            "success_rate":     round(self.fetch_success / total_f, 3) if total_f else None,
            "cache_hit":        self.cache_hit,
            "cache_miss":       self.cache_miss,
            "cache_hit_rate":   round(self.cache_hit / total_c, 3) if total_c else None,
            "validation_pass":  self.validation_pass,
            "validation_fail":  self.validation_fail,
            "validation_warnings": self.validation_warnings,
            "validation_pass_rate": round(self.validation_pass / total_v, 3) if total_v else None,
            "retry_count":      self.retry_count,
            "last_success_ts":  self.last_success_ts,
            "last_failure_ts":  self.last_failure_ts,
        }


class FetchMonitor:
    """
    Singleton metrics store for the NSE fetcher.

    All methods are thread-safe (guarded by a single RLock).
    Latency samples are stored in a bounded deque (last 500 samples)
    to allow avg and p95 computation without unbounded memory growth.
    """

    _MAX_LATENCY_SAMPLES = 500

    def __init__(self) -> None:
        self._lock = threading.RLock()

        # Global counters
        self._fetch_count         = 0
        self._fetch_success_count = 0
        self._fetch_failure_count = 0
        self._validation_pass     = 0
        self._validation_fail     = 0
        self._validation_warnings = 0
        self._cache_hit_count     = 0
        self._cache_miss_count    = 0
        self._retry_count         = 0

        # Latency (ms) ring buffer
        self._latency_samples: deque[float] = deque(maxlen=self._MAX_LATENCY_SAMPLES)

        # Timestamps
        self._last_success_ts:  Optional[str] = None
        self._last_failure_ts:  Optional[str] = None
        self._session_built_at: Optional[str] = None

        # Per-symbol breakdown
        self._per_symbol: dict[str, _PerSymbolStats] = {}

    # -----------------------------------------------------------------------
    # Internal helpers
    # -----------------------------------------------------------------------

    def _sym(self, symbol: str) -> _PerSymbolStats:
        if symbol not in self._per_symbol:
            self._per_symbol[symbol] = _PerSymbolStats()
        return self._per_symbol[symbol]

    @staticmethod
    def _now_iso() -> str:
        return datetime.now(timezone.utc).isoformat()

    # -----------------------------------------------------------------------
    # Recording methods — called by nse_option_chain_service
    # -----------------------------------------------------------------------

    def record_fetch_start(self, symbol: str = "") -> None:
        with self._lock:
            self._fetch_count += 1
            if symbol:
                self._sym(symbol).fetch_count += 1

    def record_fetch_success(self, symbol: str = "", latency_ms: float = 0.0) -> None:
        with self._lock:
            self._fetch_success_count += 1
            self._last_success_ts = self._now_iso()
            if latency_ms > 0:
                self._latency_samples.append(latency_ms)
            if symbol:
                s = self._sym(symbol)
                s.fetch_success += 1
                s.last_success_ts = self._last_success_ts

    def record_fetch_failure(self, symbol: str = "", error_code: str = "") -> None:
        with self._lock:
            self._fetch_failure_count += 1
            self._last_failure_ts = self._now_iso()
            if symbol:
                s = self._sym(symbol)
                s.fetch_failure += 1
                s.last_failure_ts = self._last_failure_ts

    def record_cache_hit(self, symbol: str = "") -> None:
        with self._lock:
            self._cache_hit_count += 1
            if symbol:
                self._sym(symbol).cache_hit += 1

    def record_cache_miss(self, symbol: str = "") -> None:
        with self._lock:
            self._cache_miss_count += 1
            if symbol:
                self._sym(symbol).cache_miss += 1

    def record_validation_result(
        self,
        symbol: str = "",
        is_valid: bool = True,
        warning_count: int = 0,
    ) -> None:
        with self._lock:
            if is_valid:
                self._validation_pass += 1
                if symbol:
                    self._sym(symbol).validation_pass += 1
            else:
                self._validation_fail += 1
                if symbol:
                    self._sym(symbol).validation_fail += 1
            self._validation_warnings += warning_count
            if symbol:
                self._sym(symbol).validation_warnings += warning_count

    def record_retry(self, symbol: str = "") -> None:
        with self._lock:
            self._retry_count += 1
            if symbol:
                self._sym(symbol).retry_count += 1

    def record_session_built(self) -> None:
        with self._lock:
            self._session_built_at = self._now_iso()

    # -----------------------------------------------------------------------
    # Aggregated snapshots
    # -----------------------------------------------------------------------

    def _latency_stats(self) -> dict:
        samples = list(self._latency_samples)
        if not samples:
            return {"avg_ms": None, "p95_ms": None, "sample_count": 0}
        samples_sorted = sorted(samples)
        avg = sum(samples_sorted) / len(samples_sorted)
        p95_idx = max(0, int(len(samples_sorted) * 0.95) - 1)
        return {
            "avg_ms":       round(avg, 1),
            "p95_ms":       round(samples_sorted[p95_idx], 1),
            "sample_count": len(samples_sorted),
        }

    def fetcher_stats(self) -> dict:
        with self._lock:
            total = self._fetch_success_count + self._fetch_failure_count
            lat   = self._latency_stats()
            return {
                "total_fetches":   self._fetch_count,
                "fetch_success":   self._fetch_success_count,
                "fetch_failure":   self._fetch_failure_count,
                "success_rate":    round(self._fetch_success_count / total, 3) if total else None,
                "retry_count":     self._retry_count,
                "avg_latency_ms":  lat["avg_ms"],
                "p95_latency_ms":  lat["p95_ms"],
                "latency_samples": lat["sample_count"],
                "last_success_ts": self._last_success_ts,
                "last_failure_ts": self._last_failure_ts,
            }

    def cache_stats(self) -> dict:
        with self._lock:
            total = self._cache_hit_count + self._cache_miss_count
            return {
                "hits":     self._cache_hit_count,
                "misses":   self._cache_miss_count,
                "hit_rate": round(self._cache_hit_count / total, 3) if total else None,
            }

    def validation_stats(self) -> dict:
        with self._lock:
            total = self._validation_pass + self._validation_fail
            return {
                "total_validations": total,
                "pass_count":        self._validation_pass,
                "fail_count":        self._validation_fail,
                "pass_rate":         round(self._validation_pass / total, 3) if total else None,
                "total_warnings":    self._validation_warnings,
                "warnings_rate":     round(self._validation_warnings / total, 3) if total else None,
            }

    def session_stats(self) -> dict:
        with self._lock:
            age = None
            if self._session_built_at:
                try:
                    built = datetime.fromisoformat(self._session_built_at)
                    age = int((datetime.now(timezone.utc) - built).total_seconds())
                except (ValueError, TypeError):
                    pass
            return {
                "session_built_at": self._session_built_at,
                "session_age_secs": age,
            }

    def per_symbol_stats(self, symbol: str) -> Optional[dict]:
        with self._lock:
            if symbol not in self._per_symbol:
                return None
            return self._per_symbol[symbol].to_dict()

    def all_symbols(self) -> list[str]:
        with self._lock:
            return list(self._per_symbol.keys())

    def full_snapshot(self) -> dict:
        """Return all metrics in one dict — used by the /health endpoint."""
        with self._lock:
            return {
                "fetcher":    self.fetcher_stats(),
                "cache":      self.cache_stats(),
                "validation": self.validation_stats(),
                "session":    self.session_stats(),
                "symbols":    {sym: self._per_symbol[sym].to_dict()
                               for sym in self._per_symbol},
            }


# ---------------------------------------------------------------------------
# Module-level singleton
# ---------------------------------------------------------------------------

monitor = FetchMonitor()
