import json
from datetime import date, datetime

import pytest

from backend import (
    AttendanceStatus,
    Proponents,
    TypeBillStep,
    TypeMotion,
    TypeMotionStep,
    TypeOrganization,
    VoteOption,
    VoteResult,
)
from backend.database.crud import review as crud_review
from backend.database.models import (
    Attendance,
    BancadaMembership,
    Bill,
    BillStep,
    ChamberMembership,
    Congresista,
    Motion,
    MotionStep,
    Organization,
    Vote,
    VoteEvent,
)
from backend.database.raw_models import (
    RawBillDocument,
    RawBillPage,
    RawMotionDocument,
    RawMotionPage,
)
from review_app.models import VoteReviewAudit


def _seed_org(session, name="Test Bancada"):
    org = Organization(org_name=name, org_type=TypeOrganization.BANCADA)
    session.add(org)
    session.flush()
    return org


def _seed_chamber_org(session, name="Congreso"):
    org = Organization(org_name=name, org_type=TypeOrganization.CHAMBER)
    session.add(org)
    session.flush()
    return org


def _seed_chamber_membership(
    session, *, person_id, org_id, start=date(2021, 1, 1), end=date(2026, 1, 1)
):
    session.add(
        ChamberMembership(
            person_id=person_id,
            org_id=org_id,
            leg_period="p",
            role="miembro",
            start_date=start,
            end_date=end,
        )
    )


def _seed_bancada_membership(
    session, *, person_id, org_id, start=date(2021, 1, 1), end=date(2026, 1, 1)
):
    session.add(
        BancadaMembership(
            person_id=person_id,
            org_id=org_id,
            leg_period="p",
            role="miembro",
            start_date=start,
            end_date=end,
        )
    )


def _seed_bill_event(
    session, *, org_id, bill_id="2021_1", step_id=1, vote_event_id=None
):
    vote_event_id = vote_event_id or f"B_{bill_id}_1"
    session.add(
        Bill(
            id=bill_id,
            title="t",
            summary_congreso="",
            observations="",
            status="x",
            proponent=Proponents.CONGRESO,
            bill_approved=False,
            summary_oc="",
            pley_id=bill_id,
        )
    )
    session.add(
        BillStep(
            bill_id=bill_id,
            step_id=step_id,
            step_type=TypeBillStep.VOTACION,
            vote_step=True,
            vote_event_id=vote_event_id,
            step_date=date(2021, 1, 1),
            step_detail="d",
        )
    )
    event = VoteEvent(
        vote_event_id=vote_event_id,
        org_id=org_id,
        bill_id=bill_id,
        motion_id=None,
        event_date=date(2021, 1, 1),
        result=VoteResult.APROBADO,
        votes_in_favor=1,
        votes_against=0,
        votes_abstention=0,
    )
    session.add(event)
    session.flush()
    return event


def _seed_motion_event(
    session, *, org_id, motion_id="M1", step_id=1, vote_event_id=None
):
    vote_event_id = vote_event_id or f"M_{motion_id}_1"
    session.add(
        Motion(
            id=motion_id,
            motion_type=TypeMotion.OTRAS,
            summary_congreso="",
            observations="",
            status="x",
            motion_approved=False,
            summary_oc="",
        )
    )
    session.add(
        MotionStep(
            motion_id=motion_id,
            step_id=step_id,
            step_type=TypeMotionStep.VOTACION_O_DECISION,
            vote_step=True,
            vote_event_id=vote_event_id,
            step_date=date(2021, 1, 1),
            step_detail="d",
        )
    )
    event = VoteEvent(
        vote_event_id=vote_event_id,
        org_id=org_id,
        bill_id=None,
        motion_id=motion_id,
        event_date=date(2021, 1, 1),
        result=VoteResult.APROBADO,
        votes_in_favor=1,
        votes_against=0,
        votes_abstention=0,
    )
    session.add(event)
    session.flush()
    return event


