"""
CRUD helpers for the standalone vote/attendance review tool (`review_app/`).

Kept separate from `pipeline_votes.py`, which is scoped to the votes ETL
extraction/load pipeline, not this reviewer tool. See the approved plan at
`~/.claude/plans/project-vote-buzzing-pillow.md` for the full design and
`/plan-eng-review` rationale behind each function's shape.
"""

from __future__ import annotations

import json
from collections import Counter
from dataclasses import dataclass
from datetime import date, datetime
from typing import Literal
from zoneinfo import ZoneInfo

from sqlalchemy import and_, func, or_, select
from sqlalchemy.orm import Session

from backend import VoteOption
from backend.database import models as db_models
from backend.database.crud.pipeline_core import find_active_bancada_for_person
from backend.database.crud.pipeline_votes import (
    upsert_attendance,
    upsert_vote,
    upsert_vote_counts_for_event,
)
from backend.database.raw_models import (
    RawBillDocument,
    RawBillPage,
    RawMotionDocument,
    RawMotionPage,
)
from review_app.models import VoteReviewAudit

TargetType = Literal["vote", "attendance"]
ReviewAction = Literal["verified", "corrected", "flagged"]

UNRECORDED_LABEL = "Sin registrar"


def find_document_for_vote_event(
    db: Session, vote_event_id: str
) -> RawBillDocument | RawMotionDocument | Literal["ambiguous"] | None:
    """
    Walk the PDF-linkage chain (VoteEvent -> BillStep/MotionStep ->
    RawBillPage/RawMotionPage -> RawBillDocument/RawMotionDocument) to find
    the source document behind a vote event.

    `processed=True` on a page is set on EVERY extraction attempt --
    success, no-match, or an unresolvable anchor step (load.py:184-201) --
    not just successful loads. This filters on the page's own parsed
    `match_found` flag instead, which is the actual "did this row's data
    get loaded" signal. If more than one page for the same step has
    `match_found=True`, that's a real upstream-matching anomaly (two
    documents both claiming the same vote event) -- surfaced as
    `"ambiguous"` rather than silently resolved.

    Returns the resolved document row, `"ambiguous"`, or `None` if the
    chain dead-ends entirely (event/step/document all missing).
    """
    event = db.get(db_models.VoteEvent, vote_event_id)
    if event is None:
        return None

    if event.bill_id is not None:
        target_id = event.bill_id
        id_attr = "bill_id"
        step_model = db_models.BillStep
        page_model = RawBillPage
        doc_model = RawBillDocument
    else:
        target_id = event.motion_id
        id_attr = "motion_id"
        step_model = db_models.MotionStep
        page_model = RawMotionPage
        doc_model = RawMotionDocument

    step = db.scalars(
        select(step_model).where(step_model.vote_event_id == vote_event_id)
    ).first()
    if step is None:
        return None

    pages = db.scalars(
        select(page_model).where(
            getattr(page_model, id_attr) == target_id,
            page_model.step_id == step.step_id,
            page_model.page_num == 0,
            page_model.processed.is_(True),
        )
    ).all()

    matched_file_ids = []
    for page in pages:
        try:
            record = json.loads(page.text)
        except (ValueError, TypeError):
            continue
        parsed = record.get("parsed") if isinstance(record, dict) else None
        if parsed and parsed.get("match_found"):
            matched_file_ids.append(page.file_id)

    if len(matched_file_ids) > 1:
        return "ambiguous"

    if len(matched_file_ids) == 1:
        doc = db.get(doc_model, (target_id, step.step_id, matched_file_ids[0]))
        if doc is not None:
            return doc

    # Zero matches (or the matched page's document row is somehow missing)
    # -- best-effort fallback: the pipeline may not have loaded this step
    # yet, but a scraped-and-archived document can still be shown.
    return db.scalars(
        select(doc_model)
        .where(
            getattr(doc_model, id_attr) == target_id,
            doc_model.step_id == step.step_id,
            doc_model.last_update.is_(True),
        )
        .order_by(doc_model.timestamp.desc())
    ).first()


