from flask.views import MethodView
from flask_smorest import Blueprint

from app.routes.api.auth import require_api_key
from app.routes.api.errors import abort_not_found
from app.routes.api.schemas import (
    BillDetailResponseSchema,
    BillListQuerySchema,
    BillListResponseSchema,
)
from app.routes.processed_session import SessionProcessed
from backend.services.bills import (
    get_bill_detail_by_period_and_pl,
    search_bills,
)


bills_blp = Blueprint(
    "api-bills",
    __name__,
    url_prefix="/api/v1",
    description="Bill API endpoints",
)


@bills_blp.route("/bills")
class BillsResource(MethodView):
    @bills_blp.arguments(BillListQuerySchema, location="query")
    @bills_blp.response(200, BillListResponseSchema)
    @require_api_key
    def get(self, args):
        with SessionProcessed() as db:
            return search_bills(db, args)


@bills_blp.route("/bills/pl/<int:period>/<int:pl_number>")
class BillDetailByPlResource(MethodView):
    @bills_blp.response(200, BillDetailResponseSchema)
    @require_api_key
    def get(self, period, pl_number):
        with SessionProcessed() as db:
            bill_detail = get_bill_detail_by_period_and_pl(db, period, pl_number)
            if bill_detail is None:
                abort_not_found("Bill not found")
            return bill_detail
