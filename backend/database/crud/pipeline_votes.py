from __future__ import annotations

import json
from datetime import datetime
from typing import Literal
from zoneinfo import ZoneInfo

from sqlalchemy import select, delete, func, case, literal, or_, and_

from sqlalchemy.orm import Session
from sqlalchemy.sql.elements import ColumnElement

from backend import (
    LegPeriod,
    TypeOrganization,
    AttendanceStatus,
    VoteOption,
    TypeRoleBill,
    TypeBillStep,
    TypeMotionStep,
)
from backend.database import models as db_models
from backend.database.raw_models import (
    ModelCostLedger,
    RawBillDocument,
    RawBillPage,
    RawMotionDocument,
    RawMotionPage,
)
from backend.core.parsers import LEG_PERIOD_RANGES
from backend.process.utils import normalize_party_name
from backend.database.crud.pipeline_core import _enum_value, find_organization
from backend.process import schema


def find_leg_period_expr(value_col: ColumnElement) -> ColumnElement:
    """
    SQLAlchemy expression version.
    Use this inside select(), group_by(), where(), joins, etc.
    """
    value_date = func.date(value_col)

    return case(
        *[
            (
                (value_date >= start_date.isoformat())
                & (value_date <= end_date.isoformat()),
                literal(leg_period.value),
            )
            for leg_period, start_date, end_date in LEG_PERIOD_RANGES
        ],
        else_=literal(LegPeriod.PERIODO_1992_1995.value),
    )


