from __future__ import annotations

import json
from typing import Literal

from loguru import logger
from sqlalchemy.orm import Session

from backend import VoteOption
from backend.database.crud import pipeline_votes as crud_votes
from backend.database.crud.pipeline_core import (
    ProcessStats,
    find_active_bancada_for_person,
    find_congresista,
    find_organization,
)
from backend.process.votes import transform


def _resolve_voter_id(db: Session, member_name: str | None) -> int | None:
    if not member_name:
        return None
    cong = find_congresista(db, name=member_name)
    return cong.id if cong is not None else None


def _resolve_bancada_for_person(db: Session, person_id: int, at_date) -> int | None:
    org = find_active_bancada_for_person(db, person_id, at_date)
    return org.org_id if org is not None else None


def _persist_vote_event(
    db: Session,
    vote_event,
    bancada_cache: dict[str, int | None],
) -> bool:
    org = find_organization(
        db, org_name=vote_event.org_name, org_type=vote_event.org_type
    )
    if org is None:
        logger.warning(
            f"Chamber organization {vote_event.org_name!r} not found for "
            f"vote_event_id={vote_event.vote_event_id}"
        )
        return False

    crud_votes.upsert_vote_event(db, vote_event=vote_event, org_id=org.org_id)

    vote_counts: dict[tuple[int | None, VoteOption], int] = {}
    for vote in vote_event.votes:
        voter_id = _resolve_voter_id(db, vote.voter_full_name)
        if voter_id is None:
            logger.warning(
                f"Congresista not found for vote: {vote.voter_full_name!r} "
                f"(vote_event_id={vote_event.vote_event_id})"
            )
            continue

        bancada_id = _resolve_bancada_for_person(db, voter_id, vote_event.event_date)
        if bancada_id is None:
            # No membership row covers this date -- fall back to the party
            # acronym printed on this document's own roll call.
            if vote.bancada_name not in bancada_cache:
                bancada_cache[vote.bancada_name] = crud_votes.resolve_bancada_id(
                    db, vote.bancada_name
                )
            bancada_id = bancada_cache[vote.bancada_name]

        crud_votes.upsert_vote(
            db,
            vote_event_id=vote_event.vote_event_id,
            voter_id=voter_id,
            option=vote.option,
            bancada_id=bancada_id,
        )
        key = (bancada_id, vote.option)
        vote_counts[key] = vote_counts.get(key, 0) + 1

    for attendance in vote_event.attendance:
        attendee_id = _resolve_voter_id(db, attendance.voter_full_name)
        if attendee_id is None:
            logger.warning(
                f"Congresista not found for attendance: {attendance.voter_full_name!r} "
                f"(event_id={vote_event.vote_event_id})"
            )
            continue
        crud_votes.upsert_attendance(
            db,
            event_id=vote_event.vote_event_id,
            attendee_id=attendee_id,
            status=attendance.status,
            bancada_id=_resolve_bancada_for_person(
                db, attendee_id, vote_event.event_date
            ),
        )

    crud_votes.upsert_vote_counts_for_event(
        db, vote_event_id=vote_event.vote_event_id, counts=vote_counts
    )
    return True


def _persist_clarifications(
    db: Session,
    vote_clarifications: list,
    attendance_clarifications: list,
    vote_event_id: str,
) -> None:
    crud_votes.clear_vote_clarifications(db, vote_event_id)
    for clarification in vote_clarifications:
        crud_votes.upsert_vote_clarification(
            db,
            vote_event_id=clarification.vote_event_id,
            voter_id=_resolve_voter_id(db, clarification.member_name),
            member_name=clarification.member_name,
            source=clarification.source,
            note=clarification.note,
            roll_value=clarification.roll_value,
            clarified_value=clarification.clarified_value,
        )

    crud_votes.clear_attendance_clarifications(db, vote_event_id)
    for clarification in attendance_clarifications:
        crud_votes.upsert_attendance_clarification(
            db,
            event_id=clarification.event_id,
            voter_id=_resolve_voter_id(db, clarification.member_name),
            member_name=clarification.member_name,
            note=clarification.note,
            roster_value=clarification.roster_value,
            clarified_value=clarification.clarified_value,
        )


