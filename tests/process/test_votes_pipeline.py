from datetime import date

import pytest

from backend import (
    AttendanceStatus,
    LegPeriod,
    Proponents,
    RoleOrganization,
    TypeBillStep,
    TypeOrganization,
    VoteOption,
    VoteResult,
)
from backend.database import models as db_models
from backend.database.crud import pipeline_votes as crud_votes
from backend.process.votes import load, transform


@pytest.fixture()
def bill_vote_fixture(session):
    session.add(
        db_models.Bill(
            id="B_2021_1",
            title="Ley de prueba",
            summary_congreso="Resumen",
            observations="",
            status="Aprobado",
            proponent=Proponents.CONGRESO,
            author_id=None,
            bill_approved=True,
            summary_oc="",
            pley_id="05665/2023-CR",
        )
    )
    session.add(
        db_models.BillStep(
            bill_id="B_2021_1",
            step_id=10,
            step_type=TypeBillStep.VOTACION,
            vote_step=True,
            vote_event_id="B_2021_1_1",
            step_date=date(2023, 5, 11),
            step_detail="Primera votación",
        )
    )
    chamber = db_models.Organization(
        org_name="Cámara de Diputados", org_type=TypeOrganization.CHAMBER
    )
    bancada = db_models.Organization(
        org_name="Fuerza Popular", org_type=TypeOrganization.BANCADA
    )
    session.add_all([chamber, bancada])

    session.add_all(
        [
            db_models.Congresista(
                full_name="Ana Torres",
                photo_url="https://x/a.jpg",
                website="https://x/a",
            ),
            db_models.Congresista(
                full_name="Luis Fernandez",
                photo_url="https://x/b.jpg",
                website="https://x/b",
            ),
        ]
    )
    session.flush()
    return session


def _base_parsed():
    return {
        "file_name": "test.pdf",
        "legislature": "Segunda Legislatura Ordinaria 2022-2023",
        "session_date": "2023-05-11",
        "requested_pley_id": "05665/2023-CR",
        "match_found": True,
        "attendance": [
            {
                "record_datetime": "11/05/2023 07:00 pm",
                "roster": [
                    {"party": "FP", "full_name": "TORRES, Ana", "status": "PRE"},
                    {"party": "FP", "full_name": "FERNANDEZ, Luis", "status": "aus"},
                ],
                "overall_totals": {"quorum_alcanzado": True},
                "party_summary": [{"party": "FP", "party_full_name": "Fuerza Popular"}],
                "clarifications": [],
            }
        ],
        "votings": [
            {
                "record_datetime": "11/05/2023 07:11 pm",
                "president": "Someone Presiding",
                "subject": "Primera votación",
                "roll": [
                    {"party": "FP", "full_name": "TORRES, Ana", "vote": "SI+++"},
                    {"party": "FP", "full_name": "FERNANDEZ, Luis", "vote": "aus"},
                ],
                "overall_totals": {"si": 1, "no": 0},
                "party_summary": [{"party": "FP", "party_full_name": "Fuerza Popular"}],
                "clarifications": [],
            }
        ],
        "minutes": [
            {
                "raw_text": "should be ignored",
                "events": [
                    {
                        "type": "primera_votacion",
                        "description": "x",
                        "result": "rechazado",  # deliberately contradicts the counts
                        "favor": None,
                        "contra": None,
                        "abstenciones": None,
                    }
                ],
            }
        ],
        "member_letters": [],
        "_uncertain_fields": [],
    }


def test_build_and_persist_vote_event(bill_vote_fixture):
    db = bill_vote_fixture
    parsed = _base_parsed()
    steps = crud_votes.find_vote_steps(db, bill_id="B_2021_1")
    assert len(steps) == 1

    build_result = transform.build_vote_events(
        parsed, kind="bill", bill_id="B_2021_1", motion_id=None, steps=steps
    )

    assert not build_result.skipped
    assert len(build_result.events) == 1
    event_result = build_result.events[0]
    vote_event = event_result.vote_event
    assert vote_event is not None
    assert vote_event.vote_event_id == "B_2021_1_1"
    # minutes[] says "rechazado" -- must be ignored; counts (1 si, 0 no) -> APROBADO.
    assert vote_event.result == VoteResult.APROBADO
    assert len(vote_event.votes) == 2
    assert len(vote_event.attendance) == 2

    bancada_cache: dict[str, int | None] = {}
    ok = load._persist_vote_event(db, vote_event, bancada_cache)
    assert ok
    db.flush()

    db_event = db.get(db_models.VoteEvent, "B_2021_1_1")
    assert db_event is not None
    assert db_event.result == VoteResult.APROBADO
    assert db_event.votes_in_favor == 1
    assert db_event.votes_against == 0

    ana = db.query(db_models.Congresista).filter_by(full_name="Ana Torres").one()
    luis = db.query(db_models.Congresista).filter_by(full_name="Luis Fernandez").one()

    ana_vote = db.get(db_models.Vote, ("B_2021_1_1", ana.id))
    assert ana_vote.option == VoteOption.SI
    luis_vote = db.get(db_models.Vote, ("B_2021_1_1", luis.id))
    assert luis_vote.option == VoteOption.AUSENTE

    ana_attendance = db.get(db_models.Attendance, ("B_2021_1_1", ana.id))
    assert ana_attendance.status == AttendanceStatus.PRESENTE
    luis_attendance = db.get(db_models.Attendance, ("B_2021_1_1", luis.id))
    assert luis_attendance.status == AttendanceStatus.AUSENTE

    bancada = (
        db.query(db_models.Organization).filter_by(org_name="Fuerza Popular").one()
    )
    assert ana_vote.bancada_id == bancada.org_id

    counts = db.query(db_models.VoteCounts).filter_by(vote_event_id="B_2021_1_1").all()
    counts_by_option = {c.option: c.count for c in counts}
    assert counts_by_option[VoteOption.SI] == 1
    assert counts_by_option[VoteOption.AUSENTE] == 1


