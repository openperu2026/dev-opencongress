from hashlib import sha1
from types import SimpleNamespace
from flask import Blueprint, current_app, make_response, render_template, request
from sqlalchemy import select
from app.diff_render import RENDERER_VERSION, render_payload_html
from backend.database.crud.pipeline_bills import get_billtext_for_step
from backend.database.models import Bill, BillDifference, BillStep, Congresista
from .processed_session import SessionProcessed
import json
import os
import sqlite3
from .generate_seats import generate_seats
from .build_bancada_bars import build_bancada_bars
from flask_babel import gettext as _

bills_bp = Blueprint("bills", __name__, template_folder="../templates")


def load_voter_bancada_dict():
    """Load voter-bancada mapping from DB into dict"""
    db_path = os.path.join(
        os.path.dirname(__file__), "..", "mock_data", "example_voter_bancada.db"
    )
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    cursor.execute("SELECT voter, bancada FROM voter_bancada")
    voter_bancada_map = {row[0]: row[1] for row in cursor.fetchall()}
    conn.close()
    return voter_bancada_map


@bills_bp.route("/bills")
def index():
    title_q = request.args.get("title_q", "").strip()
    author_q = request.args.get("author_q", "").strip()
    status = request.args.get("status", "all").strip()
    _allowed_status = {"all", "approved", "not-approved"}
    if status not in _allowed_status:
        status = "all"
    filters = []
    author_display = None
    author_id_query = author_q.isdigit()

    if title_q:
        filters.append(Bill.title.ilike(f"%{title_q}%"))

    if author_q:
        if author_id_query:
            # filter by numeric author id
            try:
                author_id_int = int(author_q)
            except ValueError:
                author_id_int = None

            if author_id_int is not None:
                filters.append(Bill.author_id == author_id_int)
                with SessionProcessed() as db:
                    author_row = db.get(Congresista, author_id_int)
                    author_display = author_row.full_name if author_row else None
        else:
            filters.append(Congresista.full_name.ilike(f"%{author_q}%"))

    if status == "approved":
        filters.append(Bill.bill_approved.is_(True))
    elif status == "not-approved":
        filters.append(Bill.bill_approved.is_(False))

    bills = []
    if author_q or title_q:
        with SessionProcessed() as db:
            stmt = (
                select(Bill.id, Bill.title, Congresista.full_name.label("author_name"))
                .join(Congresista, Bill.author_id == Congresista.id, isouter=True)
                .where(*filters)
                .limit(50)
            )

            rows = db.execute(stmt).mappings().all()
            if rows and author_q and not author_id_query:
                author_display = author_q

            # rows are flat mappings with keys: id, title, author_name
            bills = [SimpleNamespace(**row) for row in rows]

    return render_template(
        "bills/search.html",
        title_q=title_q,
        author_q=author_q,
        author_display=author_display,
        bills=bills,
        radio_status=status,
    )


@bills_bp.route("/bills/<bill_id>")
def bill_detail(bill_id):
    with SessionProcessed() as db:
        bill = db.get(Bill, bill_id)
        if not bill:
            return "Not Found", 404

        all_steps, latest_step = extract_steps(db, bill_id)

        # Only the types that actually carry comparable content; the others
        # (no_change, unavailable, first_version, missing row) shouldn't get
        # a "View changes" link.
        diff_types = dict(
            db.execute(
                select(BillDifference.step_id, BillDifference.difference_type).where(
                    BillDifference.bill_id == bill_id
                )
            ).all()
        )
        bill_status = _("Not approved")
        if bill.bill_approved:
            bill_status = _("Approved")

        author = ""
        if bill.author_id:
            author_table = db.get(Congresista, bill.author_id)
            author = author_table.full_name

        return render_template(
            "bills/detail.html",
            bill=bill,
            latest_step=latest_step,
            all_steps=all_steps,
            diff_types=diff_types,
            bill_status=bill_status,
            author=author,
        )


