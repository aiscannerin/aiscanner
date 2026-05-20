from datetime import datetime, timezone

from app.repositories import plan_tool_repository, subscription_repository


def get_current_subscription_detail(user_id) -> dict:
    """
    Build the full subscription detail payload for GET /api/subscriptions/current.
    Returns a plain dict ready to be passed to success().
    """
    sub = subscription_repository.get_active_subscription(user_id)

    if not sub:
        return {
            "has_subscription": False,
            "plan": None,
            "billing_cycle": None,
            "status": None,
            "start_date": None,
            "expiry_date": None,
            "days_remaining": None,
            "accessible_tools": [],
        }

    days_remaining = None
    if sub.expiry_date is not None:
        delta = sub.expiry_date - datetime.now(timezone.utc)
        days_remaining = max(0, delta.days)

    # Accessible tools for current plan (only active tools)
    tool_maps = plan_tool_repository.get_maps_for_plan(sub.plan_id)
    accessible_tools = [
        {"id": str(m.tool.id), "name": m.tool.name, "slug": m.tool.slug}
        for m in tool_maps
        if m.tool and m.tool.is_active
    ]

    return {
        "has_subscription": True,
        "plan": sub.plan.to_dict() if sub.plan else None,
        "billing_cycle": sub.billing_cycle,
        "status": sub.status,
        "start_date": sub.start_date.isoformat(),
        "expiry_date": sub.expiry_date.isoformat() if sub.expiry_date else None,
        "days_remaining": days_remaining,
        "accessible_tools": accessible_tools,
    }
