from flask import Blueprint, render_template, request
from sqlalchemy import select
from backend.database.models import Bill, BillStep
from .processed_session import SessionProcessed
import json
import os
import sqlite3
from .generate_seats import generate_seats
from .build_bancada_bars import build_bancada_bars

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

        all_steps, latest_step = extract_steps(db, bill_id)

        return render_template(
            "bills/detail.html", bill=bill, latest_step=latest_step, all_steps=all_steps
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
