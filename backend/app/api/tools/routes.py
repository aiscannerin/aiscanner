from flask import Blueprint, g

from app.middleware.auth_guard import require_auth
from app.services.tool_access_service import get_accessible_tools, has_tool_access
from app.utils.response import error, success

tools_bp = Blueprint("tools", __name__)


@tools_bp.get("/accessible")
@require_auth
def accessible_tools():
    result = get_accessible_tools(g.current_user.id)
    return success(
        data=result["tools"],
        meta={
            "current_plan": result["current_plan"],
            "subscription_status": result["subscription_status"],
            "expiry_date": result["expiry_date"],
        },
    )


@tools_bp.get("/test-access/<tool_slug>")
@require_auth
def test_tool_access(tool_slug):
    """
    Temporary development endpoint to verify tool-access middleware logic.
    Calls has_tool_access() directly so all 10 checks run.
    """
    result = has_tool_access(g.current_user.id, tool_slug)
    if not result["allowed"]:
        return error(
            result["reason"],
            403,
            error_code=result["error_code"],
        )
    from app.repositories import tool_repository
    tool = tool_repository.get_by_slug(tool_slug)
    return success(
        data={"tool": tool.to_dict(), "user": g.current_user.to_dict()},
        message=f"Access granted to '{tool_slug}'.",
    )
