from app.extensions import db
from app.models.plan_tool_map import PlanToolMap


def get_tool_ids_for_plan(plan_id) -> set:
    rows = db.session.execute(
        db.select(PlanToolMap.tool_id).where(PlanToolMap.plan_id == plan_id)
    ).scalars().all()
    return {str(tid) for tid in rows}


def get_maps_for_plan(plan_id) -> list[PlanToolMap]:
    return db.session.execute(
        db.select(PlanToolMap).where(PlanToolMap.plan_id == plan_id)
    ).scalars().all()


def exists(plan_id, tool_id) -> bool:
    return db.session.execute(
        db.select(PlanToolMap).where(
            PlanToolMap.plan_id == plan_id,
            PlanToolMap.tool_id == tool_id,
        )
    ).scalar_one_or_none() is not None
