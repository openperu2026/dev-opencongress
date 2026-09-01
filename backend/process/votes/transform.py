from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

from backend import AttendanceStatus, TypeOrganization, VoteOption
from backend.process import schema
from backend.process.utils import as_date, split_and_sort_name
from backend.process.votes import match

CHAMBER_ORG_NAME = "Cámara de Diputados"
CHAMBER_ORG_TYPE = TypeOrganization.CHAMBER.value

VOTE_CODE_MAP: dict[str, VoteOption] = {
    "SI+++": VoteOption.SI,
    "NO---": VoteOption.NO,
    "Abst.": VoteOption.ABSTENCION,
    "SinRes": VoteOption.SIN_RESPUESTA,
    "aus": VoteOption.AUSENTE,
    "LO": VoteOption.LICENCIA,
    "LE": VoteOption.LICENCIA,
    "LP": VoteOption.LICENCIA,
    "Sus": VoteOption.SUSPENDIDO,
    "F": VoteOption.FALLECIDO,
    "presiding": VoteOption.PRESIDING,
}

ATTENDANCE_CODE_MAP: dict[str, AttendanceStatus] = {
    "PRE": AttendanceStatus.PRESENTE,
    "aus": AttendanceStatus.AUSENTE,
    "LO": AttendanceStatus.LICENCIA,
    "LE": AttendanceStatus.LICENCIA,
    "LP": AttendanceStatus.LICENCIA,
    "Sus": AttendanceStatus.SUSPENDIDO,
    "F": AttendanceStatus.FALLECIDO,
    "presiding": AttendanceStatus.PRESIDING,
}


def _display_name(raw_name: str) -> str:
    """Roster/roll names are 'LASTNAME(S), GIVEN NAME(S)' -- convert to the
    'Firstname Lastname' convention used for Congresista.full_name elsewhere
    in the pipeline (see split_and_sort_name usage in orchestrator._process_bills)."""
    return split_and_sort_name(raw_name)[0]


def _party_map(party_summary: list[dict]) -> dict[str, str]:
    return {ps["party"]: ps["party_full_name"] for ps in party_summary or []}


@dataclass
class VoteEventResult:
    vote_event: schema.VoteEvent | None
    vote_clarifications: list[schema.VoteClarification] = field(default_factory=list)
    attendance_clarifications: list[schema.AttendanceClarification] = field(
        default_factory=list
    )
    skipped_reason: str | None = None


@dataclass
class BuildResult:
    events: list[VoteEventResult]
    member_letters: list[schema.MemberLetter]
    skipped: list[str]


def _build_votes(
    voting: dict,
    member_letters_raw: list[dict],
    vote_event_id: str,
    skipped: list[str],
) -> list[schema.Vote]:
    party_map = _party_map(voting.get("party_summary"))
    votes = []
    for roll_entry in voting.get("roll", []):
        code = match.resolve_vote_value(
            roll_entry, voting.get("clarifications", []), member_letters_raw
        )
        if code is None:
            skipped.append(
                f"vote: null code for member_name={roll_entry.get('full_name')!r}"
            )
            continue
        option = VOTE_CODE_MAP.get(code)
        if option is None:
            skipped.append(
                f"vote: unmapped code={code!r} for member_name={roll_entry.get('full_name')!r}"
            )
            continue
        party_acronym = roll_entry.get("party")
        bancada_name = party_map.get(party_acronym, party_acronym)
        votes.append(
            schema.Vote(
                vote_event_id=vote_event_id,
                voter_full_name=_display_name(roll_entry["full_name"]),
                voter_website=None,
                option=option,
                bancada_name=bancada_name,
            )
        )
    return votes


def _build_attendance(
    attendance_for_event: dict | None, event_id: str
) -> list[schema.Attendance]:
    if attendance_for_event is None:
        return []
    rows = []
    for roster_entry in attendance_for_event.get("roster", []):
        code = match.resolve_attendance_value(
            roster_entry, attendance_for_event.get("clarifications", [])
        )
        if code is None:
            continue
        status = ATTENDANCE_CODE_MAP.get(code)
        if status is None:
            continue
        rows.append(
            schema.Attendance(
                event_id=event_id,
                voter_full_name=_display_name(roster_entry["full_name"]),
                voter_website=None,
                status=status,
            )
        )
    return rows


def _build_vote_clarifications(
    voting: dict, vote_event_id: str
) -> list[schema.VoteClarification]:
    result = []
    for clarification in voting.get("clarifications", []):
        result.append(
            schema.VoteClarification(
                vote_event_id=vote_event_id,
                voter_id=None,
                member_name=clarification["member_name"],
                source=clarification["source"],
                note=clarification["note"],
                roll_value=VOTE_CODE_MAP.get(clarification.get("roll_value")),
                clarified_value=VOTE_CODE_MAP.get(clarification.get("clarified_value")),
            )
        )
    return result


