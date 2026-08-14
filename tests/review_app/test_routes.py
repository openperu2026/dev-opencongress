from __future__ import annotations

from datetime import date, datetime
from types import SimpleNamespace

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from backend import Proponents, TypeBillStep, TypeOrganization, VoteOption, VoteResult
from backend.database.models import (
    Attendance,
    BancadaMembership,
    Base,
    Bill,
    BillStep,
    ChamberMembership,
    Congresista,
    Organization,
    Vote,
    VoteEvent,
)
from backend.database.raw_models import RawBillDocument, RawBillPage
import review_app.models  # noqa: F401 -- registers VoteReviewAudit on Base.metadata


class _NoSuchKeyError(Exception):
    pass


class FakeS3Client:
    def __init__(self, *, result=None, error=None):
        self._result = result
        self._error = error
        self.exceptions = SimpleNamespace(NoSuchKey=_NoSuchKeyError)

    def get_object(self, Bucket, Key):
        if self._error is not None:
            raise self._error
        return self._result


@pytest.fixture()
def session_factory():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    yield Session
    engine.dispose()


@pytest.fixture()
def client(monkeypatch, session_factory):
    import review_app.routes as routes_module
    from review_app.app import create_app

    monkeypatch.setattr(routes_module, "SessionLocal", session_factory)
    flask_app = create_app()
    flask_app.testing = True
    return flask_app.test_client()


@pytest.fixture()
def logged_in_client(client):
    with client.session_transaction() as sess:
        sess["reviewer_name"] = "Cesar"
    return client


