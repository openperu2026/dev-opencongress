from __future__ import annotations

from sqlalchemy import select, delete, func, case
from sqlalchemy.orm import Session

from backend.database import models as db_models
from backend.core.parsers import find_leg_period


def refresh_congresista_metrics(db: Session) -> int:
    """
    Rebuild congresista_metrics from the existing processed tables.
    """

    db.execute(delete(db_models.CongresistaMetric))

    attendance_sq = (
        select(
            db_models.Attendance.attendee_id.label("cong_id"),
            find_leg_period(db_models.VoteEvent.date).label("leg_period"),
            func.avg(
                case(
                    (db_models.Attendance.status == "Presente", 1.0),
                    else_=0.0,
                )
            ).label("avg_attendance"),
        )
        .join(
            db_models.VoteEvent,
            db_models.VoteEvent.vote_event_id == db_models.Attendance.event_id,
        )
        .group_by(
            db_models.Attendance.attendee_id,
            find_leg_period(db_models.VoteEvent.date),
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
            find_leg_period(bill_dates_sq.c.presentation_date).label("leg_period"),
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
        .where(db_models.BillCongresistas.role_type == "Autor")
        .group_by(
            db_models.BillCongresistas.person_id,
            find_leg_period(bill_dates_sq.c.presentation_date),
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
            find_leg_period(motion_dates_sq.c.presentation_date).label("leg_period"),
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
        .where(db_models.MotionCongresistas.role_type == "Autor")
        .group_by(
            db_models.MotionCongresistas.person_id,
            find_leg_period(motion_dates_sq.c.presentation_date),
        )
        .subquery()
    )

    rows = db.execute(
        select(
            db_models.Membership.person_id.label("cong_id"),
            db_models.Membership.leg_period.label("leg_period"),
            attendance_sq.c.avg_attendance,
            func.coalesce(bills_sq.c.bills_auth, 0).label("bills_auth"),
            bills_sq.c.bills_success_rate,
            func.coalesce(motions_sq.c.motions_auth, 0).label("motions_auth"),
            motions_sq.c.motions_success_rate,
        )
        .outerjoin(
            attendance_sq,
            (attendance_sq.c.cong_id == db_models.Membership.person_id)
            & (attendance_sq.c.leg_period == db_models.Membership.leg_period),
        )
        .outerjoin(
            bills_sq,
            (bills_sq.c.cong_id == db_models.Membership.person_id)
            & (bills_sq.c.leg_period == db_models.Membership.leg_period),
        )
        .outerjoin(
            motions_sq,
            (motions_sq.c.cong_id == db_models.Membership.person_id)
            & (motions_sq.c.leg_period == db_models.Membership.leg_period),
        )
        .group_by(
            db_models.Membership.person_id,
            db_models.Membership.leg_period,
            attendance_sq.c.avg_attendance,
            bills_sq.c.bills_auth,
            bills_sq.c.bills_success_rate,
            motions_sq.c.motions_auth,
            motions_sq.c.motions_success_rate,
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