def refresh_congresista_metrics(db: Session) -> int:
    """
    Rebuild congresista_metrics from the existing processed tables.

    This function deletes and recreates all rows in congresista_metrics.
    It does not commit. The caller must run it inside a transaction.
    """

    db.execute(delete(db_models.CongresistaMetric))

    attendance_sq = (
        select(
            db_models.Attendance.attendee_id.label("cong_id"),
            db_models.ChamberMembership.leg_period.label("leg_period"),
            func.avg(
                case(
                    (
                        db_models.Attendance.status == AttendanceStatus.PRESENTE,
                        1.0,
                    ),
                    else_=0.0,
                )
            ).label("avg_attendance"),
        )
        .join(
            db_models.VoteEvent,
            db_models.VoteEvent.vote_event_id == db_models.Attendance.event_id,
        )
        .join(
            db_models.ChamberMembership,
            and_(
                db_models.ChamberMembership.person_id
                == db_models.Attendance.attendee_id,
                db_models.ChamberMembership.org_id == db_models.VoteEvent.org_id,
                db_models.ChamberMembership.org_type == TypeOrganization.CHAMBER,
                db_models.VoteEvent.event_date
                >= db_models.ChamberMembership.start_date,
                or_(
                    db_models.ChamberMembership.end_date.is_(None),
                    db_models.VoteEvent.event_date
                    <= db_models.ChamberMembership.end_date,
                ),
            ),
        )
        .group_by(
            db_models.Attendance.attendee_id,
            db_models.ChamberMembership.leg_period,
        )
        .subquery()
    )

    bill_dates_sq = (
        select(
            db_models.BillOrganization.bill_id.label("bill_id"),
            func.min(db_models.BillOrganization.presentation_date).label(
                "presentation_date"
            ),
        )
        .group_by(db_models.BillOrganization.bill_id)
        .subquery()
    )

    bills_sq = (
        select(
            db_models.BillCongresistas.person_id.label("cong_id"),
            find_leg_period_expr(bill_dates_sq.c.presentation_date).label("leg_period"),
            func.count(db_models.BillCongresistas.bill_id).label("bills_auth"),
            func.avg(
                case(
                    (db_models.Bill.bill_approved.is_(True), 1.0),
                    else_=0.0,
                )
            ).label("bills_success_rate"),
        )
        .join(db_models.Bill, db_models.Bill.id == db_models.BillCongresistas.bill_id)
        .join(bill_dates_sq, bill_dates_sq.c.bill_id == db_models.Bill.id)
        .where(db_models.BillCongresistas.role_type == TypeRoleBill.AUTHOR)
        .group_by(
            db_models.BillCongresistas.person_id,
            find_leg_period_expr(bill_dates_sq.c.presentation_date),
        )
        .subquery()
    )

    motion_dates_sq = (
        select(
            db_models.MotionOrganization.motion_id.label("motion_id"),
            func.min(db_models.MotionOrganization.presentation_date).label(
                "presentation_date"
            ),
        )
        .group_by(db_models.MotionOrganization.motion_id)
        .subquery()
    )

    motions_sq = (
        select(
            db_models.MotionCongresistas.person_id.label("cong_id"),
            find_leg_period_expr(motion_dates_sq.c.presentation_date).label(
                "leg_period"
            ),
            func.count(db_models.MotionCongresistas.motion_id).label("motions_auth"),
            func.avg(
                case(
                    (db_models.Motion.motion_approved.is_(True), 1.0),
                    else_=0.0,
                )
            ).label("motions_success_rate"),
        )
        .join(
            db_models.Motion,
            db_models.Motion.id == db_models.MotionCongresistas.motion_id,
        )
        .join(motion_dates_sq, motion_dates_sq.c.motion_id == db_models.Motion.id)
        .where(db_models.MotionCongresistas.role_type == TypeRoleBill.AUTHOR)
        .group_by(
            db_models.MotionCongresistas.person_id,
            find_leg_period_expr(motion_dates_sq.c.presentation_date),
        )
        .subquery()
    )

    camara_memberships_sq = (
        select(
            db_models.ChamberMembership.person_id.label("cong_id"),
            db_models.ChamberMembership.leg_period.label("leg_period"),
        )
        .where(db_models.ChamberMembership.org_type == TypeOrganization.CHAMBER)
        .distinct()
        .subquery()
    )

    rows = db.execute(
        select(
            camara_memberships_sq.c.cong_id,
            camara_memberships_sq.c.leg_period,
            attendance_sq.c.avg_attendance,
            func.coalesce(bills_sq.c.bills_auth, 0).label("bills_auth"),
            bills_sq.c.bills_success_rate,
            func.coalesce(motions_sq.c.motions_auth, 0).label("motions_auth"),
            motions_sq.c.motions_success_rate,
        )
        .outerjoin(
            attendance_sq,
            (attendance_sq.c.cong_id == camara_memberships_sq.c.cong_id)
            & (attendance_sq.c.leg_period == camara_memberships_sq.c.leg_period),
        )
        .outerjoin(
            bills_sq,
            (bills_sq.c.cong_id == camara_memberships_sq.c.cong_id)
            & (bills_sq.c.leg_period == camara_memberships_sq.c.leg_period),
        )
        .outerjoin(
            motions_sq,
            (motions_sq.c.cong_id == camara_memberships_sq.c.cong_id)
            & (motions_sq.c.leg_period == camara_memberships_sq.c.leg_period),
        )
    ).all()

    metrics = [
        db_models.CongresistaMetric(
            cong_id=row.cong_id,
            leg_period=row.leg_period,
            avg_attendance=row.avg_attendance,
            bills_auth=row.bills_auth,
            bills_success_rate=row.bills_success_rate,
            motions_auth=row.motions_auth,
            motions_success_rate=row.motions_success_rate,
        )
        for row in rows
    ]

    db.add_all(metrics)
    db.flush()

    return len(metrics)


def find_bill_by_pley_id(db: Session, pley_id: str) -> db_models.Bill | None:
    """
    Find a Bill by its pley_id, exact match first.

    Congress-side sources are inconsistent about zero-padding the numeric
    prefix (e.g. "05665/2023-CR" vs "5665/2023-CR"), so fall back to
    stripping leading zeros if the exact value isn't found.
    """
    bill = db.scalar(select(db_models.Bill).where(db_models.Bill.pley_id == pley_id))
    if bill is not None:
        return bill

    stripped = pley_id.lstrip("0")
    if stripped and stripped != pley_id:
        return db.scalar(
            select(db_models.Bill).where(db_models.Bill.pley_id == stripped)
        )
    return None