def _seed_event(session_factory, *, bill_id="2021_1", vote_event_id="B_2021_1_1"):
    with session_factory() as db:
        org = Organization(org_name="Test Bancada", org_type=TypeOrganization.BANCADA)
        db.add(org)
        db.flush()
        db.add(
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
        db.add(
            BillStep(
                bill_id=bill_id,
                step_id=1,
                step_type=TypeBillStep.VOTACION,
                vote_step=True,
                vote_event_id=vote_event_id,
                step_date=date(2021, 1, 1),
                step_detail="d",
            )
        )
        db.add(
            VoteEvent(
                vote_event_id=vote_event_id,
                org_id=org.org_id,
                bill_id=bill_id,
                motion_id=None,
                event_date=date(2021, 1, 1),
                result=VoteResult.APROBADO,
                votes_in_favor=1,
                votes_against=0,
                votes_abstention=0,
            )
        )
        c = Congresista(full_name="Jane Doe", photo_url="x", website="x")
        db.add(c)
        db.flush()
        db.add(
            Vote(
                vote_event_id=vote_event_id,
                voter_id=c.id,
                option=VoteOption.SI,
                bancada_id=org.org_id,
            )
        )
        db.commit()
        return c.id


def _seed_document(
    session_factory, *, bill_id, step_id, file_id, s3_key, url="http://x"
):
    with session_factory() as db:
        db.add(
            RawBillDocument(
                bill_id=bill_id,
                step_id=step_id,
                file_id=file_id,
                step_date=datetime(2021, 1, 1),
                url=url,
                s3_key=s3_key,
                last_update=True,
                changed=True,
                processed=True,
                timestamp=datetime(2021, 1, 1),
            )
        )
        db.add(
            RawBillPage(
                bill_id=bill_id,
                step_id=step_id,
                file_id=file_id,
                page_num=0,
                text='{"parsed": {"match_found": true}}',
                ocr_model="m",
                last_update=True,
                changed=True,
                processed=True,
                timestamp=datetime(2021, 1, 1),
            )
        )
        db.commit()


def _seed_roster_event(
    session_factory, *, bill_id="2021_9", vote_event_id="B_2021_9_1"
):
    """A vote event with a CHAMBER org and a full roster: one member who
    voted, one who didn't (should still show up), and a third
    congresista not in the roster at all (available to "add")."""
    with session_factory() as db:
        chamber = Organization(org_name="Congreso", org_type=TypeOrganization.CHAMBER)
        fp = Organization(org_name="Fuerza Popular", org_type=TypeOrganization.BANCADA)
        db.add_all([chamber, fp])
        db.flush()
        db.add(
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
        db.add(
            BillStep(
                bill_id=bill_id,
                step_id=1,
                step_type=TypeBillStep.VOTACION,
                vote_step=True,
                vote_event_id=vote_event_id,
                step_date=date(2021, 1, 1),
                step_detail="d",
            )
        )
        db.add(
            VoteEvent(
                vote_event_id=vote_event_id,
                org_id=chamber.org_id,
                bill_id=bill_id,
                motion_id=None,
                event_date=date(2021, 1, 1),
                result=VoteResult.APROBADO,
                votes_in_favor=1,
                votes_against=0,
                votes_abstention=0,
            )
        )
        voted = Congresista(
            full_name="Ana Torres",
            first_name="Ana",
            last_name="Torres",
            photo_url="x",
            website="x",
        )
        not_voted = Congresista(
            full_name="Beto Beta",
            first_name="Beto",
            last_name="Beta",
            photo_url="x",
            website="x",
        )
        addable = Congresista(
            full_name="Carla Gomez",
            first_name="Carla",
            last_name="Gomez",
            photo_url="x",
            website="x",
        )
        db.add_all([voted, not_voted, addable])
        db.flush()
        for person in (voted, not_voted):
            db.add(
                ChamberMembership(
                    person_id=person.id,
                    org_id=chamber.org_id,
                    leg_period="p",
                    role="miembro",
                    start_date=date(2021, 1, 1),
                    end_date=date(2026, 1, 1),
                )
            )
        db.add(
            BancadaMembership(
                person_id=voted.id,
                org_id=fp.org_id,
                leg_period="p",
                role="miembro",
                start_date=date(2021, 1, 1),
                end_date=date(2026, 1, 1),
            )
        )
        db.add(
            Vote(
                vote_event_id=vote_event_id,
                voter_id=voted.id,
                option=VoteOption.SI,
                bancada_id=None,
            )
        )
        db.commit()
        return voted.id, not_voted.id, addable.id


# ---------------------------------------------------------------------------
# GET /review
# ---------------------------------------------------------------------------


def test_search_redirects_to_gate_without_reviewer_name(client, session_factory):
    _seed_event(session_factory)
    r = client.get("/review")
    assert r.status_code == 200
    assert b"Who" in r.data


def test_search_lists_events_when_logged_in(logged_in_client, session_factory):
    _seed_event(session_factory)
    r = logged_in_client.get("/review")
    assert b"B_2021_1_1" in r.data


def test_search_q_filter(logged_in_client, session_factory):
    _seed_event(session_factory, bill_id="2021_1", vote_event_id="B_2021_1_1")
    _seed_event(session_factory, bill_id="2021_2", vote_event_id="B_2021_2_1")
    r = logged_in_client.get("/review?q=2021_2")
    assert b"B_2021_2_1" in r.data
    assert b"B_2021_1_1" not in r.data


def test_search_empty_result_renders_cleanly(logged_in_client):
    r = logged_in_client.get("/review?q=nope")
    assert r.status_code == 200
    assert b"No vote events match" in r.data


# ---------------------------------------------------------------------------
# GET /review/<id>
# ---------------------------------------------------------------------------


def test_detail_unknown_event_404(logged_in_client):
    r = logged_in_client.get("/review/DOES_NOT_EXIST")
    assert r.status_code == 404


def test_detail_resolved_document_shows_iframe(logged_in_client, session_factory):
    _seed_event(session_factory)
    _seed_document(
        session_factory, bill_id="2021_1", step_id=1, file_id=1, s3_key="doc.pdf"
    )
    r = logged_in_client.get("/review/B_2021_1_1")
    assert r.status_code == 200
    assert b"<iframe" in r.data
    assert b"Jane Doe" in r.data


def test_detail_s3_key_missing_shows_fallback_banner(logged_in_client, session_factory):
    _seed_event(session_factory)
    _seed_document(
        session_factory,
        bill_id="2021_1",
        step_id=1,
        file_id=1,
        s3_key=None,
        url="http://source",
    )
    r = logged_in_client.get("/review/B_2021_1_1")
    assert b"not yet archived" in r.data
    assert b"http://source" in r.data


def test_detail_no_document_found_shows_message(logged_in_client, session_factory):
    _seed_event(session_factory)
    r = logged_in_client.get("/review/B_2021_1_1")
    assert b"No source document found" in r.data


def test_detail_requires_reviewer_name(client, session_factory):
    _seed_event(session_factory)
    r = client.get("/review/B_2021_1_1")
    assert b"Who" in r.data


def test_detail_shows_full_roster_including_unvoted_member(
    logged_in_client, session_factory
):
    _seed_roster_event(session_factory)
    r = logged_in_client.get("/review/B_2021_9_1")
    assert r.status_code == 200
    assert b"Torres, Ana" in r.data
    assert b"Beta, Beto" in r.data  # in roster, no vote yet -- still shown
    assert b"not recorded" in r.data


def test_detail_shows_addable_congresista_not_in_roster(
    logged_in_client, session_factory
):
    _seed_roster_event(session_factory)
    r = logged_in_client.get("/review/B_2021_9_1")
    assert b"Gomez, Carla" in r.data  # not in roster, offered in the add dropdown


def test_detail_shows_vote_summary_panel(logged_in_client, session_factory):
    _seed_roster_event(session_factory)
    r = logged_in_client.get("/review/B_2021_9_1")
    assert b"Fuerza Popular" in r.data
    assert b"TOTAL" in r.data


def test_detail_save_form_posts_to_save_route(logged_in_client, session_factory):
    """Regression test: the review-form's action must point at the
    /save route, not back at the detail page's own URL (which only
    allows GET and would 405 on submit) -- the route-level save() tests
    all POST directly to the right URL string and never would have
    caught this, since they bypass the rendered template entirely."""
    _seed_roster_event(session_factory)
    r = logged_in_client.get("/review/B_2021_9_1")
    assert b'action="/review/B_2021_9_1/save' in r.data


# ---------------------------------------------------------------------------
# GET /review/<id>/document
# ---------------------------------------------------------------------------


def test_document_streams_s3_object(monkeypatch, logged_in_client, session_factory):
    import review_app.routes as routes_module

    _seed_event(session_factory)
    _seed_document(
        session_factory, bill_id="2021_1", step_id=1, file_id=1, s3_key="doc.pdf"
    )

    fake_client = FakeS3Client(
        result={
            "Body": SimpleNamespace(read=lambda: b"%PDF-1.4"),
            "ContentType": "application/pdf",
        }
    )
    monkeypatch.setattr(routes_module.boto3, "client", lambda *a, **kw: fake_client)
    monkeypatch.setattr(routes_module.settings, "AWS_S3_BUCKET_NAME", "test-bucket")
    monkeypatch.setattr(routes_module.settings, "AWS_ACCESS_KEY_ID", None)
    monkeypatch.setattr(routes_module.settings, "AWS_SECRET_ACCESS_KEY", None)

    r = logged_in_client.get("/review/B_2021_1_1/document")
    assert r.status_code == 200
    assert r.data == b"%PDF-1.4"
    assert r.headers["Content-Type"] == "application/pdf"
    assert "inline" in r.headers["Content-Disposition"]


def test_document_no_such_key_returns_404(
    monkeypatch, logged_in_client, session_factory
):
    import review_app.routes as routes_module

    _seed_event(session_factory)
    _seed_document(
        session_factory, bill_id="2021_1", step_id=1, file_id=1, s3_key="missing.pdf"
    )

    fake_client = FakeS3Client(error=_NoSuchKeyError())
    monkeypatch.setattr(routes_module.boto3, "client", lambda *a, **kw: fake_client)
    monkeypatch.setattr(routes_module.settings, "AWS_S3_BUCKET_NAME", "test-bucket")
    monkeypatch.setattr(routes_module.settings, "AWS_ACCESS_KEY_ID", None)
    monkeypatch.setattr(routes_module.settings, "AWS_SECRET_ACCESS_KEY", None)

    r = logged_in_client.get("/review/B_2021_1_1/document")
    assert r.status_code == 404


def test_document_other_s3_error_returns_502(
    monkeypatch, logged_in_client, session_factory
):
    import review_app.routes as routes_module

    _seed_event(session_factory)
    _seed_document(
        session_factory, bill_id="2021_1", step_id=1, file_id=1, s3_key="doc.pdf"
    )

    fake_client = FakeS3Client(error=RuntimeError("boom"))
    monkeypatch.setattr(routes_module.boto3, "client", lambda *a, **kw: fake_client)
    monkeypatch.setattr(routes_module.settings, "AWS_S3_BUCKET_NAME", "test-bucket")
    monkeypatch.setattr(routes_module.settings, "AWS_ACCESS_KEY_ID", None)
    monkeypatch.setattr(routes_module.settings, "AWS_SECRET_ACCESS_KEY", None)

    r = logged_in_client.get("/review/B_2021_1_1/document")
    assert r.status_code == 502


def test_document_bucket_not_configured_returns_404(
    monkeypatch, logged_in_client, session_factory
):
    import review_app.routes as routes_module

    _seed_event(session_factory)
    _seed_document(
        session_factory, bill_id="2021_1", step_id=1, file_id=1, s3_key="doc.pdf"
    )
    monkeypatch.setattr(routes_module.settings, "AWS_S3_BUCKET_NAME", None)

    r = logged_in_client.get("/review/B_2021_1_1/document")
    assert r.status_code == 404


def test_document_no_document_found_returns_404(logged_in_client, session_factory):
    _seed_event(session_factory)
    r = logged_in_client.get("/review/B_2021_1_1/document")
    assert r.status_code == 404


# ---------------------------------------------------------------------------
# POST /review/<id>/save
# ---------------------------------------------------------------------------


def test_save_changed_value_writes_correction(logged_in_client, session_factory):
    congresista_id = _seed_event(session_factory)
    r = logged_in_client.post(
        "/review/B_2021_1_1/save", data={f"vote-{congresista_id}": "No"}
    )
    assert r.status_code == 302

    with session_factory() as db:
        v = db.get(Vote, ("B_2021_1_1", congresista_id))
        assert v.option.value == "No"


def test_save_unchanged_value_is_noop(logged_in_client, session_factory):
    congresista_id = _seed_event(session_factory)
    r = logged_in_client.post(
        "/review/B_2021_1_1/save", data={f"vote-{congresista_id}": "Sí"}
    )
    assert r.status_code == 302

    with session_factory() as db:
        from review_app.models import VoteReviewAudit

        assert db.query(VoteReviewAudit).count() == 0


def test_save_target_not_in_roster_returns_400(logged_in_client, session_factory):
    _seed_event(session_factory)
    r = logged_in_client.post("/review/B_2021_1_1/save", data={"vote-999999": "No"})
    assert r.status_code == 400


def test_save_invalid_enum_value_returns_400(logged_in_client, session_factory):
    congresista_id = _seed_event(session_factory)
    r = logged_in_client.post(
        "/review/B_2021_1_1/save", data={f"vote-{congresista_id}": "NotAValue"}
    )
    assert r.status_code == 400


def test_save_flag_checkbox_no_value_change_records_flag_only(
    logged_in_client, session_factory
):
    congresista_id = _seed_event(session_factory)
    r = logged_in_client.post(
        "/review/B_2021_1_1/save", data={f"flag-{congresista_id}": "on"}
    )
    assert r.status_code == 302

    with session_factory() as db:
        from review_app.models import VoteReviewAudit

        audits = db.query(VoteReviewAudit).all()
        assert len(audits) == 1
        assert audits[0].action == "flagged"
        assert audits[0].old_value is None


def test_save_verified_checkbox_no_value_change_records_verified_only(
    logged_in_client, session_factory
):
    congresista_id = _seed_event(session_factory)
    r = logged_in_client.post(
        "/review/B_2021_1_1/save", data={f"verified-{congresista_id}": "on"}
    )
    assert r.status_code == 302

    with session_factory() as db:
        from review_app.models import VoteReviewAudit

        audits = db.query(VoteReviewAudit).all()
        assert len(audits) == 1
        assert audits[0].action == "verified"


def test_save_requires_reviewer_name(client, session_factory):
    congresista_id = _seed_event(session_factory)
    r = client.post("/review/B_2021_1_1/save", data={f"vote-{congresista_id}": "No"})
    assert b"Who" in r.data


def test_save_unknown_event_404(logged_in_client):
    r = logged_in_client.post("/review/DOES_NOT_EXIST/save", data={"vote-1": "No"})
    assert r.status_code == 404


def test_save_blank_value_removes_existing_vote(logged_in_client, session_factory):
    voted_id, _, _ = _seed_roster_event(session_factory)
    r = logged_in_client.post("/review/B_2021_9_1/save", data={f"vote-{voted_id}": ""})
    assert r.status_code == 302

    with session_factory() as db:
        assert db.get(Vote, ("B_2021_9_1", voted_id)) is None


def test_save_blank_value_for_unrecorded_member_is_noop(
    logged_in_client, session_factory
):
    _, not_voted_id, _ = _seed_roster_event(session_factory)
    r = logged_in_client.post(
        "/review/B_2021_9_1/save", data={f"vote-{not_voted_id}": ""}
    )
    assert r.status_code == 302

    with session_factory() as db:
        from review_app.models import VoteReviewAudit

        assert db.query(VoteReviewAudit).count() == 0


# ---------------------------------------------------------------------------
# POST /review/<id>/add_congresista
# ---------------------------------------------------------------------------


def test_add_congresista_creates_vote_row(logged_in_client, session_factory):
    _, _, addable_id = _seed_roster_event(session_factory)
    r = logged_in_client.post(
        "/review/B_2021_9_1/add_congresista",
        data={"congresista_id": str(addable_id), "vote_option": "No"},
    )
    assert r.status_code == 302

    with session_factory() as db:
        v = db.get(Vote, ("B_2021_9_1", addable_id))
        assert v is not None and v.option.value == "No"


def test_add_congresista_appears_in_detail_after_adding(
    logged_in_client, session_factory
):
    _, _, addable_id = _seed_roster_event(session_factory)
    logged_in_client.post(
        "/review/B_2021_9_1/add_congresista",
        data={"congresista_id": str(addable_id), "attendance_status": "Presente"},
    )
    r = logged_in_client.get("/review/B_2021_9_1")
    assert b"Gomez, Carla" in r.data


def test_add_congresista_requires_at_least_one_value(logged_in_client, session_factory):
    _, not_voted_id, _ = _seed_roster_event(session_factory)
    r = logged_in_client.post(
        "/review/B_2021_9_1/add_congresista", data={"congresista_id": str(not_voted_id)}
    )
    assert r.status_code == 400


def test_add_congresista_unknown_congresista_returns_400(
    logged_in_client, session_factory
):
    _seed_roster_event(session_factory)
    r = logged_in_client.post(
        "/review/B_2021_9_1/add_congresista",
        data={"congresista_id": "999999", "vote_option": "No"},
    )
    assert r.status_code == 400


def test_add_congresista_invalid_enum_returns_400(logged_in_client, session_factory):
    _, _, addable_id = _seed_roster_event(session_factory)
    r = logged_in_client.post(
        "/review/B_2021_9_1/add_congresista",
        data={"congresista_id": str(addable_id), "vote_option": "NotAValue"},
    )
    assert r.status_code == 400


def test_add_congresista_requires_reviewer_name(client, session_factory):
    _, _, addable_id = _seed_roster_event(session_factory)
    r = client.post(
        "/review/B_2021_9_1/add_congresista",
        data={"congresista_id": str(addable_id), "vote_option": "No"},
    )
    assert b"Who" in r.data


def test_add_congresista_unknown_event_404(logged_in_client, session_factory):
    _, _, addable_id = _seed_roster_event(session_factory)
    r = logged_in_client.post(
        "/review/DOES_NOT_EXIST/add_congresista",
        data={"congresista_id": str(addable_id), "vote_option": "No"},
    )
    assert r.status_code == 404


def test_add_congresista_multiple_rows_in_one_submission(
    logged_in_client, session_factory
):
    _, _, addable_id = _seed_roster_event(session_factory)
    with session_factory() as db:
        second = Congresista(
            full_name="D D", first_name="D", last_name="D", photo_url="x", website="x"
        )
        db.add(second)
        db.commit()
        second_id = second.id

    r = logged_in_client.post(
        "/review/B_2021_9_1/add_congresista",
        data={
            "congresista_id": [str(addable_id), str(second_id)],
            "vote_option": ["No", ""],
            "attendance_status": ["", "Presente"],
        },
    )
    assert r.status_code == 302

    with session_factory() as db:
        v = db.get(Vote, ("B_2021_9_1", addable_id))
        a = db.get(Attendance, ("B_2021_9_1", second_id))
        assert v is not None and v.option.value == "No"
        assert a is not None and a.status.value == "Presente"


def test_add_congresista_unused_extra_row_is_skipped(logged_in_client, session_factory):
    """The '+ Add another' control can leave a trailing row with no
    congresista picked at all -- that row is silently skipped, not an
    error, as long as at least one other row has something to add."""
    _, _, addable_id = _seed_roster_event(session_factory)
    r = logged_in_client.post(
        "/review/B_2021_9_1/add_congresista",
        data={
            "congresista_id": [str(addable_id), ""],
            "vote_option": ["No", ""],
            "attendance_status": ["", ""],
        },
    )
    assert r.status_code == 302
    with session_factory() as db:
        assert db.get(Vote, ("B_2021_9_1", addable_id)) is not None


def test_add_congresista_partial_row_skipped_others_still_added(
    logged_in_client, session_factory
):
    """A row where a person was picked but no value at all was given is
    skipped on its own -- it does not fail the whole batch."""
    _, _, addable_id = _seed_roster_event(session_factory)
    with session_factory() as db:
        second = Congresista(
            full_name="D D", first_name="D", last_name="D", photo_url="x", website="x"
        )
        db.add(second)
        db.commit()
        second_id = second.id

    r = logged_in_client.post(
        "/review/B_2021_9_1/add_congresista",
        data={
            "congresista_id": [str(addable_id), str(second_id)],
            "vote_option": ["No", ""],
            "attendance_status": ["", ""],
        },
    )
    assert r.status_code == 302

    with session_factory() as db:
        assert db.get(Vote, ("B_2021_9_1", addable_id)) is not None
        assert db.get(Vote, ("B_2021_9_1", second_id)) is None
        assert db.get(Attendance, ("B_2021_9_1", second_id)) is None


def test_add_congresista_mismatched_field_counts_returns_400(
    logged_in_client, session_factory
):
    _seed_roster_event(session_factory)
    r = logged_in_client.post(
        "/review/B_2021_9_1/add_congresista",
        data={"congresista_id": ["1", "2"], "vote_option": ["Sí"]},
    )
    assert r.status_code == 400


def test_add_congresista_all_rows_blank_returns_400(logged_in_client, session_factory):
    _seed_roster_event(session_factory)
    r = logged_in_client.post(
        "/review/B_2021_9_1/add_congresista",
        data={
            "congresista_id": ["", ""],
            "vote_option": ["", ""],
            "attendance_status": ["", ""],
        },
    )
    assert r.status_code == 400


# ---------------------------------------------------------------------------
# POST /review/set_reviewer
# ---------------------------------------------------------------------------


def test_set_reviewer_valid_name(client):
    r = client.post(
        "/review/set_reviewer", data={"reviewer_name": "Cesar", "next_url": "/review"}
    )
    assert r.status_code == 302
    with client.session_transaction() as sess:
        assert sess["reviewer_name"] == "Cesar"


def test_set_reviewer_empty_name_rejected(client):
    r = client.post(
        "/review/set_reviewer", data={"reviewer_name": "   ", "next_url": "/review"}
    )
    assert r.status_code == 400
    with client.session_transaction() as sess:
        assert "reviewer_name" not in sess
