import json

from flask import Blueprint, render_template, request
from sqlalchemy import select
from backend.database.models import Bill, BillStep, BillDifference, BillText
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

        stmt = (
            select(BillStep)
            .where(BillStep.bill_id == bill_id)
            .order_by(BillStep.step_date.desc())
        )
        all_steps = db.execute(stmt).scalars().all()

        latest_step = all_steps[0] if all_steps else None

        return render_template(
            "bills/detail.html", bill=bill, latest_step=latest_step, all_steps=all_steps
        )


@bills_bp.route("/bills/<bill_id>/difference/<int:step_id>")
def bill_difference(bill_id, step_id):
    with SessionProcessed() as db:
        bill = db.get(Bill, bill_id)
        if not bill:
            return "Not Found", 404

        step = db.get(BillStep, step_id)
        if not step or step.bill_id != bill_id:
            return "Not Found", 404

        diff = db.get(BillDifference, step_id)

        old_text = new_text = None
        if diff:
            if diff.new_archivo_id:
                new_bt = db.get(BillText, diff.new_archivo_id)
                new_text = new_bt.text if new_bt else None
            if diff.old_archivo_id:
                old_bt = db.get(BillText, diff.old_archivo_id)
                old_text = old_bt.text if old_bt else None

        difference_content = (
            json.loads(diff.difference_content)
            if (diff and diff.difference_content)
            else []
        )

        return render_template(
            "bills/difference.html",
            bill=bill,
            step=step,
            difference_type=diff.difference_type if diff else "unavailable",
            old_version_text=old_text,
            new_version_text=new_text,
            difference_content=difference_content,
        )
