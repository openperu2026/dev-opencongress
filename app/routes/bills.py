from hashlib import sha1
from math import ceil
from types import SimpleNamespace
from datetime import datetime
from flask import (
    Blueprint,
    current_app,
    make_response,
    render_template,
    request,
    session,
    url_for,
)
from sqlalchemy import func, select, desc
from app.diff_render import RENDERER_VERSION, render_payload_html
from backend.database.crud.pipeline_bills import get_billtext_for_step
from backend.database.models import (
    Bill,
    BillDifference,
    BillStep,
    BillCongresistas,
    Congresista,
    BillOrganization,
)
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
    page = request.args.get("page", 1, type=int)
    page = page if page and page > 0 else 1
    per_page = 50
    max_search_results = 500
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
    total_count = 0
    total_count_display = None
    results_start = 0
    results_end = 0
    pagination_pages = []
    if author_q or title_q:
        with SessionProcessed() as db:
            latest_bill_dates = (
                select(
                    BillOrganization.bill_id,
                    func.max(BillOrganization.presentation_date).label(
                        "latest_presentation_date"
                    ),
                )
                .group_by(BillOrganization.bill_id)
                .subquery()
            )

            stmt = (
                select(
                    Bill.id.label("id"),
                    Bill.title.label("title"),
                    Congresista.full_name.label("author_name"),
                    latest_bill_dates.c.latest_presentation_date.label(
                        "presentation_date"
                    ),
                )
                .join(Congresista, Bill.author_id == Congresista.id, isouter=True)
                .outerjoin(latest_bill_dates, latest_bill_dates.c.bill_id == Bill.id)
                .where(*filters)
            )

            count_stmt = select(func.count()).select_from(
                stmt.order_by(None).limit(max_search_results + 1).subquery()
            )
            total_count = db.execute(count_stmt).scalar_one()
            total_count_display = (
                f"{max_search_results}+"
                if total_count > max_search_results
                else str(total_count)
            )

            visible_total = min(total_count, max_search_results)
            total_pages = ceil(visible_total / per_page) if visible_total else 0
            if total_pages and page > total_pages:
                page = total_pages

            if total_pages:
                pagination_pages = [
                    SimpleNamespace(
                        number=page_number,
                        current=page_number == page,
                        url=url_for(
                            "bills.index",
                            title_q=title_q,
                            author_q=author_q,
                            status=status,
                            page=page_number,
                        ),
                    )
                    for page_number in range(1, total_pages + 1)
                ]

            result_stmt = (
                stmt.order_by(
                    latest_bill_dates.c.latest_presentation_date.desc(),
                    Bill.title.asc(),
                    Bill.id.asc(),
                )
                .offset((page - 1) * per_page)
                .limit(per_page)
            )

            rows = db.execute(result_stmt).mappings().all()
            if rows and author_q and not author_id_query:
                author_display = author_q
            if rows:
                results_start = (page - 1) * per_page + 1
                results_end = results_start + len(rows) - 1

            bills = [SimpleNamespace(**row) for row in rows]

    prev_page_url = None
    next_page_url = None
    if total_count_display is not None and pagination_pages:
        if page > 1:
            prev_page_url = url_for(
                "bills.index",
                title_q=title_q,
                author_q=author_q,
                status=status,
                page=page - 1,
            )
        if page < len(pagination_pages):
            next_page_url = url_for(
                "bills.index",
                title_q=title_q,
                author_q=author_q,
                status=status,
                page=page + 1,
            )

    return render_template(
        "bills/search.html",
        title_q=title_q,
        author_q=author_q,
        author_display=author_display,
        bills=bills,
        radio_status=status,
        page=page,
        per_page=per_page,
        total_count_display=total_count_display,
        results_start=results_start,
        results_end=results_end,
        pagination_pages=pagination_pages,
        prev_page_url=prev_page_url,
        next_page_url=next_page_url,
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

        author_table = None
        if bill.author_id:
            author_table = db.get(Congresista, bill.author_id)
        else:
            stmt = select(BillCongresistas.person_id).where(
                BillCongresistas.bill_id == bill_id,
                BillCongresistas.role_type == "Autor",
            )
            author_id = db.execute(stmt).first()
            if author_id:
                author_table = db.get(Congresista, author_id)

        # Presentation date
        presentation_date = db.scalar(
            select(BillStep.step_date).where(
                BillStep.bill_id == bill_id, BillStep.step_type == "Presentado"
            )
        )

        bill_status = _("Not approved")
        if bill.bill_approved:
            bill_status = _("Approved")

            stmt = (
                select(BillStep.step_date)
                .where(BillStep.bill_id == bill_id, BillStep.step_type == "Votación")
                .order_by(desc(BillStep.step_date))
                .limit(1)
            )
            approval_date = db.scalar(stmt)
            days_since_presentation = (approval_date - presentation_date).days
        else:
            today = datetime.now().date()
            days_since_presentation = (today - presentation_date).days

        return render_template(
            "bills/detail.html",
            bill=bill,
            latest_step=latest_step,
            all_steps=all_steps,
            diff_types=diff_types,
            bill_status=bill_status,
            author=author_table,
            presentation_date=presentation_date,
            days_since_presentation=days_since_presentation,
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
        locale = session.get("lang") or request.args.get("lang") or "en"
        etag = (
            f"bd-{bill_id}-{step_id}-{locale}-{difference_type}-{content_hash}"
            f"-r{RENDERER_VERSION}"
        )

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
