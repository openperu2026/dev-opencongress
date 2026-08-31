from functools import wraps
from hmac import compare_digest

from flask import request
from flask_smorest import abort

from backend.config import settings


def require_api_key(fn):
    """Require a configured Bearer API key when API auth is enabled."""

    @wraps(fn)
    def wrapper(*args, **kwargs):
        if not settings.API_AUTH_ENABLED:
            return fn(*args, **kwargs)

        if not settings.API_KEY:
            abort(
                500,
                message={
                    "error": {
                        "code": "api_key_not_configured",
                        "message": "API auth is enabled but no API key is configured",
                    }
                },
            )

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

        api_key = auth_header.removeprefix("Bearer ").strip()
        if not compare_digest(api_key, settings.API_KEY):
            abort(
                403,
                message={
                    "error": {
                        "code": "invalid_api_key",
                        "message": "Invalid API key",
                    }
                },
            )

        return fn(*args, **kwargs)

    return wrapper
