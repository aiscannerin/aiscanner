import uuid

from app.extensions import db
from app.models.tool import Tool


def get_all_active() -> list[Tool]:
    return db.session.execute(
        db.select(Tool)
        .where(Tool.is_active == True)  # noqa: E712
        .order_by(Tool.name)
    ).scalars().all()


def get_by_slug(slug: str) -> Tool | None:
    return db.session.execute(
        db.select(Tool).where(Tool.slug == slug)
    ).scalar_one_or_none()


def get_by_id(tool_id) -> Tool | None:
    try:
        tid = uuid.UUID(str(tool_id))
    except (ValueError, AttributeError):
        return None
    return db.session.get(Tool, tid)
