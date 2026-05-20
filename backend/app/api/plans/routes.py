from flask import Blueprint

from app.repositories import plan_repository, plan_tool_repository
from app.utils.response import error, success

plans_bp = Blueprint("plans", __name__)


@plans_bp.get("")
def list_plans():
    plans = plan_repository.get_all_active()
    return success(data=[_plan_with_tools(p) for p in plans])


@plans_bp.get("/<plan_id>")
def get_plan(plan_id):
    plan = plan_repository.get_by_id(plan_id)
    if not plan or not plan.is_active:
        return error("Plan not found.", 404, error_code="PLAN_NOT_FOUND")
    return success(data=_plan_with_tools(plan))


# ── Internal ──────────────────────────────────────────────────────────────────────

def _plan_with_tools(plan) -> dict:
    maps = plan_tool_repository.get_maps_for_plan(plan.id)
    tools = [m.tool.to_dict() for m in maps if m.tool and m.tool.is_active]
    return {
        **plan.to_dict(),
        "tools": tools,
    }
