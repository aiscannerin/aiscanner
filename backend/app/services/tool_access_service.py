from app.repositories import (
    plan_tool_repository,
    subscription_repository,
    tool_repository,
)


# ── Core helpers ─────────────────────────────────────────────────────────────────

def get_current_subscription(user_id):
    """Return the user's most recent ACTIVE subscription, or None."""
    return subscription_repository.get_active_subscription(user_id)


def subscription_is_valid(subscription) -> bool:
    """
    True when subscription is ACTIVE and either has no expiry (Free)
    or expiry_date is in the future.
    """
    if subscription is None:
        return False
    return subscription.is_active_and_valid


def has_tool_access(user_id, tool_slug: str) -> dict:
    """
    Check whether a user can access a specific tool.

    Returns:
        {"allowed": True}
        {"allowed": False, "reason": "<human message>", "error_code": "<MACHINE_CODE>"}
    """
    tool = tool_repository.get_by_slug(tool_slug)
    if not tool:
        return {"allowed": False, "reason": "Tool not found.", "error_code": "TOOL_NOT_FOUND"}
    if not tool.is_active:
        return {"allowed": False, "reason": "This tool is currently unavailable.", "error_code": "TOOL_INACTIVE"}

    sub = get_current_subscription(user_id)
    if not sub:
        return {
            "allowed": False,
            "reason": "No active subscription found.",
            "error_code": "SUBSCRIPTION_REQUIRED",
        }
    if not subscription_is_valid(sub):
        return {
            "allowed": False,
            "reason": "Your subscription has expired. Please renew to continue.",
            "error_code": "SUBSCRIPTION_EXPIRED",
        }

    if not plan_tool_repository.exists(sub.plan_id, tool.id):
        return {
            "allowed": False,
            "reason": f"Your {sub.plan.name} plan does not include access to this tool. Upgrade to unlock it.",
            "error_code": "TOOL_NOT_IN_PLAN",
        }

    return {"allowed": True}


def get_accessible_tools(user_id) -> dict:
    """
    Return all active tools annotated with has_access and context data.

    Shape per tool:
        {
            "id", "name", "slug", "description", "is_active",
            "has_access": bool,
            "locked_reason": str | None,
            "current_plan": str | None,
            "subscription_status": str | None,
            "expiry_date": str | None,
        }
    """
    tools = tool_repository.get_all_active()
    sub = get_current_subscription(user_id)

    plan_name = sub.plan.name if sub and sub.plan else None
    sub_status = sub.status if sub else None
    expiry_date = sub.expiry_date.isoformat() if sub and sub.expiry_date else None

    # Pre-fetch tool IDs allowed for this plan to avoid N+1 queries
    allowed_tool_ids: set = set()
    if sub and subscription_is_valid(sub):
        allowed_tool_ids = plan_tool_repository.get_tool_ids_for_plan(sub.plan_id)

    result = []
    for tool in tools:
        has_access = str(tool.id) in allowed_tool_ids
        locked_reason = None

        if not has_access:
            if not sub:
                locked_reason = "No active subscription found."
            elif not subscription_is_valid(sub):
                locked_reason = "Your subscription has expired. Please renew to continue."
            else:
                locked_reason = f"Your {plan_name} plan does not include this tool. Upgrade to unlock it."

        result.append({
            **tool.to_dict(),
            "has_access": has_access,
            "locked_reason": locked_reason,
            "current_plan": plan_name,
            "subscription_status": sub_status,
            "expiry_date": expiry_date,
        })

    return {
        "tools": result,
        "current_plan": plan_name,
        "subscription_status": sub_status,
        "expiry_date": expiry_date,
    }
