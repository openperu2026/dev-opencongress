from __future__ import annotations

from datetime import date

import boto3
from flask import (
    Blueprint,
    current_app,
    flash,
    make_response,
    redirect,
    render_template,
    request,
    session,
    url_for,
)

from backend import AttendanceStatus, VoteOption
from backend.config import settings
from backend.database import models as db_models
from backend.database.crud import review as crud_review
from backend.database.session import SessionLocal

review_bp = Blueprint(
    "review", __name__, template_folder="templates", static_folder="static"
)

_GATE_EXEMPT_ENDPOINTS = {"review.set_reviewer", "review.static"}


@review_bp.before_request
def _require_reviewer_name():
    if request.endpoint in _GATE_EXEMPT_ENDPOINTS:
        return None
    if not session.get("reviewer_name"):
        return render_template("set_reviewer.html", next_url=request.url)
    return None


def _parse_date(value: str | None) -> date | None:
    if not value:
        return None
    try:
        return date.fromisoformat(value)
    except ValueError:
        return None


def _parse_target_id(key: str, prefix: str) -> int | None:
    try:
        return int(key[len(prefix) :])
    except ValueError:
        return None


@review_bp.route("/")
def index():
    return redirect(url_for("review.search"))


@review_bp.route("/review")
def search():
    q = request.args.get("q") or None
    date_from = _parse_date(request.args.get("date_from"))
    date_to = _parse_date(request.args.get("date_to"))
    org_id = request.args.get("org_id", type=int)
    page = max(request.args.get("page", 1, type=int) or 1, 1)
    limit = 50
    offset = (page - 1) * limit

    with SessionLocal() as db:
        events = crud_review.search_review_queue(
            db,
            q=q,
            date_from=date_from,
            date_to=date_to,
            org_id=org_id,
            limit=limit,
            offset=offset,
        )

    event_ids_csv = ",".join(e.vote_event_id for e in events)
    return render_template(
        "search.html",
        events=events,
        q=q or "",
        date_from=request.args.get("date_from", ""),
        date_to=request.args.get("date_to", ""),
        org_id=request.args.get("org_id", ""),
        page=page,
        event_ids_csv=event_ids_csv,
    )


@review_bp.route("/review/<vote_event_id>")
def detail(vote_event_id):
    with SessionLocal() as db:
        event = db.get(db_models.VoteEvent, vote_event_id)
        if event is None:
            return "Not Found", 404

        rows = crud_review.get_review_rows(db, vote_event_id)
        doc_result = crud_review.find_document_for_vote_event(db, vote_event_id)
        summary = crud_review.summarize_votes(rows)
        existing_ids = {r.congresista_id for r in rows}
        addable_congresistas = [
            (cid, name)
            for cid, name in crud_review.list_all_congresistas(db)
            if cid not in existing_ids
        ]

    document_status = "none"
    document_url = None
    fallback_url = None
    if doc_result == "ambiguous":
        document_status = "ambiguous"
    elif doc_result is not None:
        if doc_result.s3_key:
            document_status = "resolved"
            document_url = url_for("review.document", vote_event_id=vote_event_id)
        else:
            document_status = "not_archived"
            fallback_url = doc_result.url

    return render_template(
        "detail.html",
        event=event,
        rows=rows,
        summary=summary,
        addable_congresistas=addable_congresistas,
        document_status=document_status,
        document_url=document_url,
        fallback_url=fallback_url,
        vote_options=list(VoteOption),
        attendance_statuses=list(AttendanceStatus),
        unrecorded_label=crud_review.UNRECORDED_LABEL,
        ids_csv=request.args.get("ids", ""),
        pos=request.args.get("pos", ""),
    )