def _seed_bill_page(
    session, *, bill_id, step_id, file_id, match_found, ocr_model="m", ts=None
):
    ts = ts or datetime(2021, 1, 1)
    session.add(
        RawBillPage(
            bill_id=bill_id,
            step_id=step_id,
            file_id=file_id,
            page_num=0,
            text=json.dumps({"parsed": {"match_found": match_found}}),
            ocr_model=ocr_model,
            last_update=True,
            changed=True,
            processed=True,
            timestamp=ts,
        )
    )


def _seed_bill_document(
    session, *, bill_id, step_id, file_id, s3_key=None, url="http://x", ts=None
):
    ts = ts or datetime(2021, 1, 1)
    session.add(
        RawBillDocument(
            bill_id=bill_id,
            step_id=step_id,
            file_id=file_id,
            step_date=ts,
            url=url,
            s3_key=s3_key,
            last_update=True,
            changed=True,
            processed=True,
            timestamp=ts,
        )
    )


def _seed_motion_page(
    session, *, motion_id, step_id, file_id, match_found, ocr_model="m", ts=None
):
    ts = ts or datetime(2021, 1, 1)
    session.add(
        RawMotionPage(
            motion_id=motion_id,
            step_id=step_id,
            file_id=file_id,
            page_num=0,
            text=json.dumps({"parsed": {"match_found": match_found}}),
            ocr_model=ocr_model,
            last_update=True,
            changed=True,
            processed=True,
            timestamp=ts,
        )
    )


def _seed_motion_document(
    session, *, motion_id, step_id, file_id, s3_key=None, url="http://x", ts=None
):
    ts = ts or datetime(2021, 1, 1)
    session.add(
        RawMotionDocument(
            motion_id=motion_id,
            step_id=step_id,
            file_id=file_id,
            step_date=ts,
            url=url,
            s3_key=s3_key,
            last_update=True,
            changed=True,
            processed=True,
            timestamp=ts,
        )
    )


def _seed_congresista(session, full_name="Jane Doe", first_name=None, last_name=None):
    c = Congresista(
        full_name=full_name,
        first_name=first_name,
        last_name=last_name,
        photo_url="x",
        website="x",
    )
    session.add(c)
    session.flush()
    return c


# ---------------------------------------------------------------------------
# find_document_for_vote_event
# ---------------------------------------------------------------------------


def test_find_document_event_not_found(session):
    assert crud_review.find_document_for_vote_event(session, "does-not-exist") is None


def test_find_document_bill_step_missing(session):
    org = _seed_org(session)
    # VoteEvent with no matching BillStep row.
    session.add(
        Bill(
            id="2021_9",
            title="t",
            summary_congreso="",
            observations="",
            status="x",
            proponent=Proponents.CONGRESO,
            bill_approved=False,
            summary_oc="",
            pley_id="2021_9",
        )
    )
    session.add(
        VoteEvent(
            vote_event_id="B_2021_9_1",
            org_id=org.org_id,
            bill_id="2021_9",
            motion_id=None,
            event_date=date(2021, 1, 1),
            result=VoteResult.APROBADO,
            votes_in_favor=0,
            votes_against=0,
            votes_abstention=0,
        )
    )
    session.flush()
    assert crud_review.find_document_for_vote_event(session, "B_2021_9_1") is None


def test_find_document_zero_matches_falls_back_to_last_update(session):
    org = _seed_org(session)
    event = _seed_bill_event(session, org_id=org.org_id, bill_id="2021_2")
    _seed_bill_document(
        session, bill_id="2021_2", step_id=1, file_id=1, s3_key="fallback.pdf"
    )
    _seed_bill_page(session, bill_id="2021_2", step_id=1, file_id=1, match_found=False)
    session.flush()

    result = crud_review.find_document_for_vote_event(session, event.vote_event_id)
    assert result.s3_key == "fallback.pdf"


def test_find_document_exactly_one_match_resolves_that_document(session):
    org = _seed_org(session)
    event = _seed_bill_event(session, org_id=org.org_id, bill_id="2021_3")
    _seed_bill_document(
        session, bill_id="2021_3", step_id=1, file_id=1, s3_key="no_match.pdf"
    )
    _seed_bill_page(session, bill_id="2021_3", step_id=1, file_id=1, match_found=False)
    _seed_bill_document(
        session,
        bill_id="2021_3",
        step_id=1,
        file_id=2,
        s3_key="matched.pdf",
        ts=datetime(2021, 1, 2),
    )
    _seed_bill_page(
        session,
        bill_id="2021_3",
        step_id=1,
        file_id=2,
        match_found=True,
        ts=datetime(2021, 1, 2),
    )
    session.flush()

    result = crud_review.find_document_for_vote_event(session, event.vote_event_id)
    assert result.s3_key == "matched.pdf"


