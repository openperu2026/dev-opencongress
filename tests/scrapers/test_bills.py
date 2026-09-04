import json
from datetime import datetime

from loguru import logger
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

# Adjust this import to your actual module path
from backend.scrapers.bills import RawBillScraper
from backend.database.raw_models import Base, RawBill

API_URL = "https://api.congreso.gob.pe/spley-portal-service/expediente/"
# ---------- create_raw_bill ----------


def test_create_raw_bill_sets_id_and_sections():
    scraper = RawBillScraper()

    year = "2021"
    bill_number = "1234"
    data = {
        "general": {"titulo": "Ley X"},
        "firmantes": [{"nombre": "Congresista A"}],
        # "estudioComisiones" intentionally omitted to test "Not Found" branch
        "seguimientos": [{"evento": "derivado"}],
    }

    raw_bill = scraper.create_raw_bill(year, bill_number, data, "www.example.org")

    assert isinstance(raw_bill, RawBill)
    assert raw_bill.id == f"{year}_{bill_number}"
    assert isinstance(raw_bill.timestamp, datetime)

    # Sections that exist should be JSON-dumped strings
    assert raw_bill.general == json.dumps(data["general"])
    assert raw_bill.congresistas == json.dumps(data["firmantes"])
    assert raw_bill.steps == json.dumps(data["seguimientos"])

    # Missing section in data => attribute should remain None
    assert raw_bill.committees is None
    assert raw_bill.api_url == "www.example.org"


def test_apply_sections_logs_missing_committees_at_debug_others_at_warning():
    scraper = RawBillScraper()
    raw_bill = RawBill(id="2021_1234")
    data = {
        "general": {"titulo": "Ley X"},
        # "firmantes" and "seguimientos" also omitted -- both should still
        # warn, unlike "estudioComisiones" (committees), which is legitimately
        # often absent/empty and shouldn't spam a warning per bill.
    }

    records = []
    sink_id = logger.add(lambda msg: records.append(msg.record), level="DEBUG")
    try:
        scraper._apply_sections(raw_bill, data)
    finally:
        logger.remove(sink_id)

    missing_by_name = {
        r["message"].split("Missing Attribute: ")[1].split(" ")[0]: r["level"].name
        for r in records
        if "Missing Attribute" in r["message"]
    }

    assert missing_by_name["estudioComisiones"] == "DEBUG"
    assert missing_by_name["firmantes"] == "WARNING"
    assert missing_by_name["seguimientos"] == "WARNING"


# ---------- add_bills_to_db ----------


def _setup_inmemory_db():
    """Create in-memory SQLite engine and session factory for tests."""
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    SessionLocal = sessionmaker(bind=engine)
    return engine, SessionLocal


def test_add_bills_to_db_persists_raw_bills():
    engine, SessionLocal = _setup_inmemory_db()

    scraper = RawBillScraper()
    # Override engine + Session to use in-memory DB instead of real one
    scraper.engine = engine
    scraper.Session = SessionLocal

    # Prepare one RawBill object in memory
    bill = RawBill(
        id="2021_1",
        timestamp=datetime(2021, 1, 1),
        general=json.dumps({"foo": "bar"}),
        congresistas=None,
        committees=None,
        steps=None,
    )
    scraper.raw_bills = [bill]

    assert scraper.add_bills_to_db() is True

    # Verify it actually exists in the database
    with SessionLocal() as session:
        count = session.query(RawBill).count()
        assert count == 1
        db_bill = session.query(RawBill).first()
        assert db_bill.id == "2021_1"
        assert db_bill.general == json.dumps({"foo": "bar"})


def test_add_bills_to_db_returns_false_when_empty():
    """An empty buffer is now the ROUTINE outcome of an all-unchanged
    scrape run -- must return False gracefully, not raise/assert."""
    scraper = RawBillScraper()
    scraper.raw_bills = []

    assert scraper.add_bills_to_db() is False


def test_add_bills_to_db_handles_sqlalchemy_error(monkeypatch):
    scraper = RawBillScraper()
    scraper.raw_bills = [RawBill(id="x", timestamp=datetime.now())]

    class DummySession:
        def __init__(self):
            self.rolled_back = False

        def bulk_save_objects(self, objs):
            from sqlalchemy.exc import SQLAlchemyError

            raise SQLAlchemyError("boom")

        def commit(self):
            pass

        def rollback(self):
            self.rolled_back = True

        def close(self):
            pass

    dummy_session = DummySession()

    def fake_sessionmaker():
        # each call returns the same dummy session (enough for this test)
        return dummy_session

    monkeypatch.setattr(scraper, "Session", fake_sessionmaker)

    ok = scraper.add_bills_to_db()
    assert ok is False
    assert dummy_session.rolled_back is True


