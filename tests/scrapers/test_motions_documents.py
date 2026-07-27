import json
import base64
from datetime import datetime, timezone

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from backend.database.raw_models import Base as RawBase, RawMotion, RawMotionDocument
from backend.scrapers import motions_documents as motions_documents_module
from backend.scrapers.motions_documents import (
    RawMotionDocumentScraper,
    BASE_URL,
)


def _setup_inmemory_db():
    """
    Helper to create an in-memory SQLite DB with the raw models.
    """
    engine = create_engine("sqlite:///:memory:")
    RawBase.metadata.create_all(engine)
    SessionLocal = sessionmaker(bind=engine)
    return engine, SessionLocal


# --------------------------------------------------------------------------------------
# filter_steps
# --------------------------------------------------------------------------------------


def test_filter_steps_skips_existing_steps(monkeypatch):
    """
    filter_steps should drop steps whose seguimientoId is already in the DB.
    """
    engine, SessionLocal = _setup_inmemory_db()

    scraper = RawMotionDocumentScraper()
    scraper.engine = engine
    scraper.Session = SessionLocal

    motion_id = "2021_1"

    # Insert one existing RawMotionDocument with step_id = 10
    with SessionLocal() as session:
        session.add(
            RawMotionDocument(
                motion_id=motion_id,
                step_id=10,
                file_id=111,
                step_date=datetime.now(),
                url="http://example.com/existing.pdf",
                s3_key="some_aws_s3_key",
                local_path="~/some/local/path",
                timestamp=datetime.now(),
            )
        )
        session.commit()

    extracted_steps = [
        {
            "seguimientoId": 10,  # already in DB -> should be filtered out
        },
        {
            "seguimientoId": 11,  # new -> should remain
        },
    ]

    filtered = scraper.filter_steps(extracted_steps, motion_id=motion_id)

    assert len(filtered) == 1
    assert filtered[0]["seguimientoId"] == 11


# --------------------------------------------------------------------------------------
# get_motion_documents
# --------------------------------------------------------------------------------------


def test_get_motion_documents_populates_urls(monkeypatch):
    """
    get_motion_documents should:
      - fetch the latest RawMotion
      - filter/prioritize steps
      - populate scraper.documents with RawMotionDocument objects
    """
    engine, SessionLocal = _setup_inmemory_db()

    scraper = RawMotionDocumentScraper()
    scraper.engine = engine
    scraper.Session = SessionLocal

    motion_id = "2021_1"
    step_date_str = "2021-01-01T12:00:00.000000+0000"

    steps = [
        {
            "seguimientoId": 10,
            "desEstadoMocion": "Aprobada",  # in PRIORITIES
            "fecSeguimiento": step_date_str,
            "adjuntos": [
                {
                    "seguimientoAdjuntoId": 111,
                    "seguimientoId": 10,
                }
            ],
        }
    ]

    with SessionLocal() as session:
        session.add(
            RawMotion(
                id=motion_id,
                timestamp=datetime.now(timezone.utc),
                # assuming these fields exist and are nullable
                general=None,
                congresistas=None,
                steps=json.dumps(steps),
            )
        )
        session.commit()

    scraper.get_motion_documents(motion_id=motion_id)

    # One document should have been created
    assert len(scraper.documents) == 1
    doc = scraper.documents[0]
    assert isinstance(doc, RawMotionDocument)

    # URL should match the BASE_URL + encoded id
    expected_b64 = base64.b64encode(str(111).encode()).decode()
    expected_url = f"{BASE_URL}/seguimiento-adjunto/{expected_b64}/pdf"
    assert doc.url == expected_url
    assert doc.motion_id == motion_id
    assert doc.step_id == "10"
    assert doc.file_id == "111"
    assert doc.s3_key is None
    # Check that step_date was parsed correctly
    assert doc.step_date == datetime.strptime(step_date_str, "%Y-%m-%dT%H:%M:%S.%f%z")


