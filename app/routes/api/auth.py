from functools import wraps

from flask import request
from flask_smorest import abort

from backend.config import settings


def require_api_key(fn):
    """Placeholder API-key guard.

    API auth is disabled by default. When enabled later, this decorator is the
    single place where API-key extraction and validation should live.
    """

    @wraps(fn)
    def wrapper(*args, **kwargs):
        if not settings.API_AUTH_ENABLED:
            return fn(*args, **kwargs)

        auth_header = request.headers.get("Authorization", "")
        if not auth_header.startswith("Bearer "):
            abort(
                401,
                message={
                    "error": {
                        "code": "api_key_required",
                        "message": "Missing API key",
                    }
                },
            )

        abort(
            501,
            message={
                "error": {
                    "code": "api_key_validation_not_implemented",
                    "message": "API key validation is not implemented yet",
                }
            },
        )

    return wrapper