def test_find_document_more_than_one_match_is_ambiguous(session):
    org = _seed_org(session)
    event = _seed_bill_event(session, org_id=org.org_id, bill_id="2021_4")
    for file_id in (1, 2):
        _seed_bill_document(
            session,
            bill_id="2021_4",
            step_id=1,
            file_id=file_id,
            s3_key=f"{file_id}.pdf",
        )
        _seed_bill_page(
            session, bill_id="2021_4", step_id=1, file_id=file_id, match_found=True
        )
    session.flush()

    assert (
        crud_review.find_document_for_vote_event(session, event.vote_event_id)
        == "ambiguous"
    )


def test_find_document_s3_key_empty_still_resolves_document_row(session):
    org = _seed_org(session)
    event = _seed_bill_event(session, org_id=org.org_id, bill_id="2021_5")
    _seed_bill_document(
        session, bill_id="2021_5", step_id=1, file_id=1, s3_key=None, url="http://real"
    )
    _seed_bill_page(session, bill_id="2021_5", step_id=1, file_id=1, match_found=True)
    session.flush()

    result = crud_review.find_document_for_vote_event(session, event.vote_event_id)
    assert result.s3_key is None
    assert result.url == "http://real"


def test_find_document_missing_entirely_returns_none(session):
    org = _seed_org(session)
    event = _seed_bill_event(session, org_id=org.org_id, bill_id="2021_6")
    session.flush()
    assert (
        crud_review.find_document_for_vote_event(session, event.vote_event_id) is None
    )


def test_find_document_motion_fork_mirrors_bill_fork(session):
    org = _seed_org(session)
    event = _seed_motion_event(session, org_id=org.org_id, motion_id="M2")
    _seed_motion_document(
        session, motion_id="M2", step_id=1, file_id=1, s3_key="no_match.pdf"
    )
    _seed_motion_page(session, motion_id="M2", step_id=1, file_id=1, match_found=False)
    _seed_motion_document(
        session,
        motion_id="M2",
        step_id=1,
        file_id=2,
        s3_key="matched.pdf",
        ts=datetime(2021, 1, 2),
    )
    _seed_motion_page(
        session,
        motion_id="M2",
        step_id=1,
        file_id=2,
        match_found=True,
        ts=datetime(2021, 1, 2),
    )
    session.flush()

    result = crud_review.find_document_for_vote_event(session, event.vote_event_id)
    assert result.s3_key == "matched.pdf"


# ---------------------------------------------------------------------------
# search_review_queue
# ---------------------------------------------------------------------------


def test_search_review_queue_no_filters_orders_by_date_desc(session):
    org = _seed_org(session)
    _seed_bill_event(
        session, org_id=org.org_id, bill_id="2021_10", vote_event_id="B_2021_10_1"
    )
    e2 = VoteEvent(
        vote_event_id="B_2021_10_2",
        org_id=org.org_id,
        bill_id="2021_10",
        motion_id=None,
        event_date=date(2021, 6, 1),
        result=VoteResult.APROBADO,
        votes_in_favor=0,
        votes_against=0,
        votes_abstention=0,
    )
    session.add(e2)
    session.flush()

    results = crud_review.search_review_queue(session)
    assert [r.vote_event_id for r in results][:2] == ["B_2021_10_2", "B_2021_10_1"]


def test_search_review_queue_q_matches_vote_event_id(session):
    org = _seed_org(session)
    _seed_bill_event(session, org_id=org.org_id, bill_id="2021_11")
    results = crud_review.search_review_queue(session, q="2021_11")
    assert len(results) == 1


def test_search_review_queue_q_matches_bill_id_substring(session):
    org = _seed_org(session)
    _seed_bill_event(session, org_id=org.org_id, bill_id="2021_12")
    results = crud_review.search_review_queue(session, q="2021_12")
    assert results[0].bill_id == "2021_12"