def find_vote_steps(
    db: Session,
    *,
    bill_id: str | None = None,
    motion_id: str | None = None,
) -> list[db_models.BillStep] | list[db_models.MotionStep]:
    """
    Return vote_step=True rows for one bill or motion, ordered (step_date, step_id).
    """
    if bill_id is not None:
        stmt = (
            select(db_models.BillStep)
            .where(
                db_models.BillStep.bill_id == bill_id,
                db_models.BillStep.vote_step.is_(True),
            )
            .order_by(db_models.BillStep.step_date, db_models.BillStep.step_id)
        )
    elif motion_id is not None:
        stmt = (
            select(db_models.MotionStep)
            .where(
                db_models.MotionStep.motion_id == motion_id,
                db_models.MotionStep.vote_step.is_(True),
            )
            .order_by(db_models.MotionStep.step_date, db_models.MotionStep.step_id)
        )
    else:
        raise ValueError("Must provide bill_id or motion_id")

    return db.scalars(stmt).all()


def find_step_by_id(
    db: Session,
    *,
    bill_id: str | None = None,
    motion_id: str | None = None,
    step_id: int,
) -> db_models.BillStep | db_models.MotionStep | None:
    """
    Fetch the single BillStep/MotionStep row a page's own (bill_id/motion_id,
    step_id) FK points to -- the deterministic anchor step this document was
    scraped for. Straight PK lookup, no date-guessing.
    """
    if bill_id is not None:
        return db.get(db_models.BillStep, (bill_id, step_id))
    if motion_id is not None:
        return db.get(db_models.MotionStep, (motion_id, step_id))
    raise ValueError("Must provide bill_id or motion_id")


def find_pending_vote_documents(
    db: Session,
    *,
    kind: Literal["bill", "motion"],
    max_pages: int | None = None,
    limit: int | None = None,
) -> list[RawBillDocument] | list[RawMotionDocument]:
    """
    Vote-related documents (joined on a vote_step BillStep/MotionStep row)
    that haven't been extracted yet, optionally capped to <= max_pages.
    """
    if kind == "bill":
        doc_model = RawBillDocument
        stmt = (
            select(RawBillDocument)
            .join(
                db_models.BillStep,
                and_(
                    db_models.BillStep.bill_id == RawBillDocument.bill_id,
                    db_models.BillStep.step_id == RawBillDocument.step_id,
                ),
            )
            .where(
                db_models.BillStep.step_type == TypeBillStep.VOTACION,
                db_models.BillStep.vote_step.is_(True),
                RawBillDocument.last_update.is_(True),
                RawBillDocument.processed.is_(False),
            )
            .order_by(RawBillDocument.step_date)
        )
    elif kind == "motion":
        doc_model = RawMotionDocument
        stmt = (
            select(RawMotionDocument)
            .join(
                db_models.MotionStep,
                and_(
                    db_models.MotionStep.motion_id == RawMotionDocument.motion_id,
                    db_models.MotionStep.step_id == RawMotionDocument.step_id,
                ),
            )
            .where(
                db_models.MotionStep.step_type == TypeMotionStep.VOTACION_O_DECISION,
                db_models.MotionStep.vote_step.is_(True),
                RawMotionDocument.last_update.is_(True),
                RawMotionDocument.processed.is_(False),
            )
            .order_by(RawMotionDocument.step_date)
        )
    else:
        raise ValueError(f"Unknown kind: {kind}")

    if max_pages is not None:
        stmt = stmt.where(
            or_(doc_model.num_pages.is_(None), doc_model.num_pages <= max_pages)
        )
    if limit is not None:
        stmt = stmt.limit(limit)

    return db.scalars(stmt).all()


def find_pending_vote_pages(
    db: Session,
    *,
    kind: Literal["bill", "motion"],
    model: str,
    limit: int | None = None,
) -> list[RawBillPage] | list[RawMotionPage]:
    """
    Pending whole-document extraction results (page_num=0 sentinel rows) for
    a given OpenAI model, not yet loaded into the clean vote tables.
    """
    page_model = RawBillPage if kind == "bill" else RawMotionPage
    id_col = page_model.bill_id if kind == "bill" else page_model.motion_id

    stmt = (
        select(page_model)
        .where(
            page_model.page_num == 0,
            page_model.ocr_model == model,
            page_model.processed.is_(False),
        )
        .order_by(id_col, page_model.step_id, page_model.file_id)
    )
    if limit is not None:
        stmt = stmt.limit(limit)

    return db.scalars(stmt).all()