def search_review_queue(
    db: Session,
    *,
    q: str | None = None,
    date_from: date | None = None,
    date_to: date | None = None,
    org_id: int | None = None,
    limit: int = 50,
    offset: int = 0,
) -> list[db_models.VoteEvent]:
    """
    Plain filtered/paginated search over VoteEvent, ordered by event_date
    descending. No "needs review" default -- there's currently no
    automated signal for which events need a second look on this branch,
    so the reviewer drives this purely off id/date/org filters.
    """
    stmt = select(db_models.VoteEvent)
    filters = []
    if q:
        like = f"%{q}%"
        filters.append(
            or_(
                db_models.VoteEvent.vote_event_id.ilike(like),
                db_models.VoteEvent.bill_id.ilike(like),
                db_models.VoteEvent.motion_id.ilike(like),
            )
        )
    if date_from is not None:
        filters.append(db_models.VoteEvent.event_date >= date_from)
    if date_to is not None:
        filters.append(db_models.VoteEvent.event_date <= date_to)
    if org_id is not None:
        filters.append(db_models.VoteEvent.org_id == org_id)
    if filters:
        stmt = stmt.where(and_(*filters))

    stmt = (
        stmt.order_by(db_models.VoteEvent.event_date.desc()).limit(limit).offset(offset)
    )
    return db.scalars(stmt).all()


@dataclass
class ReviewRow:
    congresista_id: int
    display_name: str
    bancada_name: str | None
    vote_option: str | None
    attendance_status: str | None
    vote_action: str | None
    attendance_action: str | None


def _display_name(full_name: str, first_name: str | None, last_name: str | None) -> str:
    """'Last, First' for sorting/scanning a roster A-Z by surname -- falls
    back to full_name for the congresistas missing a first/last split."""
    if last_name and first_name:
        return f"{last_name}, {first_name}"
    return full_name


def _roster_ids_for_event(db: Session, event: db_models.VoteEvent) -> set[int]:
    """
    The expected roster: everyone who was a member of the event's own
    organization (`Membership.org_id == event.org_id`) as of its
    `event_date`. Querying the base `Membership` table directly -- rather
    than a specific subtype like `ChamberMembership` -- means this works
    unchanged for a plenary vote (org_id = the chamber) and for a
    Comisión Permanente vote (org_id = that committee) alike: whichever
    org the vote actually happened in defines the roster, not a hardcoded
    assumption about which subtype applies.
    """
    return set(
        db.scalars(
            select(db_models.Membership.person_id).where(
                db_models.Membership.org_id == event.org_id,
                db_models.Membership.start_date <= event.event_date,
                db_models.Membership.end_date >= event.event_date,
            )
        ).all()
    )


def _bancada_names_as_of(
    db: Session, person_ids: set[int], as_of: date
) -> dict[int, str]:
    """Each person's political-group membership as of a date."""
    if not person_ids:
        return {}
    rows = db.execute(
        select(db_models.BancadaMembership.person_id, db_models.Organization.org_name)
        .join(
            db_models.Organization,
            db_models.Organization.org_id == db_models.BancadaMembership.org_id,
        )
        .where(
            db_models.BancadaMembership.person_id.in_(person_ids),
            db_models.BancadaMembership.start_date <= as_of,
            db_models.BancadaMembership.end_date >= as_of,
        )
    ).all()
    return dict(rows)


