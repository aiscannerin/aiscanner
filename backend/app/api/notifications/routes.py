"""
/api/notifications — in-app scanner notifications

GET  /api/notifications/recent          last 50 notifications for current user
POST /api/notifications/<id>/read       mark one as read
POST /api/notifications/read-all        mark all unread as read
"""
import uuid as _uuid

from flask import g

from app.api.notifications import notifications_bp
from app.extensions import db
from app.middleware.auth_guard import require_auth
from app.models.scanner_notification import ScannerNotification
from app.utils.response import error, success


# ── Recent ────────────────────────────────────────────────────────────────────

@notifications_bp.get("/recent")
@require_auth
def recent():
    notifs = db.session.execute(
        db.select(ScannerNotification)
        .where(ScannerNotification.user_id == g.current_user.id)
        .order_by(ScannerNotification.created_at.desc())
        .limit(50)
    ).scalars().all()

    unread_count = sum(1 for n in notifs if not n.is_read)

    return success(
        data=[n.to_dict() for n in notifs],
        meta={"unread_count": unread_count, "total": len(notifs)},
    )


# ── Mark one read ─────────────────────────────────────────────────────────────

@notifications_bp.post("/<notification_id>/read")
@require_auth
def mark_read(notification_id):
    try:
        nid = _uuid.UUID(str(notification_id))
    except (ValueError, AttributeError):
        return error("Invalid notification ID.", 400)

    notif = db.session.get(ScannerNotification, nid)
    if not notif:
        return error("Notification not found.", 404, error_code="NOTIF_NOT_FOUND")
    if notif.user_id and str(notif.user_id) != str(g.current_user.id):
        return error("This notification does not belong to your account.", 403,
                     error_code="NOTIF_OWNERSHIP_MISMATCH")

    notif.is_read = True
    db.session.commit()
    return success(message="Notification marked as read.", data=notif.to_dict())


# ── Mark all read ─────────────────────────────────────────────────────────────

@notifications_bp.post("/read-all")
@require_auth
def mark_all_read():
    updated = db.session.execute(
        db.update(ScannerNotification)
        .where(ScannerNotification.user_id == g.current_user.id)
        .where(ScannerNotification.is_read == False)   # noqa: E712
        .values(is_read=True)
        .returning(ScannerNotification.id)
    ).fetchall()
    db.session.commit()

    return success(
        message=f"{len(updated)} notification(s) marked as read.",
        meta={"marked_count": len(updated)},
    )
