import uuid

from app.extensions import db
from app.models.plan import Plan


def get_all_active() -> list[Plan]:
    return db.session.execute(
        db.select(Plan)
        .where(Plan.is_active == True)  # noqa: E712
        .order_by(Plan.monthly_price)
    ).scalars().all()


def get_by_id(plan_id) -> Plan | None:
    try:
        pid = uuid.UUID(str(plan_id))
    except (ValueError, AttributeError):
        return None
    return db.session.get(Plan, pid)


def get_by_name(name: str) -> Plan | None:
    return db.session.execute(
        db.select(Plan).where(Plan.name == name)
    ).scalar_one_or_none()