def _persist_member_letters(
    db: Session,
    member_letters: list,
    *,
    bill_id: str | None,
    motion_id: str | None,
) -> None:
    if not member_letters:
        return
    crud_votes.clear_member_letters(db, bill_id=bill_id, motion_id=motion_id)
    for letter in member_letters:
        crud_votes.upsert_member_letter(
            db,
            bill_id=letter.bill_id,
            motion_id=letter.motion_id,
            voter_id=_resolve_voter_id(db, letter.member_name),
            member_name=letter.member_name,
            party=letter.party,
            letter_date=letter.letter_date,
            subject_reference=letter.subject_reference,
            requested_attendance=letter.requested_attendance,
            requested_vote=letter.requested_vote,
        )


def run_vote_load(
    db: Session,
    *,
    kind: Literal["bill", "motion"],
    model: str,
    limit: int | None = None,
) -> ProcessStats:
    """
    Orchestrator-facing load stage: transforms pending page_num=0 extraction
    rows into Vote/Attendance/VoteEvent/VoteCounts (+ clarifications/letters)
    rows, always marking the page processed=True after one attempt -- a
    page that can't be resolved (no match, no step match, unmapped code) is
    logged and skipped rather than retried forever, since retrying costs no
    OpenAI spend but is otherwise pointless without a code/data fix.
    """
    stats = ProcessStats()
    pages = crud_votes.find_pending_vote_pages(db, kind=kind, model=model, limit=limit)

    for page in pages:
        target_id = page.bill_id if kind == "bill" else page.motion_id
        try:
            record = json.loads(page.text)
            parsed = record.get("parsed")

            if not parsed or not parsed.get("match_found", False):
                page.processed = True
                db.commit()
                stats.skipped += 1
                continue

            bill_id = target_id if kind == "bill" else None
            motion_id = target_id if kind == "motion" else None

            anchor_step = crud_votes.find_step_by_id(
                db, bill_id=bill_id, motion_id=motion_id, step_id=page.step_id
            )
            if anchor_step is None or not anchor_step.vote_step:
                logger.warning(
                    f"No anchor vote step for {kind} id={target_id} "
                    f"step_id={page.step_id} file_id={page.file_id}; skipping page"
                )
                page.processed = True
                db.commit()
                stats.skipped += 1
                continue

            steps = crud_votes.find_vote_steps(db, bill_id=bill_id, motion_id=motion_id)

            build_result = transform.build_vote_events(
                parsed,
                kind=kind,
                bill_id=bill_id,
                motion_id=motion_id,
                steps=steps,
                anchor_step=anchor_step,
            )

            all_ok = not build_result.skipped
            bancada_cache: dict[str, int | None] = {}
            for event_result in build_result.events:
                if event_result.vote_event is None:
                    all_ok = False
                    continue
                if not _persist_vote_event(db, event_result.vote_event, bancada_cache):
                    all_ok = False
                    continue
                _persist_clarifications(
                    db,
                    event_result.vote_clarifications,
                    event_result.attendance_clarifications,
                    event_result.vote_event.vote_event_id,
                )

            _persist_member_letters(
                db, build_result.member_letters, bill_id=bill_id, motion_id=motion_id
            )

            for reason in build_result.skipped:
                logger.warning(f"Vote load skip ({kind} id={target_id}): {reason}")

            page.processed = True
            db.commit()
            stats.processed += 1 if all_ok else 0
            stats.skipped += 0 if all_ok else 1
        except Exception as exc:
            logger.exception(
                f"Error loading vote page {kind} id={target_id} "
                f"step_id={page.step_id} file_id={page.file_id}: {exc}"
            )
            db.rollback()
            stats.errors += 1

    return stats
