import uuid
from datetime import datetime, timezone

from sqlalchemy.dialects.postgresql import JSONB

from app.extensions import db


class Direction:
    BULLISH = "bullish"
    BEARISH = "bearish"
    NEUTRAL = "neutral"
    ALL = [BULLISH, BEARISH, NEUTRAL]


class Grade:
    A  = "A"
    B  = "B"
    C  = "C"
    D  = "D"
    NM = "NM"
    ALL = [A, B, C, D, NM]


class ScanResult(db.Model):
    __tablename__ = "scan_results"

    __table_args__ = (
        db.Index("ix_scan_results_scan_job_id",    "scan_job_id"),
        db.Index("ix_scan_results_symbol",         "symbol"),
        db.Index("ix_scan_results_classification", "classification"),
    )

    id          = db.Column(db.UUID(as_uuid=True), primary_key=True, default=uuid.uuid4, nullable=False)
    scan_job_id = db.Column(db.UUID(as_uuid=True), db.ForeignKey("scan_jobs.id", ondelete="CASCADE"), nullable=False)

    # ── Core identity ─────────────────────────────────────────────────────────
    symbol     = db.Column(db.String(50),  nullable=False)
    direction  = db.Column(db.String(20),  nullable=True)
    setup_type = db.Column(db.String(100), nullable=True)
    score      = db.Column(db.Numeric(5, 2), nullable=True)
    grade      = db.Column(db.String(5),   nullable=True)
    timeframe  = db.Column(db.String(20),  nullable=True)

    # ── Denormalised queryable fields ─────────────────────────────────────────
    classification        = db.Column(db.String(30),  nullable=True)
    watchlist_level       = db.Column(db.String(5),   nullable=True)
    watchlist_level_label = db.Column(db.String(120), nullable=True)
    current_stage_label   = db.Column(db.String(150), nullable=True)
    trade_plan_type       = db.Column(db.String(30),  nullable=True)
    liquidity_source      = db.Column(db.String(50),  nullable=True)
    entry                 = db.Column(db.Float, nullable=True)
    stop_loss             = db.Column(db.Float, nullable=True)
    target_1              = db.Column(db.Float, nullable=True)
    target_2              = db.Column(db.Float, nullable=True)
    risk                  = db.Column(db.Float, nullable=True)
    sequence_valid        = db.Column(db.Boolean, nullable=True)
    entry_ready           = db.Column(db.Boolean, nullable=True)

    # ── JSON payloads ─────────────────────────────────────────────────────────
    quality_flags = db.Column(JSONB, nullable=True)   # [{id, label, severity, detail}]
    checklist     = db.Column(JSONB, nullable=True)   # {htf: {...}, ltf: {...}}
    debug_trace   = db.Column(JSONB, nullable=True)   # full engine debug dict
    result_data   = db.Column(JSONB, nullable=True)   # complete engine result payload

    # ── Progression (filled when result is saved, compared to previous run) ───
    progression_type         = db.Column(db.String(40),  nullable=True)
    progression_label        = db.Column(db.String(120), nullable=True)
    progression_priority     = db.Column(db.Integer,     nullable=True)
    previous_scan_result_id  = db.Column(db.UUID(as_uuid=True), nullable=True)
    previous_status          = db.Column(db.String(30),  nullable=True)
    previous_watchlist_level = db.Column(db.String(10),  nullable=True)
    previous_score           = db.Column(db.Float,       nullable=True)

    created_at = db.Column(db.DateTime(timezone=True), nullable=False,
                            default=lambda: datetime.now(timezone.utc))

    # ── Relationships ─────────────────────────────────────────────────────────
    scan_job = db.relationship("ScanJob", back_populates="results")

    def __repr__(self):
        return f"<ScanResult {self.symbol} job={self.scan_job_id} cl={self.classification}>"

    def to_dict(self):
        return {
            "id":                    str(self.id),
            "scan_job_id":           str(self.scan_job_id),
            "symbol":                self.symbol,
            "direction":             self.direction,
            "setup_type":            self.setup_type,
            "score":                 float(self.score) if self.score is not None else None,
            "grade":                 self.grade,
            "timeframe":             self.timeframe,
            "classification":        self.classification,
            "watchlist_level":       self.watchlist_level,
            "watchlist_level_label": self.watchlist_level_label,
            "current_stage_label":   self.current_stage_label,
            "trade_plan_type":       self.trade_plan_type,
            "liquidity_source":      self.liquidity_source,
            "entry":                 self.entry,
            "stop_loss":             self.stop_loss,
            "target_1":              self.target_1,
            "target_2":              self.target_2,
            "risk":                  self.risk,
            "sequence_valid":        self.sequence_valid,
            "entry_ready":           self.entry_ready,
            "quality_flags":         self.quality_flags,
            "checklist":             self.checklist,
            "debug_trace":           self.debug_trace,
            "result_data":           self.result_data,
            # progression
            "progression_type":          self.progression_type,
            "progression_label":         self.progression_label,
            "progression_priority":      self.progression_priority,
            "previous_scan_result_id":   str(self.previous_scan_result_id) if self.previous_scan_result_id else None,
            "previous_status":           self.previous_status,
            "previous_watchlist_level":  self.previous_watchlist_level,
            "previous_score":            self.previous_score,
            "created_at":            self.created_at.isoformat(),
        }
