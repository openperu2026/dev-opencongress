from app.routes.api.health import health_blp
from app.routes.api.bills import bills_blp
from app.routes.api.congress import congress_blp
from flask_smorest import Api


def register_api(api: Api):
    """Register API v1 blueprints."""
    api.register_blueprint(health_blp)
    api.register_blueprint(bills_blp)
    api.register_blueprint(congress_blp)
