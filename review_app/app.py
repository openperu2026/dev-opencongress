"""
Standalone local-only Flask app for reviewing/correcting vote and
attendance records against their source PDF. Deliberately not wired into
`docker-compose`'s public `open-congress-frontend` service -- see the
approved plan at `~/.claude/plans/project-vote-buzzing-pillow.md` for why.
"""

import os

from flask import Flask

from review_app.routes import review_bp


def _assert_local_only(host: str) -> None:
    """
    The entire reason this is a separate app is that it has DB write
    access and no auth -- that safety currently rests entirely on Flask's
    default 127.0.0.1 bind. Refuse to start bound to anything else unless
    explicitly overridden.
    """
    if host not in ("127.0.0.1", "localhost", "::1") and not os.environ.get(
        "REVIEW_APP_ALLOW_REMOTE"
    ):
        raise SystemExit(
            f"Refusing to bind review_app to {host!r} -- this tool has no "
            "auth and writes production data. Set REVIEW_APP_ALLOW_REMOTE=1 "
            "to override."
        )


def create_app() -> Flask:
    app = Flask(__name__)
    app.register_blueprint(review_bp)
    app.secret_key = os.environ.get("REVIEW_APP_SECRET_KEY", "review-app-local-only")
    return app


def main() -> None:
    host = os.environ.get("REVIEW_APP_HOST", "127.0.0.1")
    _assert_local_only(host)
    app = create_app()
    app.run(host=host, port=int(os.environ.get("REVIEW_APP_PORT", "5050")), debug=True)


if __name__ == "__main__":
    main()