# ---------- scrape_bill ----------


def test_scrape_bill_appends_raw_bill(monkeypatch, session):
    scraper = RawBillScraper()
    scraper.session = session

    monkeypatch.setattr(
        scraper,
        "_RawBillScraper__search_api_url",
        lambda bill_url: f"{API_URL}2021/1234",
    )

    monkeypatch.setattr(
        scraper,
        "_RawBillScraper__get_existing_api_url",
        lambda bill_url: f"{API_URL}2021/1234",
    )

    # Fake JSON response from get_url_text
    def fake_get_url_text(url: str):
        # Make sure URL is what we expect
        assert url.startswith(API_URL)
        return json.dumps(
            {
                "data": {
                    "general": {"titulo": "Ley de Prueba"},
                    "firmantes": [{"nombre": "Congresista X"}],
                    "estudioComisiones": [{"nombre": "Comisión Y"}],
                    "seguimientos": [{"evento": "ingreso"}],
                }
            }
        )

    # Patch get_url_text in the scraper module
    monkeypatch.setattr("backend.scrapers.bills.get_url_text", fake_get_url_text)
    monkeypatch.setattr(scraper, "update_tracking", lambda bill: [bill])

    scraper.scrape_bill("2021", "1234")

    assert len(scraper.raw_bills) == 1
    bill = scraper.raw_bills[0]
    assert bill.id == "2021_1234"
    assert json.loads(bill.general)["titulo"] == "Ley de Prueba"
    assert json.loads(bill.committees)[0]["nombre"] == "Comisión Y"
    assert json.loads(bill.steps)[0]["evento"] == "ingreso"


# ---------- 2026-2031 chamber bills (Phase B2) ----------


def test_create_chamber_raw_bill_uses_explicit_id():
    scraper = RawBillScraper()

    data = {
        "general": {"titulo": "Ley X"},
        "firmantes": [{"nombre": "Senador A"}],
        "seguimientos": [{"evento": "derivado"}],
    }

    raw_bill = scraper.create_chamber_raw_bill(
        "00006-2026-2031-S", data, "www.example.org"
    )

    assert isinstance(raw_bill, RawBill)
    assert raw_bill.id == "00006-2026-2031-S"
    assert raw_bill.general == json.dumps(data["general"])
    assert raw_bill.congresistas == json.dumps(data["firmantes"])
    assert raw_bill.committees is None
    assert raw_bill.api_url == "www.example.org"


def test_scrape_chamber_bill_senadores_builds_correct_id_and_url(monkeypatch):
    scraper = RawBillScraper()
    captured_urls = []

    def fake_search(bill_url):
        captured_urls.append(bill_url)
        return f"{API_URL}opaque1/opaque2"

    monkeypatch.setattr(
        scraper, "_RawBillScraper__get_existing_api_url", lambda bid: None
    )
    monkeypatch.setattr(scraper, "_RawBillScraper__search_api_url", fake_search)

    def fake_get_url_text(url):
        return json.dumps({"data": {"general": {"titulo": "Ley Senado"}}})

    monkeypatch.setattr("backend.scrapers.bills.get_url_text", fake_get_url_text)
    monkeypatch.setattr(scraper, "update_tracking", lambda bill: [bill])

    scraper.scrape_chamber_bill("Senadores", 6)

    assert captured_urls == [
        "https://wb2server.congreso.gob.pe/spley-portal/#/senado/expediente/2026/6"
    ]
    assert len(scraper.raw_bills) == 1
    assert scraper.raw_bills[0].id == "00006-2026-2031-S"


def test_scrape_chamber_bill_diputados_builds_correct_id_and_url(monkeypatch):
    scraper = RawBillScraper()
    captured_urls = []

    def fake_search(bill_url):
        captured_urls.append(bill_url)
        return f"{API_URL}opaque1/opaque2"

    monkeypatch.setattr(
        scraper, "_RawBillScraper__get_existing_api_url", lambda bid: None
    )
    monkeypatch.setattr(scraper, "_RawBillScraper__search_api_url", fake_search)

    def fake_get_url_text(url):
        return json.dumps({"data": {"general": {"titulo": "Ley Diputados"}}})

    monkeypatch.setattr("backend.scrapers.bills.get_url_text", fake_get_url_text)
    monkeypatch.setattr(scraper, "update_tracking", lambda bill: [bill])

    scraper.scrape_chamber_bill("Diputados", 102)

    assert captured_urls == [
        "https://wb2server.congreso.gob.pe/spley-portal/#/diputados/expediente/2026/102"
    ]
    assert len(scraper.raw_bills) == 1
    assert scraper.raw_bills[0].id == "00102-2026-2031-CD"