def _build_attendance_clarifications(
    attendance_for_event: dict | None, event_id: str
) -> list[schema.AttendanceClarification]:
    if attendance_for_event is None:
        return []
    result = []
    for clarification in attendance_for_event.get("clarifications", []):
        result.append(
            schema.AttendanceClarification(
                event_id=event_id,
                voter_id=None,
                member_name=clarification["member_name"],
                note=clarification["note"],
                roster_value=ATTENDANCE_CODE_MAP.get(clarification.get("roster_value")),
                clarified_value=ATTENDANCE_CODE_MAP.get(
                    clarification.get("clarified_value")
                ),
            )
        )
    return result


def _build_member_letters(
    parsed: dict, *, bill_id: str | None, motion_id: str | None
) -> list[schema.MemberLetter]:
    result = []
    for letter in parsed.get("member_letters", []) or []:
        result.append(
            schema.MemberLetter(
                bill_id=bill_id,
                motion_id=motion_id,
                voter_id=None,
                member_name=letter["member_name"],
                party=letter.get("party"),
                letter_date=letter.get("letter_date") or None,
                subject_reference=letter["subject_reference"],
                requested_attendance=ATTENDANCE_CODE_MAP.get(
                    letter.get("requested_attendance")
                ),
                requested_vote=VOTE_CODE_MAP.get(letter.get("requested_vote")),
            )
        )
    return result


def build_vote_events(
    parsed: dict,
    *,
    kind: Literal["bill", "motion"],
    bill_id: str | None,
    motion_id: str | None,
    steps: list,
    anchor_step,
) -> BuildResult:
    """
    Transform one extraction result's `votings`/`attendance`/`member_letters`
    into schema.VoteEvent bundles (+ clarification/letter DTOs), matching
    each voting to an already-persisted BillStep/MotionStep vote_event_id.

    `anchor_step` is the document's own deterministic (bill_id/motion_id,
    step_id) target -- see pipeline_votes.find_step_by_id -- and is the
    default target for every voting/attendance entry. `steps` must be the
    vote_step=True rows for this bill/motion, ordered (step_date, step_id)
    -- see pipeline_votes.find_vote_steps -- and is only used to disambiguate
    multiple votings within one document. Pure/DB-free: all DB reads happen
    upstream (steps, anchor_step) and all writes happen downstream (load.py).
    """
    votings = parsed.get("votings", []) or []
    attendance = parsed.get("attendance", []) or []
    member_letters_raw = parsed.get("member_letters", []) or []
    session_date = parsed.get("session_date")

    skipped: list[str] = []

    voting_matches = match.match_votings_to_steps(
        votings, steps, anchor_step=anchor_step, fallback_date=session_date
    )
    attendance_matches = match.match_attendance_to_steps(
        attendance, voting_matches, anchor_step=anchor_step, fallback_date=session_date
    )
    attendance_by_vote_event_id = {
        step.vote_event_id: att for att, step in attendance_matches if step is not None
    }

    events: list[VoteEventResult] = []
    for voting, step in voting_matches:
        if step is None:
            skipped.append(
                f"voting: no step match for subject={voting.get('subject')!r} "
                f"record_datetime={voting.get('record_datetime')!r}"
            )
            events.append(
                VoteEventResult(vote_event=None, skipped_reason="no_step_match")
            )
            continue

        vote_event_id = step.vote_event_id
        attendance_for_event = attendance_by_vote_event_id.get(vote_event_id)

        votes = _build_votes(voting, member_letters_raw, vote_event_id, skipped)
        attendance_rows = _build_attendance(attendance_for_event, vote_event_id)

        vote_event = schema.VoteEvent(
            vote_event_id=vote_event_id,
            org_name=CHAMBER_ORG_NAME,
            org_type=CHAMBER_ORG_TYPE,
            bill_id=bill_id,
            motion_id=motion_id,
            event_date=as_date(step.step_date),
            result=match.resolve_result(voting, attendance_for_event),
            votes=votes,
            attendance=attendance_rows,
        )

        events.append(
            VoteEventResult(
                vote_event=vote_event,
                vote_clarifications=_build_vote_clarifications(voting, vote_event_id),
                attendance_clarifications=_build_attendance_clarifications(
                    attendance_for_event, vote_event_id
                ),
            )
        )

    for att, step in attendance_matches:
        if step is None:
            skipped.append(
                f"attendance: no matching voting/step for "
                f"record_datetime={att.get('record_datetime')!r}"
            )

    return BuildResult(
        events=events,
        member_letters=_build_member_letters(
            parsed, bill_id=bill_id, motion_id=motion_id
        ),
        skipped=skipped,
    )
