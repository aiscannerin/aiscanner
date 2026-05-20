import uuid
from datetime import datetime, timezone

from app.extensions import db

# Default alert preferences
_ALERT_DEFAULTS = {
    "alert_became_confirmed":        True,
    "alert_improved_level":          True,
    "alert_became_watchlist":        True,
    "alert_degraded":                False,
    "alert_score_crossed_threshold": False,
}


class UserTrackedSymbol(db.Model):
    __tablename__ = "user_tracked_symbols"

    __table_args__ = (
        db.UniqueConstraint(
            "user_id", "symbol", "scanner_name", "htf", "ltf",
            name="uq_tracked_active_combo",
        ),
        db.Index("ix_tracked_user_id",   "user_id"),
        db.Index("ix_tracked_symbol",    "symbol"),
        db.Index("ix_tracked_is_active", "is_active"),
    )

    # ── identity ────────────────────────────────────────────────────────────────
    id           = db.Column(db.UUID(as_uuid=True), primary_key=True,
                             default=uuid.uuid4, nullable=False)
    user_id      = db.Column(db.UUID(as_uuid=True),
                             db.ForeignKey("users.id", ondelete="CASCADE"),
                             nullable=True)

    # ── symbol info ─────────────────────────────────────────────────────────────
    symbol       = db.Column(db.String(50),  nullable=False)
    scanner_name = db.Column(db.String(100), nullable=False)
    htf          = db.Column(db.String(10),  nullable=False)
    ltf          = db.Column(db.String(10),  nullable=True)
    note         = db.Column(db.Text(),      nullable=True)
    is_active    = db.Column(db.Boolean(),   nullable=False, default=True)

    # ── alert preferences ────────────────────────────────────────────────────────
    alert_became_confirmed        = db.Column(db.Boolean(), nullable=False, default=True)
    alert_improved_level          = db.Column(db.Boolean(), nullable=False, default=True)
    alert_became_watchlist        = db.Column(db.Boolean(), nullable=False, default=True)
    alert_degraded                = db.Column(db.Boolean(), nullable=False, default=False)
    alert_score_crossed_threshold = db.Column(db.Boolean(), nullable=False, default=False)
    score_threshold               = db.Column(db.Integer(), nullable=True)

    # ── timestamps ───────────────────────────────────────────────────────────────
    created_at   = db.Column(db.DateTime(timezone=True), nullable=False,
                             default=lambda: datetime.now(timezone.utc))
    updated_at   = db.Column(db.DateTime(timezone=True), nullable=False,
                             default=lambda: datetime.now(timezone.utc),
                             onupdate=lambda: datetime.now(timezone.utc))

    def __repr__(self):
        return f"<UserTrackedSymbol {self.symbol} htf={self.htf} active={self.is_active}>"

    def alert_allowed(self, progression_type: str) -> bool:
        """
        Return True if this tracked entry should generate a notification for
        the given progression_type.  Used by notification_service to gate
        per-symbol alerts.
        """
        mapping = {
            "became_confirmed": self.alert_became_confirmed,
            "improved_level":   self.alert_improved_level,
            "became_watchlist": self.alert_became_watchlist,
            "degraded_level":   self.alert_degraded,
            "became_near_miss": self.alert_degraded,
        }
        # Types not in the mapping (new_setup, unchanged, etc.) are never alerted
        return bool(mapping.get(progression_type, False))

    def alert_prefs_dict(self) -> dict:
        return {
            "alert_became_confirmed":        self.alert_became_confirmed,
            "alert_improved_level":          self.alert_improved_level,
            "alert_became_watchlist":        self.alert_became_watchlist,
            "alert_degraded":                self.alert_degraded,
            "alert_score_crossed_threshold": self.alert_score_crossed_threshold,
            "score_threshold":               self.score_threshold,
        }

    def to_dict(self, latest_result=None):
        d = {
            "id":           str(self.id),
            "user_id":      str(self.user_id) if self.user_id else None,
            "symbol":       self.symbol,
            "scanner_name": self.scanner_name,
            "htf":          self.htf,
            "ltf":          self.ltf,
            "note":         self.note,
            "is_active":    self.is_active,
            "alert_prefs":  self.alert_prefs_dict(),
            "created_at":   self.created_at.isoformat(),
            "updated_at":   self.updated_at.isoformat(),
            "latest":       None,
        }
        if latest_result is not None:
            d["latest"] = {
                "classification":      latest_result.classification,
                "watchlist_level":     latest_result.watchlist_level,
                "score":               float(latest_result.score) if latest_result.score is not None else None,
                "grade":               latest_result.grade,
                "progression_label":   latest_result.progression_label,
                "progression_type":    latest_result.progression_type,
                "current_stage_label": latest_result.current_stage_label,
                "scanned_at":          latest_result.created_at.isoformat(),
            }
        return d