def test_search_review_queue_date_range(session):
    org = _seed_org(session)
    _seed_bill_event(session, org_id=org.org_id, bill_id="2021_13")
    in_range = crud_review.search_review_queue(
        session, date_from=date(2020, 1, 1), date_to=date(2022, 1, 1)
    )
    out_of_range = crud_review.search_review_queue(
        session, date_from=date(2022, 1, 1), date_to=date(2023, 1, 1)
    )
    assert any(r.bill_id == "2021_13" for r in in_range)
    assert not any(r.bill_id == "2021_13" for r in out_of_range)


def test_search_review_queue_org_id_filter(session):
    org1 = _seed_org(session, "Org1")
    org2 = _seed_org(session, "Org2")
    _seed_bill_event(session, org_id=org1.org_id, bill_id="2021_14")
    _seed_bill_event(session, org_id=org2.org_id, bill_id="2021_15")

    results = crud_review.search_review_queue(session, org_id=org1.org_id)
    assert {r.bill_id for r in results} == {"2021_14"}


def test_search_review_queue_pagination_empty_page(session):
    org = _seed_org(session)
    _seed_bill_event(session, org_id=org.org_id, bill_id="2021_16")
    results = crud_review.search_review_queue(session, limit=10, offset=100)
    assert results == []


# ---------------------------------------------------------------------------
# get_review_rows
# ---------------------------------------------------------------------------


def test_get_review_rows_vote_only(session):
    org = _seed_org(session)
    event = _seed_bill_event(session, org_id=org.org_id, bill_id="2021_20")
    c = _seed_congresista(session)
    session.add(
        Vote(
            vote_event_id=event.vote_event_id,
            voter_id=c.id,
            option=VoteOption.SI,
            bancada_id=org.org_id,
        )
    )
    session.flush()

    rows = crud_review.get_review_rows(session, event.vote_event_id)
    assert len(rows) == 1
    assert rows[0].vote_option == "Sí"
    assert rows[0].attendance_status is None
    assert rows[0].bancada_name == org.org_name


def test_get_review_rows_attendance_only(session):
    org = _seed_org(session)
    event = _seed_bill_event(session, org_id=org.org_id, bill_id="2021_21")
    c = _seed_congresista(session)
    session.add(
        Attendance(
            event_id=event.vote_event_id,
            attendee_id=c.id,
            status=AttendanceStatus.PRESENTE,
            bancada_id=org.org_id,
        )
    )
    session.flush()

    rows = crud_review.get_review_rows(session, event.vote_event_id)
    assert len(rows) == 1
    assert rows[0].attendance_status == "Presente"
    assert rows[0].vote_option is None


def test_get_review_rows_both_vote_and_attendance(session):
    org = _seed_org(session)
    event = _seed_bill_event(session, org_id=org.org_id, bill_id="2021_22")
    c = _seed_congresista(session)
    session.add(
        Vote(
            vote_event_id=event.vote_event_id,
            voter_id=c.id,
            option=VoteOption.SI,
            bancada_id=org.org_id,
        )
    )
    session.add(
        Attendance(
            event_id=event.vote_event_id,
            attendee_id=c.id,
            status=AttendanceStatus.PRESENTE,
            bancada_id=org.org_id,
        )
    )
    session.flush()

    rows = crud_review.get_review_rows(session, event.vote_event_id)
    assert len(rows) == 1
    assert rows[0].vote_option == "Sí"
    assert rows[0].attendance_status == "Presente"


def test_get_review_rows_null_bancada(session):
    org = _seed_org(session)
    event = _seed_bill_event(session, org_id=org.org_id, bill_id="2021_23")
    c = _seed_congresista(session)
    session.add(
        Vote(
            vote_event_id=event.vote_event_id,
            voter_id=c.id,
            option=VoteOption.SI,
            bancada_id=None,
        )
    )
    session.flush()

    rows = crud_review.get_review_rows(session, event.vote_event_id)
    assert rows[0].bancada_name is None


