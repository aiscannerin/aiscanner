from flask import jsonify


def success(data=None, message="Success", status_code=200, meta=None):
    """
    Standard success envelope.

    Shape:
        { "success": true, "message": "...", "data": {...}, "meta": {...} }
    """
    payload = {
        "success": True,
        "message": message,
    }
    if data is not None:
        payload["data"] = data
    if meta is not None:
        payload["meta"] = meta
    return jsonify(payload), status_code


def error(message="An error occurred", status_code=400, errors=None, error_code=None):
    """
    Standard error envelope.

    Shape:
        { "success": false, "message": "...", "error_code": "...", "errors": [...] }

    error_code: machine-readable string e.g. "SUBSCRIPTION_EXPIRED", "EMAIL_NOT_VERIFIED"
    errors:     list of field-level validation errors [{"field": "email", "message": "..."}]
    """
    payload = {
        "success": False,
        "message": message,
    }
    if error_code:
        payload["error_code"] = error_code
    if errors:
        payload["errors"] = errors
    return jsonify(payload), status_code


def paginated(items, total, page, per_page, message="Success"):
    """
    Success envelope with pagination meta.
    """
    return success(
        data=items,
        message=message,
        meta={
            "total": total,
            "page": page,
            "per_page": per_page,
            "total_pages": (total + per_page - 1) // per_page,
        },
    )