@review_bp.route("/review/<vote_event_id>/document")
def document(vote_event_id):
    with SessionLocal() as db:
        doc = crud_review.find_document_for_vote_event(db, vote_event_id)

    if doc is None or doc == "ambiguous" or not getattr(doc, "s3_key", None):
        return "Document not available", 404

    bucket = settings.AWS_S3_BUCKET_NAME
    if not bucket:
        current_app.logger.error("AWS_S3_BUCKET_NAME is not configured")
        return "Document not available", 404

    if settings.AWS_ACCESS_KEY_ID and settings.AWS_SECRET_ACCESS_KEY:
        client = boto3.session.Session(
            aws_access_key_id=settings.AWS_ACCESS_KEY_ID,
            aws_secret_access_key=settings.AWS_SECRET_ACCESS_KEY,
            region_name=settings.AWS_REGION,
        ).client("s3")
    else:
        client = boto3.client("s3", region_name=settings.AWS_REGION)

    try:
        obj = client.get_object(Bucket=bucket, Key=doc.s3_key)
    except client.exceptions.NoSuchKey:
        current_app.logger.warning(
            "S3 object missing for vote_event %s key %s", vote_event_id, doc.s3_key
        )
        return "Document not available", 404
    except Exception:
        current_app.logger.exception("S3 fetch failed for vote_event %s", vote_event_id)
        return "Document not available", 502

    resp = make_response(obj["Body"].read())
    # Force application/pdf rather than trusting S3's stored ContentType --
    # uploads that didn't set it explicitly default to
    # application/octet-stream, which makes the browser download the file
    # instead of rendering it in the iframe. Every document reachable via
    # this route is a scraped PDF (RawBillDocument/RawMotionDocument), so
    # there's no case where a different content type would be correct.
    resp.headers["Content-Type"] = "application/pdf"
    resp.headers["Content-Disposition"] = f'inline; filename="{vote_event_id}.pdf"'
    resp.headers["Cache-Control"] = "public, max-age=86400"
    return resp


@review_bp.route("/review/<vote_event_id>/save", methods=["POST"])
def save(vote_event_id):
    with SessionLocal() as db:
        event = db.get(db_models.VoteEvent, vote_event_id)
        if event is None:
            return "Not Found", 404

        rows = crud_review.get_review_rows(db, vote_event_id)
        row_by_id = {r.congresista_id: r for r in rows}
        valid_ids = set(row_by_id)
        reviewer_name = session["reviewer_name"]

        corrected = flagged = verified = 0

        for key, value in request.form.items():
            if key.startswith("vote-"):
                target_id = _parse_target_id(key, "vote-")
                if target_id is None:
                    continue
                # An empty selection ("-- not recorded --") means "remove
                # this row" -- apply_correction(new_value=None) deletes
                # the existing Vote row instead of upserting one.
                if value == "":
                    new_value = None
                else:
                    try:
                        new_value = VoteOption(value).value
                    except ValueError:
                        return f"Invalid vote option: {value!r}", 400
                try:
                    result = crud_review.apply_correction(
                        db,
                        vote_event_id=vote_event_id,
                        target_type="vote",
                        target_id=target_id,
                        new_value=new_value,
                        reviewer_name=reviewer_name,
                        valid_target_ids=valid_ids,
                    )
                except ValueError as exc:
                    return str(exc), 400
                if result is not None:
                    corrected += 1
            elif key.startswith("attendance-"):
                target_id = _parse_target_id(key, "attendance-")
                if target_id is None:
                    continue
                if value == "":
                    new_value = None
                else:
                    try:
                        new_value = AttendanceStatus(value).value
                    except ValueError:
                        return f"Invalid attendance status: {value!r}", 400
                try:
                    result = crud_review.apply_correction(
                        db,
                        vote_event_id=vote_event_id,
                        target_type="attendance",
                        target_id=target_id,
                        new_value=new_value,
                        reviewer_name=reviewer_name,
                        valid_target_ids=valid_ids,
                    )
                except ValueError as exc:
                    return str(exc), 400
                if result is not None:
                    corrected += 1

        for key in request.form:
            if key.startswith("flag-"):
                action = "flagged"
                target_id = _parse_target_id(key, "flag-")
            elif key.startswith("verified-"):
                action = "verified"
                target_id = _parse_target_id(key, "verified-")
            else:
                continue
            if target_id is None or target_id not in row_by_id:
                continue

            row = row_by_id[target_id]
            target_types = [
                t
                for t, present in (
                    ("vote", row.vote_option is not None),
                    ("attendance", row.attendance_status is not None),
                )
                if present
            ]
            for target_type in target_types:
                crud_review.record_review_action(
                    db,
                    vote_event_id=vote_event_id,
                    target_type=target_type,
                    target_id=target_id,
                    action=action,
                    reviewer_name=reviewer_name,
                    valid_target_ids=valid_ids,
                )
            if action == "flagged":
                flagged += 1
            else:
                verified += 1

        db.commit()

    flash(f"{corrected} changed, {flagged} flagged, {verified} verified")
    return redirect(
        url_for(
            "review.detail",
            vote_event_id=vote_event_id,
            ids=request.args.get("ids", ""),
            pos=request.args.get("pos", ""),
        )
    )


