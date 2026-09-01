from __future__ import annotations

import difflib
from datetime import date, datetime

from backend import VoteResult

SIMILARITY_FLOOR = 0.35


def parse_record_datetime(
    value: str | None, fallback_date: str | None = None
) -> date | None:
    """
    Parse record_datetime strings like '11/05/2023 07:11 pm' (dd/mm/yyyy).
    Falls back to the top-level session_date (already YYYY-MM-DD) if the
    value is missing or fails to parse.
    """
    if value:
        for fmt in ("%d/%m/%Y %I:%M %p", "%d/%m/%Y"):
            try:
                return datetime.strptime(value.strip(), fmt).date()
            except ValueError:
                continue
    if fallback_date:
        try:
            return date.fromisoformat(fallback_date)
        except ValueError:
            return None
    return None


def _text_similarity(a: str | None, b: str | None) -> float:
    return difflib.SequenceMatcher(None, a or "", b or "").ratio()


def match_votings_to_steps(
    votings: list[dict],
    steps: list,
    *,
    anchor_step,
    fallback_date: str | None = None,
) -> list[tuple[dict, object | None]]:
    """
    Match each votings[] entry (in document order) to the BillStep/MotionStep
    row (vote_step=True) whose vote_event_id it should reuse.

    `anchor_step` is the document's own deterministic (bill_id/motion_id,
    step_id) target -- see pipeline_votes.find_step_by_id -- and is the
    default target for every voting extracted from this document, since a
    document is only ever fetched for one specific vote_step. `steps` (the
    bill's/motion's whole vote_step=True history, ordered step_date/step_id
    -- see pipeline_votes.find_vote_steps) is only consulted to disambiguate
    the rarer case of multiple votings in one document (e.g. a
    reconsideración and its revote) that fall on anchor_step's exact date;
    it is never used to match against unrelated, differently-dated steps.
    Returns (voting_dict, step) pairs in the same order as `votings` --
    every entry resolves to a step, defaulting to anchor_step.
    """
    if len(votings) <= 1:
        return [(v, anchor_step) for v in votings]

    candidate_steps = [s for s in steps if s.step_date == anchor_step.step_date]
    if anchor_step not in candidate_steps:
        candidate_steps.append(anchor_step)

    voting_dates = [
        parse_record_datetime(v.get("record_datetime"), fallback_date) for v in votings
    ]
    step_dates = [s.step_date for s in candidate_steps]

    result: list[tuple[dict, object | None] | None] = [None] * len(votings)

    all_dates = {d for d in voting_dates if d is not None} | {
        d for d in step_dates if d is not None
    }

    for target_date in all_dates:
        v_indices = [i for i, d in enumerate(voting_dates) if d == target_date]
        s_indices = [i for i, d in enumerate(step_dates) if d == target_date]
        if not v_indices or not s_indices:
            continue

        if len(v_indices) == len(s_indices):
            # Same count on the same day: zip positionally. Both lists
            # preserve chronological/document order, so this is the primary
            # disambiguation for same-day reconsideración + revote pairs.
            for vi, si in zip(v_indices, s_indices):
                result[vi] = (votings[vi], candidate_steps[si])
            continue

        # Count mismatch: fall back to greedy text-similarity matching
        # between the voting's subject and the step's step_detail.
        pairs = []
        for vi in v_indices:
            for si in s_indices:
                score = _text_similarity(
                    votings[vi].get("subject"), candidate_steps[si].step_detail
                )
                pairs.append((score, vi, si))
        pairs.sort(key=lambda p: p[0], reverse=True)

        used_v, used_s = set(), set()
        for score, vi, si in pairs:
            if vi in used_v or si in used_s or score < SIMILARITY_FLOOR:
                continue
            result[vi] = (votings[vi], candidate_steps[si])
            used_v.add(vi)
            used_s.add(si)

    for i, voting in enumerate(votings):
        if result[i] is None:
            result[i] = (voting, anchor_step)

    return result


def match_attendance_to_steps(
    attendance: list[dict],
    voting_matches: list[tuple[dict, object | None]],
    *,
    anchor_step,
    fallback_date: str | None = None,
) -> list[tuple[dict, object | None]]:
    """
    Pair each attendance[] entry to the nearest same-day matched voting's
    resolved step (and therefore its vote_event_id), defaulting to
    anchor_step -- the document's own deterministic target -- when no
    same-day voting match exists.
    """
    resolved = [(v, s) for v, s in voting_matches if s is not None]

    result = []
    for att in attendance:
        att_date = parse_record_datetime(att.get("record_datetime"), fallback_date)
        same_day = [
            s
            for v, s in resolved
            if parse_record_datetime(v.get("record_datetime"), fallback_date)
            == att_date
        ]
        result.append((att, same_day[0] if same_day else anchor_step))
    return result


def resolve_result(voting: dict, attendance_for_event: dict | None) -> VoteResult:
    """
    Compute VoteEvent.result purely from the voting's own vote counts (and,
    when available, a paired attendance call's explicit quorum flag).
    minutes[] is deliberately not used -- never guesses APROBADO on a tie or
    on missing data.
    """
    totals = voting.get("overall_totals") or {}
    favor = totals.get("si") or 0
    contra = totals.get("no") or 0

    if attendance_for_event is not None:
        att_totals = attendance_for_event.get("overall_totals") or {}
        if att_totals.get("quorum_alcanzado") is False:
            return VoteResult.NO_QUORUM

    if favor == 0 and contra == 0:
        return VoteResult.NO_QUORUM

    return VoteResult.APROBADO if favor > contra else VoteResult.RECHAZADO


def resolve_vote_value(
    roll_entry: dict,
    voting_clarifications: list[dict],
    member_letters: list[dict],
) -> str | None:
    """
    Final VoteCode for one roll[] entry, highest priority wins (system
    prompt Section 5): member letter > president/roll clarification > the
    roll value itself. The extraction is already scoped to one bill/motion,
    so member_letters here are already about the right target -- only the
    member name needs matching.
    """
    member_name = roll_entry.get("full_name")

    for letter in member_letters:
        if letter.get("member_name") == member_name:
            value = letter.get("requested_vote")
            if value is not None:
                return value

    for clarification in voting_clarifications:
        if clarification.get("member_name") == member_name:
            value = clarification.get("clarified_value")
            if value is not None:
                return value

    return roll_entry.get("vote")


def resolve_attendance_value(
    roster_entry: dict,
    attendance_clarifications: list[dict],
) -> str | None:
    """
    Final AttendanceCode for one roster[] entry: clarification override
    (president's note) > the roster value itself.
    """
    member_name = roster_entry.get("full_name")

    for clarification in attendance_clarifications:
        if clarification.get("member_name") == member_name:
            value = clarification.get("clarified_value")
            if value is not None:
                return value

    return roster_entry.get("status")