def test_get_review_rows_display_name_is_last_first(session):
    org = _seed_org(session)
    event = _seed_bill_event(session, org_id=org.org_id, bill_id="2021_25")
    c = _seed_congresista(
        session, full_name="Ana Torres", first_name="Ana", last_name="Torres"
    )
    session.add(
        Vote(
            vote_event_id=event.vote_event_id,
            voter_id=c.id,
            option=VoteOption.SI,
            bancada_id=org.org_id,
        )
    )
    session.flush()

    rows = crud_review.get_review_rows(session, event.vote_event_id)
    assert rows[0].display_name == "Torres, Ana"


def test_get_review_rows_display_name_falls_back_to_full_name(session):
    org = _seed_org(session)
    event = _seed_bill_event(session, org_id=org.org_id, bill_id="2021_26")
    c = _seed_congresista(session, full_name="Only Full Name")
    session.add(
        Vote(
            vote_event_id=event.vote_event_id,
            voter_id=c.id,
            option=VoteOption.SI,
            bancada_id=org.org_id,
        )
    )
    session.flush()

    rows = crud_review.get_review_rows(session, event.vote_event_id)
    assert rows[0].display_name == "Only Full Name"


def test_get_review_rows_sorted_alphabetically_by_last_name(session):
    org = _seed_org(session)
    event = _seed_bill_event(session, org_id=org.org_id, bill_id="2021_27")
    zeta = _seed_congresista(
        session, full_name="Ana Zeta", first_name="Ana", last_name="Zeta"
    )
    beta = _seed_congresista(
        session, full_name="Beto Beta", first_name="Beto", last_name="Beta"
    )
    alfa = _seed_congresista(
        session, full_name="Carlos Alfa", first_name="Carlos", last_name="Alfa"
    )
    for c in (zeta, beta, alfa):
        session.add(
            Vote(
                vote_event_id=event.vote_event_id,
                voter_id=c.id,
                option=VoteOption.SI,
                bancada_id=org.org_id,
            )
        )
    session.flush()

    rows = crud_review.get_review_rows(session, event.vote_event_id)
    assert [r.display_name for r in rows] == ["Alfa, Carlos", "Beta, Beto", "Zeta, Ana"]


def test_get_review_rows_latest_action_lookup(session):
    org = _seed_org(session)
    event = _seed_bill_event(session, org_id=org.org_id, bill_id="2021_24")
    c = _seed_congresista(session)
    session.add(
        Vote(
            vote_event_id=event.vote_event_id,
            voter_id=c.id,
            option=VoteOption.SI,
            bancada_id=org.org_id,
        )
    )
    session.flush()

    valid_ids = {c.id}
    crud_review.record_review_action(
        session,
        vote_event_id=event.vote_event_id,
        target_type="vote",
        target_id=c.id,
        action="flagged",
        reviewer_name="A",
        valid_target_ids=valid_ids,
    )
    crud_review.record_review_action(
        session,
        vote_event_id=event.vote_event_id,
        target_type="vote",
        target_id=c.id,
        action="verified",
        reviewer_name="A",
        valid_target_ids=valid_ids,
    )

    rows = crud_review.get_review_rows(session, event.vote_event_id)
    # Most recent action wins ("verified" was written after "flagged").
    assert rows[0].vote_action == "verified"


def test_get_review_rows_no_event_returns_empty(session):
    assert crud_review.get_review_rows(session, "does-not-exist") == []


def test_get_review_rows_includes_roster_member_with_no_vote_or_attendance(session):
    chamber = _seed_chamber_org(session)
    event = _seed_bill_event(session, org_id=chamber.org_id, bill_id="2021_50")
    voted = _seed_congresista(session, "Voted Person", "Voted", "Person")
    not_voted = _seed_congresista(session, "Blank Row", "Blank", "Row")
    _seed_chamber_membership(session, person_id=voted.id, org_id=chamber.org_id)
    _seed_chamber_membership(session, person_id=not_voted.id, org_id=chamber.org_id)
    session.add(
        Vote(
            vote_event_id=event.vote_event_id,
            voter_id=voted.id,
            option=VoteOption.SI,
            bancada_id=None,
        )
    )
    session.flush()

    rows = crud_review.get_review_rows(session, event.vote_event_id)
    names = {r.display_name for r in rows}
    assert names == {"Person, Voted", "Row, Blank"}
    blank = next(r for r in rows if r.display_name == "Row, Blank")
    assert blank.vote_option is None
    assert blank.attendance_status is None


