from flask import Blueprint, render_template, request
from sqlalchemy import select
from backend.database.models import Bill
from .processed_session import SessionProcessed

bills_bp = Blueprint("bills", __name__, template_folder="../templates")


@bills_bp.route("/bills")
def index():
    q = request.args.get("q", "").strip()
    bills = []

    if q:
        with SessionProcessed() as db:
            stmt = select(Bill).where(Bill.title.ilike(f"%{q}%")).limit(50)
            bills = db.execute(stmt).scalars().all()

    return render_template("bills/search.html", q=q, bills=bills)


@bills_bp.route("/bills/<bill_id>")
def bill_detail(bill_id):
    with SessionProcessed() as db:
        bill = db.get(Bill, bill_id)
        if not bill:
            return "Not Found", 404
        return render_template("bills/detail.html", bill=bill)