def resolve_bancada_id(db: Session, party_full_name: str) -> int | None:
    """
    Resolve a bancada Organization by its full name (already resolved from a
    document's own party_summary acronym -> full-name mapping by the caller).
    """
    normalized = normalize_party_name(party_full_name)
    org = find_organization(db, org_name=normalized, org_type=TypeOrganization.BANCADA)
    return org.org_id if org is not None else None


def upsert_vote_event(
    db: Session, *, vote_event: schema.VoteEvent, org_id: int
) -> db_models.VoteEvent:
    counts = vote_event.get_counts()
    payload = {
        "org_id": org_id,
        "bill_id": vote_event.bill_id,
        "motion_id": vote_event.motion_id,
        "event_date": vote_event.event_date,
        "result": _enum_value(vote_event.result),
        "votes_in_favor": counts.get(VoteOption.SI, 0),
        "votes_against": counts.get(VoteOption.NO, 0),
        "votes_abstention": counts.get(VoteOption.ABSTENCION, 0),
    }

    existing = db.get(db_models.VoteEvent, vote_event.vote_event_id)
    if existing is None:
        obj = db_models.VoteEvent(vote_event_id=vote_event.vote_event_id, **payload)
        db.add(obj)
        db.flush()
        return obj

    for key, value in payload.items():
        setattr(existing, key, value)
    db.flush()
    return existing


def upsert_vote(
    db: Session,
    *,
    vote_event_id: str,
    voter_id: int,
    option: VoteOption | str,
    bancada_id: int | None,
) -> db_models.Vote:
    payload = {
        "vote_event_id": vote_event_id,
        "voter_id": voter_id,
        "option": _enum_value(option),
        "bancada_id": bancada_id,
    }
    existing = db.get(db_models.Vote, (vote_event_id, voter_id))
    if existing is None:
        obj = db_models.Vote(**payload)
        db.add(obj)
        db.flush()
        return obj

    for key, value in payload.items():
        setattr(existing, key, value)
    db.flush()
    return existing


def upsert_attendance(
    db: Session,
    *,
    event_id: str,
    attendee_id: int,
    status: AttendanceStatus | str,
    bancada_id: int | None = None,
) -> db_models.Attendance:
    payload = {
        "event_id": event_id,
        "attendee_id": attendee_id,
        "status": _enum_value(status),
        "bancada_id": bancada_id,
    }
    existing = db.get(db_models.Attendance, (event_id, attendee_id))
    if existing is None:
        obj = db_models.Attendance(**payload)
        db.add(obj)
        db.flush()
        return obj

    for key, value in payload.items():
        setattr(existing, key, value)
    db.flush()
    return existing


def upsert_vote_counts_for_event(
    db: Session,
    *,
    vote_event_id: str,
    counts: dict[tuple[int | None, VoteOption], int],
) -> list[db_models.VoteCounts]:
    """
    Delete-then-reinsert (not per-row upsert), so a corrected re-extraction
    doesn't leave stale bancada/option combinations behind. `counts` keys are
    the already-resolved bancada_id (per-vote, see load._persist_vote_event)
    paired with the vote option, not the raw extracted party name -- so this
    stays consistent with whatever bancada_id actually got stored on `Vote`.
    """
    db.execute(
        delete(db_models.VoteCounts).where(
            db_models.VoteCounts.vote_event_id == vote_event_id
        )
    )

    rows = []
    for (bancada_id, option), count in counts.items():
        if bancada_id is None:
            continue
        row = db_models.VoteCounts(
            vote_event_id=vote_event_id,
            option=_enum_value(option),
            bancada_id=bancada_id,
            count=count,
        )
        db.add(row)
        rows.append(row)

    db.flush()
    return rows


def clear_vote_clarifications(db: Session, vote_event_id: str) -> None:
    db.execute(
        delete(db_models.VoteClarification).where(
            db_models.VoteClarification.vote_event_id == vote_event_id
        )
    )