def test_get_review_rows_includes_out_of_roster_erroneous_entry(session):
    chamber = _seed_chamber_org(session)
    event = _seed_bill_event(session, org_id=chamber.org_id, bill_id="2021_51")
    in_roster = _seed_congresista(session, "In Roster", "In", "Roster")
    wrong_person = _seed_congresista(session, "Wrong Person", "Wrong", "Person")
    _seed_chamber_membership(session, person_id=in_roster.id, org_id=chamber.org_id)
    # wrong_person has NO membership in this org at all -- an extraction error.
    session.add(
        Vote(
            vote_event_id=event.vote_event_id,
            voter_id=wrong_person.id,
            option=VoteOption.NO,
            bancada_id=None,
        )
    )
    session.flush()

    rows = crud_review.get_review_rows(session, event.vote_event_id)
    names = {r.display_name for r in rows}
    assert names == {"Roster, In", "Person, Wrong"}
    wrong = next(r for r in rows if r.display_name == "Person, Wrong")
    assert wrong.vote_option == "No"


def test_get_review_rows_bancada_resolved_from_membership(session):
    chamber = _seed_chamber_org(session)
    fp = _seed_org(session, "Fuerza Popular")
    event = _seed_bill_event(session, org_id=chamber.org_id, bill_id="2021_52")
    c = _seed_congresista(session, "Ana Torres", "Ana", "Torres")
    _seed_chamber_membership(session, person_id=c.id, org_id=chamber.org_id)
    _seed_bancada_membership(session, person_id=c.id, org_id=fp.org_id)
    session.flush()

    rows = crud_review.get_review_rows(session, event.vote_event_id)
    assert rows[0].bancada_name == "Fuerza Popular"


def test_get_review_rows_bancada_falls_back_to_extraction_snapshot(session):
    chamber = _seed_chamber_org(session)
    old_party = _seed_org(session, "Old Party")
    event = _seed_bill_event(session, org_id=chamber.org_id, bill_id="2021_53")
    c = _seed_congresista(session, "No Membership", "No", "Membership")
    # No BancadaMembership row for `c` at all -- only the extraction-time
    # snapshot on the Vote row itself.
    session.add(
        Vote(
            vote_event_id=event.vote_event_id,
            voter_id=c.id,
            option=VoteOption.SI,
            bancada_id=old_party.org_id,
        )
    )
    session.flush()

    rows = crud_review.get_review_rows(session, event.vote_event_id)
    assert rows[0].bancada_name == "Old Party"


# ---------------------------------------------------------------------------
# summarize_votes
# ---------------------------------------------------------------------------


def test_summarize_votes_counts_by_party_and_option(session):
    chamber = _seed_chamber_org(session)
    fp = _seed_org(session, "Fuerza Popular")
    event = _seed_bill_event(session, org_id=chamber.org_id, bill_id="2021_54")
    a = _seed_congresista(session, "A A", "A", "A")
    b = _seed_congresista(session, "B B", "B", "B")
    c = _seed_congresista(session, "C C", "C", "C")
    for person in (a, b, c):
        _seed_chamber_membership(session, person_id=person.id, org_id=chamber.org_id)
        _seed_bancada_membership(session, person_id=person.id, org_id=fp.org_id)
    session.add(
        Vote(
            vote_event_id=event.vote_event_id,
            voter_id=a.id,
            option=VoteOption.SI,
            bancada_id=None,
        )
    )
    session.add(
        Vote(
            vote_event_id=event.vote_event_id,
            voter_id=b.id,
            option=VoteOption.SI,
            bancada_id=None,
        )
    )
    session.add(
        Vote(
            vote_event_id=event.vote_event_id,
            voter_id=c.id,
            option=VoteOption.NO,
            bancada_id=None,
        )
    )
    session.flush()

    rows = crud_review.get_review_rows(session, event.vote_event_id)
    summary = crud_review.summarize_votes(rows)

    assert summary["Fuerza Popular"]["Sí"] == 2
    assert summary["Fuerza Popular"]["No"] == 1
    assert summary["TOTAL"]["Sí"] == 2
    assert summary["TOTAL"]["No"] == 1
    assert list(summary.keys())[-1] == "TOTAL"