def resync_vote_event_aggregates(db: Session, vote_event_id: str) -> None:
    """
    Recompute `VoteEvent.votes_in_favor/against/abstention` and rebuild
    `VoteCounts` (per bancada per option) from the CURRENT `Vote` rows for
    this event. `apply_correction` previously only touched the individual
    `Vote` row it was asked to change, silently leaving these two
    derived/aggregate tables stale after every review-tool correction --
    this makes every add/correct/remove of a vote re-sync both, the same
    way the original ETL load path does via `upsert_vote_event`/
    `upsert_vote_counts_for_event`, just recomputed from the live table
    instead of from the extraction's own tally.

    Public (not `_`-prefixed) because `scripts/backfill_review_aggregates.py`
    calls it directly to re-sync events that were corrected before this
    function existed -- one shared implementation for both the live
    per-correction path and the one-time backfill, rather than two copies
    that could drift apart.
    """
    event = db.get(db_models.VoteEvent, vote_event_id)
    if event is None:
        return

    rows = db.execute(
        select(db_models.Vote.option, db_models.Vote.bancada_id).where(
            db_models.Vote.vote_event_id == vote_event_id
        )
    ).all()

    tally = Counter(option for option, _ in rows)
    event.votes_in_favor = tally.get(VoteOption.SI, 0)
    event.votes_against = tally.get(VoteOption.NO, 0)
    event.votes_abstention = tally.get(VoteOption.ABSTENCION, 0)

    counts = Counter((bancada_id, option) for option, bancada_id in rows)
    upsert_vote_counts_for_event(db, vote_event_id=vote_event_id, counts=dict(counts))
    db.flush()


def list_all_congresistas(db: Session) -> list[tuple[int, str]]:
    """All congresistas as (id, display_name), sorted A-Z by surname --
    populates the "add a congresista" control in the review tool."""
    rows = db.execute(
        select(
            db_models.Congresista.id,
            db_models.Congresista.full_name,
            db_models.Congresista.first_name,
            db_models.Congresista.last_name,
        )
    ).all()
    people = [
        (row.id, _display_name(row.full_name, row.first_name, row.last_name))
        for row in rows
    ]
    people.sort(key=lambda p: p[1].casefold())
    return people


def get_review_rows(db: Session, vote_event_id: str) -> list[ReviewRow]:
    """
    One row per congresista in the union of: the expected roster (every
    member of the event's organization as of its date, via
    `_roster_ids_for_event` -- so someone nobody extracted a vote for
    still shows up, ready to fill in) and anyone who already has a
    Vote/Attendance row for this event even if they fall outside that
    roster (so an extraction error that attributes a vote to the wrong
    person stays visible instead of silently disappearing).

    Bancada is resolved from `BancadaMembership` as of the event's date --
    the same source for everyone, including roster members who don't have
    a Vote/Attendance row yet -- falling back to the extraction-time
    `Vote`/`Attendance.bancada_id` snapshot only when no current
    membership record resolves one.

    The latest-audit-action lookup is a single windowed query
    (ROW_NUMBER() partitioned by target_type/target_id), not a per-row
    query -- a per-row loop would issue one query per congresista (100+
    on a typical vote event) on every detail-page load.

    The returned rows are also the source of truth for the event's
    legitimate roster: callers use `{row.congresista_id for row in
    get_review_rows(...)}` to validate any submitted correction before
    calling `apply_correction`/`record_review_action`.
    """
    event = db.get(db_models.VoteEvent, vote_event_id)
    if event is None:
        return []

    vote_by_id = {
        r.voter_id: r
        for r in db.execute(
            select(
                db_models.Vote.voter_id,
                db_models.Vote.option,
                db_models.Vote.bancada_id,
            ).where(db_models.Vote.vote_event_id == vote_event_id)
        ).all()
    }
    attendance_by_id = {
        r.attendee_id: r
        for r in db.execute(
            select(
                db_models.Attendance.attendee_id,
                db_models.Attendance.status,
                db_models.Attendance.bancada_id,
            ).where(db_models.Attendance.event_id == vote_event_id)
        ).all()
    }

    all_ids = _roster_ids_for_event(db, event) | set(vote_by_id) | set(attendance_by_id)
    if not all_ids:
        return []

    congresista_by_id = {
        c.id: c
        for c in db.scalars(
            select(db_models.Congresista).where(db_models.Congresista.id.in_(all_ids))
        ).all()
    }

    membership_bancada = _bancada_names_as_of(db, all_ids, event.event_date)

    extraction_bancada_ids = {
        r.bancada_id
        for r in [*vote_by_id.values(), *attendance_by_id.values()]
        if r.bancada_id is not None
    }
    extraction_org_name_by_id: dict[int, str] = {}
    if extraction_bancada_ids:
        extraction_org_name_by_id = dict(
            db.execute(
                select(
                    db_models.Organization.org_id, db_models.Organization.org_name
                ).where(db_models.Organization.org_id.in_(extraction_bancada_ids))
            ).all()
        )

    action_by_target = _latest_actions_for_event(db, vote_event_id)

    rows = []
    for congresista_id in all_ids:
        congresista = congresista_by_id.get(congresista_id)
        if congresista is None:
            # A Vote/Attendance row points at a congresista_id that no
            # longer exists -- shouldn't happen, skip defensively rather
            # than crash the whole detail page over one bad row.
            continue

        vote_row = vote_by_id.get(congresista_id)
        attendance_row = attendance_by_id.get(congresista_id)

        bancada_name = membership_bancada.get(congresista_id)
        if bancada_name is None:
            fallback_bancada_id = (vote_row.bancada_id if vote_row else None) or (
                attendance_row.bancada_id if attendance_row else None
            )
            bancada_name = extraction_org_name_by_id.get(fallback_bancada_id)

        rows.append(
            ReviewRow(
                congresista_id=congresista_id,
                display_name=_display_name(
                    congresista.full_name, congresista.first_name, congresista.last_name
                ),
                bancada_name=bancada_name,
                vote_option=vote_row.option.value if vote_row else None,
                attendance_status=attendance_row.status.value
                if attendance_row
                else None,
                vote_action=action_by_target.get(("vote", congresista_id)),
                attendance_action=action_by_target.get(("attendance", congresista_id)),
            )
        )

    rows.sort(key=lambda r: r.display_name.casefold())
    return rows


