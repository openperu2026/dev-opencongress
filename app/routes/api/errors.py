from flask_smorest import abort


def abort_not_found(message: str = "Resource not found"):
    abort(
        404,
        message={
            "error": {
                "code": "not_found",
                "message": message,
            }
        },
    )


def abort_bad_request(message: str = "Invalid request"):
    abort(
        400,
        message={
            "error": {
                "code": "bad_request",
                "message": message,
            }
        },
    )
