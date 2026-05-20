import uuid
from datetime import datetime, timezone

from sqlalchemy.dialects.postgresql import JSONB

from app.extensions import db


class ScanJobStatus:
    QUEUED    = "queued"
    RUNNING   = "running"
    COMPLETED = "completed"
    FAILED    = "failed"
    CANCELLED = "cancelled"
    ALL = [QUEUED, RUNNING, COMPLETED, FAILED, CANCELLED]


class ScanJob(db.Model):
    __tablename__ = "scan_jobs"

    __table_args__ = (
        db.Index("ix_scan_jobs_user_status", "user_id", "status"),
    )

    id = db.Column(db.UUID(as_uuid=True), primary_key=True, default=uuid.uuid4, nullable=False)
    user_id  = db.Column(db.UUID(as_uuid=True), db.ForeignKey("users.id",  ondelete="CASCADE"),   nullable=False)
    tool_id  = db.Column(db.UUID(as_uuid=True), db.ForeignKey("tools.id",  ondelete="RESTRICT"),  nullable=False)
    status   = db.Column(db.String(20),  nullable=False, default=ScanJobStatus.QUEUED)

    # ── Core identity ─────────────────────────────────────────────────────────
    scanner_name   = db.Column(db.String(100), nullable=True)   # e.g. "stop-hunter-pro"
    universe       = db.Column(db.String(100), nullable=False)
    timeframe      = db.Column(db.String(20),  nullable=False)  # HTF
    ltf            = db.Column(db.String(20),  nullable=True)   # LTF derived from HTF
    scan_mode      = db.Column(db.String(20),  nullable=True)   # "mock" | "live"
    candidate_mode = db.Column(db.String(20),  nullable=True)   # "fast" | "best_setup"
    filters        = db.Column(JSONB,          nullable=True)

    # ── Progress ─────────────────────────────────────────────────────────────
    progress          = db.Column(db.Integer, nullable=False, default=0)
    total_symbols     = db.Column(db.Integer, nullable=True)
    completed_symbols = db.Column(db.Integer, nullable=False, default=0)

    # ── Result counts (filled on completion) ─────────────────────────────────
    confirmed_count = db.Column(db.Integer, nullable=True)
    watchlist_count = db.Column(db.Integer, nullable=True)
    near_miss_count = db.Column(db.Integer, nullable=True)
    no_result_count = db.Column(db.Integer, nullable=True)

    # ── Timing / cache metrics ────────────────────────────────────────────────
    fetch_elapsed_s = db.Column(db.Float, nullable=True)
    scan_elapsed_s  = db.Column(db.Float, nullable=True)
    cache_hits      = db.Column(db.Integer, nullable=True)
    cache_misses    = db.Column(db.Integer, nullable=True)

    # ── Scan health (data integrity layer) ────────────────────────────────────
    scan_health_json  = db.Column(JSONB, nullable=True)
    symbols_requested = db.Column(db.Integer, nullable=True)
    symbols_scanned   = db.Column(db.Integer, nullable=True)
    symbols_failed    = db.Column(db.Integer, nullable=True)
    partial_scan      = db.Column(db.Boolean, nullable=True)
    data_quality      = db.Column(db.String(10), nullable=True)  # good|partial|poor

    # ── Timestamps ────────────────────────────────────────────────────────────
    created_at   = db.Column(db.DateTime(timezone=True), nullable=False,
                              default=lambda: datetime.now(timezone.utc))
    completed_at = db.Column(db.DateTime(timezone=True), nullable=True)

    # ── Relationships ─────────────────────────────────────────────────────────
    user    = db.relationship("User",       back_populates="scan_jobs")
    tool    = db.relationship("Tool",       back_populates="scan_jobs")
    results = db.relationship("ScanResult", back_populates="scan_job",
                               cascade="all, delete-orphan")

    def __repr__(self):
        return f"<ScanJob {self.id} status={self.status}>"

    def to_dict(self):
        return {
            "id":               str(self.id),
            "user_id":          str(self.user_id),
            "tool":             self.tool.to_dict() if self.tool else None,
            "scanner_name":     self.scanner_name,
            "status":           self.status,
            "universe":         self.universe,
            "timeframe":        self.timeframe,
            "ltf":              self.ltf,
            "scan_mode":        self.scan_mode,
            "candidate_mode":   self.candidate_mode,
            "filters":          self.filters,
            "progress":         self.progress,
            "total_symbols":    self.total_symbols,
            "completed_symbols": self.completed_symbols,
            "confirmed_count":  self.confirmed_count,
            "watchlist_count":  self.watchlist_count,
            "near_miss_count":  self.near_miss_count,
            "no_result_count":  self.no_result_count,
            "fetch_elapsed_s":  self.fetch_elapsed_s,
            "scan_elapsed_s":   self.scan_elapsed_s,
            "cache_hits":       self.cache_hits,
            "cache_misses":     self.cache_misses,
            "created_at":       self.created_at.isoformat(),
            "completed_at":     self.completed_at.isoformat() if self.completed_at else None,
            # ── scan health ───────────────────────────────────────────────────
            "scan_health":        self.scan_health_json,
            "symbols_requested":  self.symbols_requested,
            "symbols_scanned":    self.symbols_scanned,
            "symbols_failed":     self.symbols_failed,
            "partial_scan":       self.partial_scan,
            "data_quality":       self.data_quality,
        }