# --------------------------------------------------------------------------------------
# add_documents_to_db / load_raw_documents
# --------------------------------------------------------------------------------------


def test_add_documents_to_db_persists_urls(monkeypatch):
    """
    add_documents_to_db should insert all documents in scraper.documents
    and return True on success.
    """
    engine, SessionLocal = _setup_inmemory_db()

    scraper = RawMotionDocumentScraper()
    scraper.engine = engine
    scraper.Session = SessionLocal

    motion_id = "2021_3"

    # Manually populate scraper.documents with two docs
    scraper.documents = [
        RawMotionDocument(
            motion_id="2021_3",
            step_id=10,
            file_id=111,
            step_date=datetime.now(),
            url="http://example.com/1.pdf",
            s3_key="some_aws_s3_key",
            local_path="~/some/local/path",
            timestamp=datetime.now(),
        ),
        RawMotionDocument(
            motion_id="2021_3",
            step_id=10,
            file_id=123,
            step_date=datetime.now(),
            url="http://example.com/2.pdf",
            s3_key="some_aws_s3_key",
            local_path="~/some/local/path",
            timestamp=datetime.now(),
        ),
    ]

    success = scraper.add_documents_to_db()
    assert success is True

    # Verify they are really in the DB
    with SessionLocal() as session:
        docs = session.query(RawMotionDocument).filter_by(motion_id=motion_id).all()
        assert len(docs) == 2
        urls = {d.url for d in docs}
        assert "http://example.com/1.pdf" in urls
        assert "http://example.com/2.pdf" in urls


def test_load_raw_documents_calls_add_and_resets_urls(monkeypatch):
    """
    load_raw_documents should call add_documents_to_db and then reset urls.
    """
    engine, SessionLocal = _setup_inmemory_db()

    scraper = RawMotionDocumentScraper()
    scraper.engine = engine
    scraper.Session = SessionLocal

    # Put one doc in urls
    scraper.documents = [
        RawMotionDocument(
            motion_id="2021_3",
            step_id=10,
            file_id=123,
            step_date=datetime.now(),
            url="http://example.com/2.pdf",
            s3_key="some_aws_s3_key",
            local_path="~/some/local/path",
            timestamp=datetime.now(),
        )
    ]

    # Spy on add_documents_to_db
    called = {}

    def fake_add():
        called["called"] = True
        return True

    monkeypatch.setattr(scraper, "add_documents_to_db", fake_add)

    scraper.load_raw_documents()

    assert called["called"] is True
    assert scraper.documents == []


def test_get_docs_pending_s3_upload_returns_only_null_keys():
    engine, SessionLocal = _setup_inmemory_db()
    scraper = RawMotionDocumentScraper()
    scraper.engine = engine
    scraper.Session = SessionLocal

    with SessionLocal() as session:
        session.add_all(
            [
                RawMotionDocument(
                    motion_id="2021_10",
                    step_id="1",
                    file_id="100",
                    step_date=datetime.now(timezone.utc),
                    url="http://example.com/pending.pdf",
                    s3_key=None,
                    local_path=None,
                    timestamp=datetime.now(timezone.utc),
                ),
                RawMotionDocument(
                    motion_id="2021_10",
                    step_id="2",
                    file_id="200",
                    step_date=datetime.now(timezone.utc),
                    url="http://example.com/uploaded.pdf",
                    s3_key="documents/motions/uploaded.pdf",
                    local_path=None,
                    timestamp=datetime.now(timezone.utc),
                ),
            ]
        )
        session.commit()

    pending = scraper.get_docs_pending_s3_upload()

    assert [(doc.step_id, doc.file_id) for doc in pending] == [("1", "100")]


