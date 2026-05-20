"""
ScanSnapshot — one row per successful full-universe scanner run.

Stores the complete response payload so it can be served as a fallback
when NSE is closed or unreachable, preserving the last known market
state for traders who open the app outside market hours.

Access patterns:
  1. Latest snapshot for threshold           → (threshold, created_at DESC)
  2. History list                            → (created_at DESC)
  3. By ID for snapshot detail               → (id)

Design decisions:
  • payload_json stores the entire ``run_scanner()`` response as TEXT.
    This avoids schema churn when the scanner adds new fields, and lets
    the API return it verbatim without reconstructing Python objects.
  • threshold is stored as REAL so different threshold configs each get
    their own latest snapshot (a 0% run and a 2% run are different views).
  • symbol_count / avg_fetch_ms / scan_elapsed_ms are promoted to columns
    so history queries can filter/sort without JSON parsing.
  • market_status is a freeform label (e.g. "open", "closed", "holiday").
"""

import uuid
from datetime import datetime, timezone

from app.extensions import db


class ScanSnapshot(db.Model):
    __tablename__ = "scan_snapshots"

    __table_args__ = (
        # Primary: latest snapshot per threshold
        db.Index("ix_ss_threshold_time", "threshold", "created_at"),
        # History list (all thresholds)
        db.Index("ix_ss_created_at",     "created_at"),
        # Filter on market status
        db.Index("ix_ss_market_status",  "market_status"),
    )

    id = db.Column(
        db.UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
        nullable=False,
    )

    # ── Timing ────────────────────────────────────────────────────────────────
    created_at = db.Column(
        db.DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
        index=False,  # covered by ix_ss_created_at above
    )

    # ── Scan config ───────────────────────────────────────────────────────────
    threshold = db.Column(db.Float, nullable=False, default=2.0)

    # ── Aggregate metrics (promoted columns — no JSON parse needed) ───────────
    symbol_count    = db.Column(db.Integer, nullable=True)   # symbols with valid data
    avg_fetch_ms    = db.Column(db.Float,   nullable=True)
    scan_elapsed_ms = db.Column(db.Float,   nullable=True)

    # ── Market context ────────────────────────────────────────────────────────
    market_status = db.Column(db.String(20), nullable=True)   # "open" | "closed" | "unknown"

    # ── Payload ───────────────────────────────────────────────────────────────
    # Full run_scanner() response as JSON text.  TEXT (not JSONB) because:
    #   - We only ever read it back whole (no column projection needed).
    #   - Keeps the model portable to SQLite for tests.
    payload_json = db.Column(db.Text, nullable=False)

    # ── Convenience ───────────────────────────────────────────────────────────
    def age_minutes(self) -> float:
        """How many minutes ago this snapshot was taken (float, UTC-aware)."""
        now = datetime.now(timezone.utc)
        created = self.created_at
        # Ensure timezone-aware comparison
        if created.tzinfo is None:
            created = created.replace(tzinfo=timezone.utc)
        delta = now - created
        return delta.total_seconds() / 60.0

    def to_meta(self) -> dict:
        """Lightweight metadata dict (no payload) — for history lists."""
        return {
            "id":               str(self.id),
            "created_at":       self.created_at.isoformat(),
            "age_minutes":      round(self.age_minutes(), 1),
            "threshold":        self.threshold,
            "symbol_count":     self.symbol_count,
            "avg_fetch_ms":     self.avg_fetch_ms,
            "scan_elapsed_ms":  self.scan_elapsed_ms,
            "market_status":    self.market_status,
        }

    def __repr__(self):
        return (
            f"<ScanSnapshot id={str(self.id)[:8]}… "
            f"threshold={self.threshold}% symbols={self.symbol_count} "
            f"@ {self.created_at}>"
        )