def test_summarize_votes_unrecorded_bucket(session):
    chamber = _seed_chamber_org(session)
    event = _seed_bill_event(session, org_id=chamber.org_id, bill_id="2021_55")
    c = _seed_congresista(session, "No Vote Yet", "No", "Vote")
    _seed_chamber_membership(session, person_id=c.id, org_id=chamber.org_id)
    session.flush()

    rows = crud_review.get_review_rows(session, event.vote_event_id)
    summary = crud_review.summarize_votes(rows)
    assert summary["Sin bancada"]["Sin registrar"] == 1
    assert summary["TOTAL"]["Sin registrar"] == 1


# ---------------------------------------------------------------------------
# apply_correction
# ---------------------------------------------------------------------------


def test_apply_correction_vote_changed_writes_audit_row(session):
    org = _seed_org(session)
    event = _seed_bill_event(session, org_id=org.org_id, bill_id="2021_30")
    c = _seed_congresista(session)
    session.add(
        Vote(
            vote_event_id=event.vote_event_id,
            voter_id=c.id,
            option=VoteOption.SI,
            bancada_id=org.org_id,
        )
    )
    session.flush()

    audit = crud_review.apply_correction(
        session,
        vote_event_id=event.vote_event_id,
        target_type="vote",
        target_id=c.id,
        new_value="No",
        reviewer_name="Cesar",
        valid_target_ids={c.id},
    )
    assert audit is not None
    assert audit.old_value == "Sí"
    assert audit.new_value == "No"
    assert session.get(Vote, (event.vote_event_id, c.id)).option.value == "No"


def test_apply_correction_vote_unchanged_is_noop(session):
    org = _seed_org(session)
    event = _seed_bill_event(session, org_id=org.org_id, bill_id="2021_31")
    c = _seed_congresista(session)
    session.add(
        Vote(
            vote_event_id=event.vote_event_id,
            voter_id=c.id,
            option=VoteOption.SI,
            bancada_id=org.org_id,
        )
    )
    session.flush()

    audit = crud_review.apply_correction(
        session,
        vote_event_id=event.vote_event_id,
        target_type="vote",
        target_id=c.id,
        new_value="Sí",
        reviewer_name="Cesar",
        valid_target_ids={c.id},
    )
    assert audit is None
    assert session.query(VoteReviewAudit).count() == 0


def test_apply_correction_attendance_changed_and_unchanged(session):
    org = _seed_org(session)
    event = _seed_bill_event(session, org_id=org.org_id, bill_id="2021_32")
    c = _seed_congresista(session)
    session.add(
        Attendance(
            event_id=event.vote_event_id,
            attendee_id=c.id,
            status=AttendanceStatus.PRESENTE,
            bancada_id=org.org_id,
        )
    )
    session.flush()

    changed = crud_review.apply_correction(
        session,
        vote_event_id=event.vote_event_id,
        target_type="attendance",
        target_id=c.id,
        new_value="Ausente",
        reviewer_name="Cesar",
        valid_target_ids={c.id},
    )
    assert changed is not None
    assert (
        session.get(Attendance, (event.vote_event_id, c.id)).status.value == "Ausente"
    )

    unchanged = crud_review.apply_correction(
        session,
        vote_event_id=event.vote_event_id,
        target_type="attendance",
        target_id=c.id,
        new_value="Ausente",
        reviewer_name="Cesar",
        valid_target_ids={c.id},
    )
    assert unchanged is None


def test_apply_correction_target_not_in_roster_raises(session):
    org = _seed_org(session)
    event = _seed_bill_event(session, org_id=org.org_id, bill_id="2021_33")
    session.flush()

    with pytest.raises(ValueError):
        crud_review.apply_correction(
            session,
            vote_event_id=event.vote_event_id,
            target_type="vote",
            target_id=999,
            new_value="No",
            reviewer_name="Cesar",
            valid_target_ids=set(),
        )
    assert session.query(Vote).count() == 0
    assert session.query(VoteReviewAudit).count() == 0