def summarize_votes(rows: list[ReviewRow]) -> dict[str, dict[str, int]]:
    """
    Live tally of vote counts per party (bancada) plus a grand "TOTAL"
    row -- computed from the rows `get_review_rows` already fetched, no
    new query. Parties are ordered alphabetically with "TOTAL" last;
    people with no recorded vote count under `UNRECORDED_LABEL` so the
    reviewer can see at a glance how much of each party is still pending.
    """
    option_labels = [opt.value for opt in VoteOption] + [UNRECORDED_LABEL]
    per_party: dict[str, dict[str, int]] = {}
    for row in rows:
        party = row.bancada_name or "Sin bancada"
        option = row.vote_option or UNRECORDED_LABEL
        counts = per_party.setdefault(party, {label: 0 for label in option_labels})
        counts[option] += 1

    total = {label: 0 for label in option_labels}
    for counts in per_party.values():
        for label, count in counts.items():
            total[label] += count

    ordered = {party: per_party[party] for party in sorted(per_party, key=str.casefold)}
    ordered["TOTAL"] = total
    return ordered


def _latest_actions_for_event(
    db: Session, vote_event_id: str
) -> dict[tuple[str, int], str]:
    """Single windowed query: the most recent action per (target_type, target_id)."""
    rn = (
        func.row_number()
        .over(
            partition_by=(VoteReviewAudit.target_type, VoteReviewAudit.target_id),
            order_by=VoteReviewAudit.created_at.desc(),
        )
        .label("rn")
    )
    subq = (
        select(
            VoteReviewAudit.target_type,
            VoteReviewAudit.target_id,
            VoteReviewAudit.action,
            rn,
        )
        .where(VoteReviewAudit.vote_event_id == vote_event_id)
        .subquery()
    )
    rows = db.execute(
        select(subq.c.target_type, subq.c.target_id, subq.c.action).where(
            subq.c.rn == 1
        )
    ).all()
    return {(target_type, target_id): action for target_type, target_id, action in rows}


def _now_lima() -> datetime:
    return datetime.now(ZoneInfo("America/Lima"))


