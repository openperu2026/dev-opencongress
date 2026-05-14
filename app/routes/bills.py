import json
from hashlib import sha1

from flask import Blueprint, current_app, make_response, render_template, request
from sqlalchemy import select
from app.diff_render import RENDERER_VERSION, render_payload_html
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

        # ETag from every input the renderer (and the page) actually depends on.
        # When any of these change, the ETag changes and the client refetches.
        content_hash = (
            sha1(diff.difference_content.encode("utf-8")).hexdigest()[:12]
            if diff and diff.difference_content
            else "none"
        )
        difference_type = diff.difference_type if diff else "unavailable"
        etag = f"bd-{step_id}-{difference_type}-{content_hash}-r{RENDERER_VERSION}"

        if request.if_none_match.contains(etag):
            return "", 304

        # Render the diff payload at request time.  Both parse and render
        # are wrapped: a malformed/truncated row or a renderer bug must not
        # take the page down — the template falls back to the
        # "no difference data available" branch.
        text_html = None
        if diff and diff.difference_content:
            try:
                parsed = json.loads(diff.difference_content)
            except (ValueError, TypeError):
                current_app.logger.exception(
                    "Failed to parse difference_content for step %s", step_id
                )
                parsed = None
            if isinstance(parsed, dict):
                try:
                    text_html = render_payload_html(parsed)
                except Exception:
                    current_app.logger.exception("Renderer failed for step %s", step_id)
                    text_html = None

        resp = make_response(
            render_template(
                "bills/difference.html",
                bill=bill,
                step=step,
                difference_type=difference_type,
                old_version_text=old_text,
                new_version_text=new_text,
                text_html=text_html,
            )
        )
        resp.set_etag(etag)
        resp.headers["Cache-Control"] = (
            "public, max-age=300, stale-while-revalidate=86400"
        )
        return resp
