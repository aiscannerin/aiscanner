from functools import wraps

from flask import g
from flask_jwt_extended import get_jwt, get_jwt_identity, verify_jwt_in_request

from app.utils.response import error


def require_auth(f):
    """
    Decorator that:
    1. Validates the JWT in the Authorization header.
    2. Rejects password-reset tokens used as auth tokens.
    3. Loads the user from DB and attaches it to flask.g.current_user.
    4. Rejects inactive accounts.

    Any JWT validation failure is handled by Flask-JWT-Extended's
    registered error loaders (defined in app/__init__.py), which return
    properly structured JSON error responses automatically.
    """
    @wraps(f)
    def decorated(*args, **kwargs):
        verify_jwt_in_request()

        claims = get_jwt()
        if claims.get("token_purpose") == "password_reset":
            return error(
                "This token cannot be used for authentication.",
                401,
                error_code="TOKEN_INVALID",
            )

        user_id = get_jwt_identity()

        # Import inside function to prevent circular imports at module load time
        from app.repositories import user_repository

        user = user_repository.get_by_id(user_id)
        if not user:
            return error("User account not found.", 401, error_code="USER_NOT_FOUND")
        if not user.is_active:
            return error(
                "Your account has been deactivated.",
                403,
                error_code="ACCOUNT_INACTIVE",
            )

        g.current_user = user
        return f(*args, **kwargs)

    return decorated