def test_upload_s3_persists_key_only_after_success(monkeypatch):
    engine, SessionLocal = _setup_inmemory_db()
    scraper = RawMotionDocumentScraper()
    scraper.engine = engine
    scraper.Session = SessionLocal
    expected_key = scraper._build_s3_key("motions", "2021_11-1-101.pdf")

    with SessionLocal() as session:
        session.add(
            RawMotionDocument(
                motion_id="2021_11",
                step_id="1",
                file_id="101",
                step_date=datetime.now(timezone.utc),
                url="http://example.com/motion.pdf",
                s3_key=None,
                local_path=None,
                timestamp=datetime.now(timezone.utc),
            )
        )
        session.commit()

    calls = []
    monkeypatch.setattr(
        scraper,
        "_upload_url_to_s3",
        lambda url, key: calls.append((url, key)) or True,
    )
    pending_doc = scraper.get_docs_pending_s3_upload()[0]

    assert scraper.upload_s3(pending_doc) is True
    assert calls == [("http://example.com/motion.pdf", expected_key)]

    with SessionLocal() as session:
        stored = session.get(
            RawMotionDocument,
            {"motion_id": "2021_11", "step_id": "1", "file_id": "101"},
        )
        assert stored.s3_key == expected_key


def test_upload_s3_failure_leaves_key_null(monkeypatch):
    engine, SessionLocal = _setup_inmemory_db()
    scraper = RawMotionDocumentScraper()
    scraper.engine = engine
    scraper.Session = SessionLocal

    with SessionLocal() as session:
        session.add(
            RawMotionDocument(
                motion_id="2021_12",
                step_id="1",
                file_id="102",
                step_date=datetime.now(timezone.utc),
                url="http://example.com/failure.pdf",
                s3_key=None,
                local_path=None,
                timestamp=datetime.now(timezone.utc),
            )
        )
        session.commit()

    monkeypatch.setattr(scraper, "_upload_url_to_s3", lambda url, key: False)
    pending_doc = scraper.get_docs_pending_s3_upload()[0]

    assert scraper.upload_s3(pending_doc) is False

    with SessionLocal() as session:
        stored = session.get(
            RawMotionDocument,
            {"motion_id": "2021_12", "step_id": "1", "file_id": "102"},
        )
        assert stored.s3_key is None


def test_upload_s3_fails_when_database_row_is_missing(monkeypatch):
    engine, SessionLocal = _setup_inmemory_db()
    scraper = RawMotionDocumentScraper()
    scraper.engine = engine
    scraper.Session = SessionLocal
    monkeypatch.setattr(scraper, "_upload_url_to_s3", lambda url, key: True)
    missing_doc = RawMotionDocument(
        motion_id="2021_missing",
        step_id="1",
        file_id="999",
        step_date=datetime.now(timezone.utc),
        url="http://example.com/missing.pdf",
        s3_key=None,
        local_path=None,
        timestamp=datetime.now(timezone.utc),
    )

    assert scraper.upload_s3(missing_doc) is False


def test_upload_url_to_s3_streams_response_bytes(monkeypatch):
    uploaded = []

    class FakeResponse:
        content = b"%PDF-test"

        def raise_for_status(self):
            return None

    class FakeClient:
        def upload_fileobj(self, fileobj, bucket, key):
            uploaded.append((fileobj.read(), bucket, key))

    monkeypatch.setattr(
        motions_documents_module,
        "get_url",
        lambda url: FakeResponse(),
    )
    monkeypatch.setattr(
        motions_documents_module.settings,
        "AWS_ACCESS_KEY_ID",
        None,
    )
    monkeypatch.setattr(
        motions_documents_module.settings,
        "AWS_SECRET_ACCESS_KEY",
        None,
    )
    monkeypatch.setattr(
        motions_documents_module.boto3,
        "client",
        lambda *args, **kwargs: FakeClient(),
    )

    assert (
        RawMotionDocumentScraper._upload_url_to_s3(
            "http://example.com/motion.pdf",
            "documents/motions/motion.pdf",
        )
        is True
    )
    assert uploaded == [
        (
            b"%PDF-test",
            motions_documents_module.settings.AWS_S3_BUCKET_NAME,
            "documents/motions/motion.pdf",
        )
    ]
