from flask.views import MethodView
from flask_smorest import Blueprint

from backend.config import settings
from app.routes.api.schemas import HealthResponseSchema


health_blp = Blueprint(
    "api-health",
    __name__,
    url_prefix="/api/v1",
    description="API health checks",
)


@health_blp.route("/health")
class HealthResource(MethodView):
    @health_blp.response(200, HealthResponseSchema)
    def get(self):
        return {
            "status": "ok",
            "version": settings.API_VERSION,
        }
