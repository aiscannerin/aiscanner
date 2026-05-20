from functools import wraps

from flask import g
from flask_jwt_extended import get_jwt, get_jwt_identity, verify_jwt_in_request

from app.utils.response import error


def tool_access_required(tool_slug: str):
    """
    Decorator factory that enforces tool-level access control.

    Checks (in order):
        1. JWT present and valid            → 401 TOKEN_MISSING / TOKEN_INVALID
        2. Token is not a password-reset    → 401 TOKEN_INVALID
        3. User exists in DB                → 401 USER_NOT_FOUND
        4. user.is_active                   → 403 ACCOUNT_INACTIVE
        5. user.email_verified              → 403 EMAIL_NOT_VERIFIED
        6. Tool exists by slug              → 404 TOOL_NOT_FOUND
        7. tool.is_active                   → 403 TOOL_INACTIVE
        8. User has active subscription     → 403 SUBSCRIPTION_REQUIRED
        9. Subscription not expired         → 403 SUBSCRIPTION_EXPIRED
       10. Plan includes the tool           → 403 TOOL_NOT_IN_PLAN

    On success: g.current_user and g.current_tool are set.
    """
    def decorator(f):
        @wraps(f)
        def decorated(*args, **kwargs):
            # ── 1. JWT validation (Flask-JWT-Extended handles 401 on failure) ────
            verify_jwt_in_request()

            # ── 2. Reject password-reset tokens ─────────────────────────────────
            claims = get_jwt()
            if claims.get("token_purpose") == "password_reset":
                return error(
                    "This token cannot be used for authentication.",
                    401,
                    error_code="TOKEN_INVALID",
                )

            user_id = get_jwt_identity()

            # Deferred imports to prevent circular dependency at module load
            from app.repositories import plan_tool_repository, tool_repository, user_repository
            from app.services.tool_access_service import get_current_subscription, subscription_is_valid

            # ── 3. User exists ───────────────────────────────────────────────────
            user = user_repository.get_by_id(user_id)
            if not user:
                return error("User account not found.", 401, error_code="USER_NOT_FOUND")

            # ── 4. Account active ────────────────────────────────────────────────
            if not user.is_active:
                return error(
                    "Your account has been deactivated.",
                    403,
                    error_code="ACCOUNT_INACTIVE",
                )

            # ── 5. Email verified ────────────────────────────────────────────────
            if not user.email_verified:
                return error(
                    "Please verify your email before using tools.",
                    403,
                    error_code="EMAIL_NOT_VERIFIED",
                )

            # ── 6. Tool exists ───────────────────────────────────────────────────
            tool = tool_repository.get_by_slug(tool_slug)
            if not tool:
                return error(
                    f"Tool '{tool_slug}' not found.",
                    404,
                    error_code="TOOL_NOT_FOUND",
                )

            # ── 7. Tool active ───────────────────────────────────────────────────
            if not tool.is_active:
                return error(
                    "This tool is currently unavailable.",
                    403,
                    error_code="TOOL_INACTIVE",
                )

            # ── 8. Active subscription ───────────────────────────────────────────
            sub = get_current_subscription(user.id)
            if not sub:
                return error(
                    "An active subscription is required to use this tool.",
                    403,
                    error_code="SUBSCRIPTION_REQUIRED",
                )

            # ── 9. Subscription not expired ──────────────────────────────────────
            if not subscription_is_valid(sub):
                return error(
                    "Your subscription has expired. Please renew to continue.",
                    403,
                    error_code="SUBSCRIPTION_EXPIRED",
                )

            # ── 10. Tool in plan ─────────────────────────────────────────────────
            if not plan_tool_repository.exists(sub.plan_id, tool.id):
                return error(
                    f"Your {sub.plan.name} plan does not include access to this tool. "
                    "Upgrade your plan to unlock it.",
                    403,
                    error_code="TOOL_NOT_IN_PLAN",
                )

            g.current_user = user
            g.current_tool = tool
            return f(*args, **kwargs)

        return decorated
    return decorator
