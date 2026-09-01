from flask.views import MethodView
from flask_smorest import Blueprint

from app.routes.api.auth import require_api_key
from app.routes.api.schemas import (
    CongressMemberListQuerySchema,
    CongressMemberListResponseSchema,
)
from app.routes.processed_session import SessionProcessed
from backend.services.congress import search_congress_members


congress_blp = Blueprint(
    "api-congress",
    __name__,
    url_prefix="/api/v1",
    description="Congress member API endpoints",
)


@congress_blp.route("/congress-members")
class CongressMembersResource(MethodView):
    @congress_blp.arguments(CongressMemberListQuerySchema, location="query")
    @congress_blp.response(200, CongressMemberListResponseSchema)
    @require_api_key
    def get(self, args):
        with SessionProcessed() as db:
            return search_congress_members(db, args)