def test_persist_vote_event_prefers_membership_over_pdf_text(bill_vote_fixture):
    db = bill_vote_fixture
    parsed = _base_parsed()
    steps = crud_votes.find_vote_steps(db, bill_id="B_2021_1")

    # Ana's PDF roll call says "FP" (Fuerza Popular), but she has an active
    # BancadaMembership in a different bancada covering the vote's date --
    # that membership must win over the PDF-text fuzzy match. Luis has no
    # membership row at all, so his Vote falls back to the PDF text, while
    # his Attendance (no fallback available) stays unresolved.
    renovacion = db_models.Organization(
        org_name="Renovación Popular", org_type=TypeOrganization.BANCADA
    )
    db.add(renovacion)
    db.flush()

    ana = db.query(db_models.Congresista).filter_by(full_name="Ana Torres").one()
    db.add(
        db_models.BancadaMembership(
            person_id=ana.id,
            org_id=renovacion.org_id,
            leg_period=LegPeriod.PERIODO_2021_2026.value,
            org_type=TypeOrganization.BANCADA,
            role=RoleOrganization.MIEMBRO,
            start_date=date(2023, 1, 1),
            end_date=date(2023, 12, 31),
        )
    )
    db.flush()

    build_result = transform.build_vote_events(
        parsed, kind="bill", bill_id="B_2021_1", motion_id=None, steps=steps
    )
    vote_event = build_result.events[0].vote_event

    bancada_cache: dict[str, int | None] = {}
    assert load._persist_vote_event(db, vote_event, bancada_cache)
    db.flush()

    fuerza_popular = (
        db.query(db_models.Organization).filter_by(org_name="Fuerza Popular").one()
    )
    luis = db.query(db_models.Congresista).filter_by(full_name="Luis Fernandez").one()

    ana_vote = db.get(db_models.Vote, ("B_2021_1_1", ana.id))
    assert ana_vote.bancada_id == renovacion.org_id

    luis_vote = db.get(db_models.Vote, ("B_2021_1_1", luis.id))
    assert luis_vote.bancada_id == fuerza_popular.org_id

    ana_attendance = db.get(db_models.Attendance, ("B_2021_1_1", ana.id))
    assert ana_attendance.bancada_id == renovacion.org_id

    luis_attendance = db.get(db_models.Attendance, ("B_2021_1_1", luis.id))
    assert luis_attendance.bancada_id is None

    counts = db.query(db_models.VoteCounts).filter_by(vote_event_id="B_2021_1_1").all()
    counts_by_bancada_option = {(c.bancada_id, c.option): c.count for c in counts}
    assert counts_by_bancada_option[(renovacion.org_id, VoteOption.SI)] == 1
    assert counts_by_bancada_option[(fuerza_popular.org_id, VoteOption.AUSENTE)] == 1


def test_member_letter_overrides_roll_value(bill_vote_fixture):
    db = bill_vote_fixture
    parsed = _base_parsed()
    parsed["member_letters"] = [
        {
            "member_name": "FERNANDEZ, Luis",
            "party": "FP",
            "letter_date": "2023-05-10",
            "subject_reference": "Primera votación",
            "requested_attendance": None,
            "requested_vote": "NO---",
        }
    ]
    steps = crud_votes.find_vote_steps(db, bill_id="B_2021_1")

    build_result = transform.build_vote_events(
        parsed, kind="bill", bill_id="B_2021_1", motion_id=None, steps=steps
    )
    assert len(build_result.member_letters) == 1

    vote_event = build_result.events[0].vote_event
    # split_and_sort_name only reorders "SURNAME, Given" -> "Given SURNAME";
    # it doesn't re-case the surname (that's left to find_congresista's fuzzy
    # match at load time), so the roster's "FERNANDEZ, Luis" becomes this.
    votes_by_name = {v.voter_full_name: v.option for v in vote_event.votes}
    # The letter overrides Luis's roll value of "aus" with an explicit "NO---".
    assert votes_by_name["Luis FERNANDEZ"] == VoteOption.NO


def test_no_step_match_is_skipped(bill_vote_fixture):
    db = bill_vote_fixture
    parsed = _base_parsed()
    parsed["votings"][0]["record_datetime"] = "12/05/2023 07:11 pm"  # different day
    steps = crud_votes.find_vote_steps(db, bill_id="B_2021_1")

    build_result = transform.build_vote_events(
        parsed, kind="bill", bill_id="B_2021_1", motion_id=None, steps=steps
    )

    assert build_result.events[0].vote_event is None
    assert build_result.skipped
    assert "no step match" in build_result.skipped[0]