@review_bp.route("/review/<vote_event_id>/add_congresista", methods=["POST"])
def add_congresista(vote_event_id):
    """
    Adds one or more congresistas in a single submission. The template
    renders one or more identical (congresista_id, attendance_status,
    vote_option) triplets -- possibly with extra unused rows added via
    the "+ Add another" control -- so the three fields are read with
    `getlist()` and zipped back together by position rather than reading
    a single value each.
    """
    congresista_ids = request.form.getlist("congresista_id")
    vote_values = request.form.getlist("vote_option")
    attendance_values = request.form.getlist("attendance_status")

    # getlist() returns [] -- not a same-length list of ""s -- when a
    # field is entirely absent from the submission (e.g. a client that
    # only sends vote_option and omits attendance_status altogether,
    # rather than sending it as an empty string). Treat "absent" the same
    # as "blank for every row" instead of flagging it as malformed.
    row_count = len(congresista_ids)
    if not vote_values:
        vote_values = [""] * row_count
    if not attendance_values:
        attendance_values = [""] * row_count

    if not (len(congresista_ids) == len(vote_values) == len(attendance_values)):
        return "Malformed submission", 400

    with SessionLocal() as db:
        event = db.get(db_models.VoteEvent, vote_event_id)
        if event is None:
            return "Not Found", 404

        reviewer_name = session["reviewer_name"]
        added = 0

        for raw_id, vote_value, attendance_value in zip(
            congresista_ids, vote_values, attendance_values
        ):
            raw_id = (raw_id or "").strip()
            if not raw_id:
                # An unused extra row from "+ Add another" -- skip it,
                # not an error.
                continue
            try:
                congresista_id = int(raw_id)
            except ValueError:
                return f"Invalid congresista id: {raw_id!r}", 400
            if db.get(db_models.Congresista, congresista_id) is None:
                return f"Unknown congresista: {raw_id!r}", 400

            vote_value = vote_value or None
            attendance_value = attendance_value or None
            if vote_value is None and attendance_value is None:
                # A person was picked but no value given for them --
                # nothing to add for this row, skip rather than fail the
                # whole batch over one incomplete row.
                continue

            # This action's whole purpose is adding someone the automatic
            # roster/extraction never surfaced, so each row is gated only
            # on "this congresista_id exists" (checked above), not on the
            # computed roster -- unlike the per-row save() flow.
            valid_ids = {congresista_id}

            if vote_value is not None:
                try:
                    vote_value = VoteOption(vote_value).value
                except ValueError:
                    return f"Invalid vote option: {vote_value!r}", 400
                crud_review.apply_correction(
                    db,
                    vote_event_id=vote_event_id,
                    target_type="vote",
                    target_id=congresista_id,
                    new_value=vote_value,
                    reviewer_name=reviewer_name,
                    valid_target_ids=valid_ids,
                )

            if attendance_value is not None:
                try:
                    attendance_value = AttendanceStatus(attendance_value).value
                except ValueError:
                    return f"Invalid attendance status: {attendance_value!r}", 400
                crud_review.apply_correction(
                    db,
                    vote_event_id=vote_event_id,
                    target_type="attendance",
                    target_id=congresista_id,
                    new_value=attendance_value,
                    reviewer_name=reviewer_name,
                    valid_target_ids=valid_ids,
                )

            added += 1

        if added == 0:
            return (
                "No congresistas were added -- pick at least one person with a value",
                400,
            )

        db.commit()

    flash(f"{added} congresista(s) added")
    return redirect(url_for("review.detail", vote_event_id=vote_event_id))


@review_bp.route("/review/set_reviewer", methods=["POST"])
def set_reviewer():
    name = (request.form.get("reviewer_name") or "").strip()
    next_url = request.form.get("next_url") or url_for("review.search")
    if not name:
        return (
            render_template(
                "set_reviewer.html",
                next_url=next_url,
                error="Please enter a name.",
            ),
            400,
        )
    session["reviewer_name"] = name
    return redirect(next_url)