def test_apply_correction_new_value_none_removes_existing_row(session):
    org = _seed_org(session)
    event = _seed_bill_event(session, org_id=org.org_id, bill_id="2021_34")
    c = _seed_congresista(session)
    session.add(
        Vote(
            vote_event_id=event.vote_event_id,
            voter_id=c.id,
            option=VoteOption.SI,
            bancada_id=org.org_id,
        )
    )
    session.flush()

    audit = crud_review.apply_correction(
        session,
        vote_event_id=event.vote_event_id,
        target_type="vote",
        target_id=c.id,
        new_value=None,
        reviewer_name="Cesar",
        valid_target_ids={c.id},
    )
    assert audit is not None
    assert audit.old_value == "Sí"
    assert audit.new_value is None
    assert session.get(Vote, (event.vote_event_id, c.id)) is None


def test_apply_correction_new_value_none_when_absent_is_noop(session):
    org = _seed_org(session)
    event = _seed_bill_event(session, org_id=org.org_id, bill_id="2021_35")
    c = _seed_congresista(session)
    session.flush()

    audit = crud_review.apply_correction(
        session,
        vote_event_id=event.vote_event_id,
        target_type="vote",
        target_id=c.id,
        new_value=None,
        reviewer_name="Cesar",
        valid_target_ids={c.id},
    )
    assert audit is None
    assert session.query(VoteReviewAudit).count() == 0


def test_apply_correction_adds_row_for_congresista_outside_normal_roster(session):
    """The explicit 'add a congresista' action bypasses the computed
    roster entirely -- the caller passes {target_id} directly as
    valid_target_ids, since the whole point is adding someone the
    automatic roster/extraction never surfaced."""
    org = _seed_org(session)
    event = _seed_bill_event(session, org_id=org.org_id, bill_id="2021_36")
    c = _seed_congresista(session, "Added Later", "Added", "Later")
    session.flush()

    audit = crud_review.apply_correction(
        session,
        vote_event_id=event.vote_event_id,
        target_type="attendance",
        target_id=c.id,
        new_value="Presente",
        reviewer_name="Cesar",
        valid_target_ids={c.id},
    )
    assert audit.old_value is None
    assert audit.new_value == "Presente"
    assert (
        session.get(Attendance, (event.vote_event_id, c.id)).status.value == "Presente"
    )


# ---------------------------------------------------------------------------
# record_review_action
# ---------------------------------------------------------------------------


def test_record_review_action_flagged(session):
    org = _seed_org(session)
    event = _seed_bill_event(session, org_id=org.org_id, bill_id="2021_40")
    c = _seed_congresista(session)
    session.flush()

    audit = crud_review.record_review_action(
        session,
        vote_event_id=event.vote_event_id,
        target_type="attendance",
        target_id=c.id,
        action="flagged",
        reviewer_name="Cesar",
        valid_target_ids={c.id},
    )
    assert audit.action == "flagged"
    assert audit.old_value is None
    assert audit.new_value is None


def test_record_review_action_verified(session):
    org = _seed_org(session)
    event = _seed_bill_event(session, org_id=org.org_id, bill_id="2021_41")
    c = _seed_congresista(session)
    session.flush()

    audit = crud_review.record_review_action(
        session,
        vote_event_id=event.vote_event_id,
        target_type="vote",
        target_id=c.id,
        action="verified",
        reviewer_name="Cesar",
        valid_target_ids={c.id},
    )
    assert audit.action == "verified"


def test_record_review_action_target_not_in_roster_raises(session):
    org = _seed_org(session)
    event = _seed_bill_event(session, org_id=org.org_id, bill_id="2021_42")
    session.flush()

    with pytest.raises(ValueError):
        crud_review.record_review_action(
            session,
            vote_event_id=event.vote_event_id,
            target_type="vote",
            target_id=999,
            action="flagged",
            reviewer_name="Cesar",
            valid_target_ids=set(),
        )
    assert session.query(VoteReviewAudit).count() == 0