def apply_correction(
    db: Session,
    *,
    vote_event_id: str,
    target_type: TargetType,
    target_id: int,
    new_value: str | None,
    reviewer_name: str,
    valid_target_ids: set[int],
) -> VoteReviewAudit | None:
    """
    Single function for adding, correcting, AND removing both vote and
    attendance rows. Raises `ValueError` if `target_id` isn't in
    `valid_target_ids` -- the caller computes that set (normally from
    `get_review_rows`'s roster, or just `{target_id}` for the explicit
    "add a congresista" action) before processing any submitted field, so
    a tampered or stray congresista_id never reaches
    `upsert_vote`/`upsert_attendance` as a silent new row.

    `new_value=None` means "remove this row" -- deletes the existing
    Vote/Attendance row if one exists (a no-op if there wasn't one). Any
    other string means "add or correct" -- upserts the row. For a vote,
    `bancada_id` is re-resolved from the person's current
    `BancadaMembership` as of the event's date on every add/correct
    (falling back to whatever was already stored if no membership record
    resolves one) rather than blindly carrying over the previous value --
    a brand-new row otherwise gets `bancada_id=None` forever, which would
    silently drop out of every bancada-grouped view. Every real vote
    change also re-syncs `VoteEvent`'s tally fields and `VoteCounts` from
    the table's current state (see `resync_vote_event_aggregates`) --
    those two derived tables would otherwise go stale the moment a
    correction changed what they were computed from. No-ops (returns
    None, no DB write) if the submitted value matches the current one
    either way. `new_value` is assumed already validated against the
    relevant enum by the caller when it isn't None -- this function
    trusts it.
    """
    if target_id not in valid_target_ids:
        raise ValueError(
            f"congresista {target_id} is not part of vote event {vote_event_id}'s roster"
        )

    if target_type == "vote":
        event = db.get(db_models.VoteEvent, vote_event_id)
        existing = db.get(db_models.Vote, (vote_event_id, target_id))
        old_value = existing.option.value if existing else None
        if old_value == new_value:
            return None
        if new_value is None:
            if existing is not None:
                db.delete(existing)
        else:
            org = find_active_bancada_for_person(db, target_id, event.event_date)
            bancada_id = (
                org.org_id
                if org is not None
                else (existing.bancada_id if existing else None)
            )
            upsert_vote(
                db,
                vote_event_id=vote_event_id,
                voter_id=target_id,
                option=new_value,
                bancada_id=bancada_id,
            )
        db.flush()
        resync_vote_event_aggregates(db, vote_event_id)
    elif target_type == "attendance":
        existing = db.get(db_models.Attendance, (vote_event_id, target_id))
        old_value = existing.status.value if existing else None
        if old_value == new_value:
            return None
        if new_value is None:
            if existing is not None:
                db.delete(existing)
        else:
            upsert_attendance(
                db,
                event_id=vote_event_id,
                attendee_id=target_id,
                status=new_value,
                bancada_id=existing.bancada_id if existing else None,
            )
    else:
        raise ValueError(f"Unknown target_type: {target_type!r}")

    audit = VoteReviewAudit(
        vote_event_id=vote_event_id,
        target_type=target_type,
        target_id=target_id,
        action="corrected",
        old_value=old_value,
        new_value=new_value,
        reviewer_name=reviewer_name,
        created_at=_now_lima(),
    )
    db.add(audit)
    db.flush()
    return audit


def record_review_action(
    db: Session,
    *,
    vote_event_id: str,
    target_type: TargetType,
    target_id: int,
    action: Literal["verified", "flagged"],
    reviewer_name: str,
    valid_target_ids: set[int],
) -> VoteReviewAudit:
    """For the 'verified'/'flagged' per-row actions that don't change a value."""
    if target_id not in valid_target_ids:
        raise ValueError(
            f"congresista {target_id} is not part of vote event {vote_event_id}'s roster"
        )

    audit = VoteReviewAudit(
        vote_event_id=vote_event_id,
        target_type=target_type,
        target_id=target_id,
        action=action,
        old_value=None,
        new_value=None,
        reviewer_name=reviewer_name,
        created_at=_now_lima(),
    )
    db.add(audit)
    db.flush()
    return audit