def upsert_vote_clarification(
    db: Session,
    *,
    vote_event_id: str,
    voter_id: int | None,
    member_name: str,
    source: str,
    note: str,
    roll_value: VoteOption | str | None,
    clarified_value: VoteOption | str | None,
) -> db_models.VoteClarification:
    row = db_models.VoteClarification(
        vote_event_id=vote_event_id,
        voter_id=voter_id,
        member_name=member_name,
        source=source,
        note=note,
        roll_value=_enum_value(roll_value) if roll_value is not None else None,
        clarified_value=_enum_value(clarified_value)
        if clarified_value is not None
        else None,
    )
    db.add(row)
    db.flush()
    return row


def clear_attendance_clarifications(db: Session, event_id: str) -> None:
    db.execute(
        delete(db_models.AttendanceClarification).where(
            db_models.AttendanceClarification.event_id == event_id
        )
    )


def upsert_attendance_clarification(
    db: Session,
    *,
    event_id: str,
    voter_id: int | None,
    member_name: str,
    note: str,
    roster_value: AttendanceStatus | str | None,
    clarified_value: AttendanceStatus | str | None,
) -> db_models.AttendanceClarification:
    row = db_models.AttendanceClarification(
        event_id=event_id,
        voter_id=voter_id,
        member_name=member_name,
        note=note,
        roster_value=_enum_value(roster_value) if roster_value is not None else None,
        clarified_value=_enum_value(clarified_value)
        if clarified_value is not None
        else None,
    )
    db.add(row)
    db.flush()
    return row


def clear_member_letters(
    db: Session, *, bill_id: str | None = None, motion_id: str | None = None
) -> None:
    stmt = delete(db_models.MemberLetter)
    if bill_id is not None:
        stmt = stmt.where(db_models.MemberLetter.bill_id == bill_id)
    elif motion_id is not None:
        stmt = stmt.where(db_models.MemberLetter.motion_id == motion_id)
    else:
        raise ValueError("Must provide bill_id or motion_id")
    db.execute(stmt)


def get_total_cost_usd(db: Session, model: str) -> float:
    """Real cumulative spend recorded for this model so far."""
    row = db.get(ModelCostLedger, model)
    return row.total_cost_usd if row is not None else 0.0


def increment_usage_ledger(
    db: Session,
    *,
    model: str,
    cost_usd: float | None,
    provider: str = "openai",
) -> None:
    """
    Atomically add to the model's running total. No-ops on None/zero cost so
    callers can pass ExtractionResult.cost_usd directly without guarding it.
    """
    if not cost_usd:
        return

    now = datetime.now(ZoneInfo("America/Lima"))
    existing = db.get(ModelCostLedger, model)
    if existing is None:
        db.add(
            ModelCostLedger(
                model=model,
                provider=provider,
                total_cost_usd=cost_usd,
                updated_at=now,
            )
        )
    else:
        existing.total_cost_usd += cost_usd
        existing.updated_at = now
    db.flush()


def get_average_cost_per_document(db: Session, *, model: str) -> float | None:
    """
    Mean of real cost_usd values already stored in page_num=0 sentinel rows
    for this model, across both bills and motions (same per-document cost
    profile regardless of kind). None if there's no history yet.
    """
    costs: list[float] = []
    for page_model in (RawBillPage, RawMotionPage):
        stmt = select(page_model.text).where(
            page_model.page_num == 0, page_model.ocr_model == model
        )
        for text in db.scalars(stmt).all():
            try:
                record = json.loads(text)
            except (ValueError, TypeError):
                continue
            cost = record.get("cost_usd")
            if cost is not None:
                costs.append(cost)

    if not costs:
        return None
    return sum(costs) / len(costs)


def upsert_member_letter(
    db: Session,
    *,
    bill_id: str | None,
    motion_id: str | None,
    voter_id: int | None,
    member_name: str,
    party: str | None,
    letter_date,
    subject_reference: str,
    requested_attendance: AttendanceStatus | str | None,
    requested_vote: VoteOption | str | None,
) -> db_models.MemberLetter:
    row = db_models.MemberLetter(
        bill_id=bill_id,
        motion_id=motion_id,
        voter_id=voter_id,
        member_name=member_name,
        party=party,
        letter_date=letter_date,
        subject_reference=subject_reference,
        requested_attendance=_enum_value(requested_attendance)
        if requested_attendance is not None
        else None,
        requested_vote=_enum_value(requested_vote)
        if requested_vote is not None
        else None,
    )
    db.add(row)
    db.flush()
    return row