@bills_bp.route("/bills/<bill_id>/mock_votes")
def mock_votes(bill_id):
    with SessionProcessed() as db:
        bill = db.get(Bill, bill_id)
        if not bill:
            return "Not Found", 404

        _, latest_step = extract_steps(db, bill_id)

        mock_data_path = os.path.join(
            os.path.dirname(__file__), "..", "mock_data", "example_vote_event.json"
        )
        vote_counts = {"yes": 0, "no": 0, "abstain": 0}

        with open(mock_data_path, "r", encoding="utf-8") as f:
            vote_event = json.load(f)

        for count in vote_event.get("counts", []):
            option = count.get("option", "").lower()
            value = count.get("value", 0)

            vote_counts[option] = value

        # Build grouped name lists
        votes = vote_event.get("votes", [])

        groups = {"yes": [], "no": [], "abstain": []}
        for v in votes:
            opt = v.get("option", "").lower()
            voter = v.get("voter")
            name = voter.get("name", "")
            if opt in groups:
                groups[opt].append(name)

        # Generate seat positions and attributes server-side
        seats = generate_seats(vote_counts, groups)

        # Load voter-bancada mapping and aggregate by bancada
        voter_bancada_map = load_voter_bancada_dict()
        bancada_votes = {}

        # reparsing the votes list
        for vote_type, names in groups.items():
            for name in names:
                bancada = voter_bancada_map.get(name, "unknown")
                if bancada not in bancada_votes:
                    bancada_votes[bancada] = {
                        "yes": 0,
                        "no": 0,
                        "abstain": 0,
                        "total": 0,
                    }
                if vote_type in bancada_votes[bancada]:
                    bancada_votes[bancada][vote_type] += 1
                    bancada_votes[bancada]["total"] += 1

        bancada_rows, bancada_chart_height = build_bancada_bars(bancada_votes)

        return render_template(
            "bills/mock_votes.html",
            bill=bill,
            latest_step=latest_step,
            vote_counts=vote_counts,
            seats=seats,
            bancada_rows=bancada_rows,
            bancada_chart_height=bancada_chart_height,
        )


def extract_steps(db, bill_id):
    stmt = (
        select(BillStep)
        .where(BillStep.bill_id == bill_id)
        .order_by(BillStep.step_date.desc())
    )
    all_steps = db.execute(stmt).scalars().all()
    latest_step = all_steps[0] if all_steps else None

    return all_steps, latest_step


@bills_bp.route("/bills/<bill_id>/difference/<int:step_id>")
def bill_difference(bill_id, step_id):
    with SessionProcessed() as db:
        bill = db.get(Bill, bill_id)
        if not bill:
            return "Not Found", 404

        step = db.get(BillStep, (bill_id, step_id))
        if not step:
            return "Not Found", 404

        diff = db.get(BillDifference, (bill_id, step_id))

        new_bt = get_billtext_for_step(db, bill_id, step_id)
        new_text = new_bt.text if new_bt else None
        old_text = None
        prev_step = None
        if diff and diff.prev_step_id is not None:
            old_bt = get_billtext_for_step(db, bill_id, diff.prev_step_id)
            old_text = old_bt.text if old_bt else None
            prev_step = db.get(BillStep, (bill_id, diff.prev_step_id))

        # ETag covers every input the renderer (and the page) depends on so
        # any change forces a client refetch.
        content_hash = (
            sha1(diff.difference_content.encode("utf-8")).hexdigest()[:12]
            if diff and diff.difference_content
            else "none"
        )
        # No row means the diff stage hasn't reached this step yet — distinct
        # from ``unavailable``, which means we tried and the new text is
        # missing. The template's final ``else`` branch handles ``None``.
        difference_type = diff.difference_type if diff else None
        etag = f"bd-{bill_id}-{step_id}-{difference_type}-{content_hash}-r{RENDERER_VERSION}"

        if request.if_none_match.contains(etag):
            return "", 304

        # Both parse and render are guarded: a malformed row or a renderer
        # bug must not take the page down — the template falls back to the
        # "no difference data available" branch.
        text_html = None
        if diff and diff.difference_content:
            try:
                parsed = json.loads(diff.difference_content)
            except (ValueError, TypeError):
                current_app.logger.exception(
                    "Failed to parse difference_content for bill %s step %s",
                    bill_id,
                    step_id,
                )
                parsed = None
            if isinstance(parsed, dict):
                try:
                    text_html = render_payload_html(parsed)
                except Exception:
                    current_app.logger.exception(
                        "Renderer failed for bill %s step %s", bill_id, step_id
                    )
                    text_html = None

        resp = make_response(
            render_template(
                "bills/difference.html",
                bill=bill,
                step=step,
                prev_step=prev_step,
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
