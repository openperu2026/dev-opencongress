import datetime

import pytest
from lxml import html as lxml_html
from sqlalchemy import Boolean, Column, DateTime, Integer, String, create_engine
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import declarative_base, sessionmaker

import backend.scrapers.bancadas as bancadas
from backend.scrapers.bancadas import RawBancadaScraper


def test_get_options_returns_expected_dict(monkeypatch):
    doc = lxml_html.fromstring(
        """
        <html>
          <body>
            <select name="idPeriodo[]">
              <option value="1">2021-2026</option>
              <option value="2"></option>
            </select>
          </body>
        </html>
        """
    )

    monkeypatch.setattr(bancadas, "parse_url", lambda url: doc)

    scraper = RawBancadaScraper()
    options = scraper.get_options(
        url="https://fake-url.test",
        select_name="idPeriodo[]",
    )

    assert options == {"2021-2026": "1"}


class FakePage:
    def __init__(self, html="<html>OK</html>", fail_on=None):
        self.html = html
        self.fail_on = fail_on
        self.goto_calls = []
        self.selector_waits = []
        self.evaluate_calls = []
        self.function_waits = []
        self.timeout_waits = []
        self.closed = False

    def goto(self, url, wait_until=None):
        self.goto_calls.append((url, wait_until))
        if self.fail_on == "goto":
            raise bancadas.PlaywrightTimeoutError("goto failed")

    def wait_for_selector(self, selector, state=None):
        self.selector_waits.append((selector, state))
        if self.fail_on == "wait_for_selector":
            raise bancadas.PlaywrightTimeoutError("selector missing")

    def evaluate(self, script, arg):
        self.evaluate_calls.append((script, arg))
        if self.fail_on == "evaluate":
            raise bancadas.PlaywrightTimeoutError("evaluate failed")
        return [arg["value"]]

    def wait_for_function(self, script, arg):
        self.function_waits.append((script, arg))
        if self.fail_on == "wait_for_function":
            raise bancadas.PlaywrightTimeoutError("selection not applied")

    def wait_for_timeout(self, timeout):
        self.timeout_waits.append(timeout)
        if self.fail_on == "wait_for_timeout":
            raise bancadas.PlaywrightTimeoutError("table not stable")

    def content(self):
        if self.fail_on == "content":
            raise bancadas.PlaywrightTimeoutError("content failed")
        return self.html

    def close(self):
        self.closed = True


class FakeBrowser:
    def __init__(self, page):
        self.page = page
        self.closed = False
        self.new_page_calls = 0

    def new_page(self):
        self.new_page_calls += 1
        return self.page

    def close(self):
        self.closed = True


class FakeChromium:
    def __init__(self, browser):
        self.browser = browser
        self.launch_calls = []

    def launch(self, headless=True):
        self.launch_calls.append(headless)
        return self.browser


class FakePlaywrightContext:
    def __init__(self, chromium):
        self.chromium = chromium

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False


def test_get_html_with_selections_success(monkeypatch):
    page = FakePage(html="<html>captured</html>")
    browser = FakeBrowser(page)
    chromium = FakeChromium(browser)
    playwright = FakePlaywrightContext(chromium)
    monkeypatch.setattr(bancadas, "sync_playwright", lambda: playwright)

    scraper = RawBancadaScraper()
    html = scraper.get_html_with_selections(
        url="https://fake-url.test",
        period_value="2021",
        condition_value="eej",
    )

    assert html == "<html>captured</html>"
    assert chromium.launch_calls == [True]
    assert page.goto_calls == [("https://fake-url.test", "domcontentloaded")]
    assert page.selector_waits == [
        ('select[name="idPeriodo[]"]', "attached"),
        ('select[name="keyCondicion[]"]', "attached"),
        (".table-cng", "visible"),
    ]
    assert [call[1] for call in page.evaluate_calls] == [
        {"selector": 'select[name="idPeriodo[]"]', "value": "2021"},
        {"selector": 'select[name="keyCondicion[]"]', "value": "eej"},
    ]
    assert [call[1] for call in page.function_waits] == [
        {"selector": 'select[name="idPeriodo[]"]', "value": "2021"},
        {"selector": 'select[name="keyCondicion[]"]', "value": "eej"},
    ]
    assert page.timeout_waits == [1000]
    assert page.closed is True
    assert browser.closed is True


def test_get_html_with_selections_handles_failures_and_cleans_up(monkeypatch):
    page = FakePage(fail_on="wait_for_selector")
    browser = FakeBrowser(page)
    chromium = FakeChromium(browser)
    playwright = FakePlaywrightContext(chromium)
    monkeypatch.setattr(bancadas, "sync_playwright", lambda: playwright)

    scraper = RawBancadaScraper()
    html = scraper.get_html_with_selections(
        url="https://fake-url.test",
        period_value="2021",
        condition_value="eej",
    )

    assert html is None
    assert page.closed is True
    assert browser.closed is True


class _DummyRawBancada:
    def __init__(
        self, timestamp, legislative_period, raw_html, last_update, changed, processed
    ):
        self.timestamp = timestamp
        self.legislative_period = legislative_period
        self.raw_html = raw_html
        self.last_update = last_update
        self.changed = changed
        self.processed = processed


def test_get_raw_bancadas_only_current(monkeypatch):
    monkeypatch.setattr(bancadas, "RawBancada", _DummyRawBancada)

    def fake_get_options(url, select_name="idPeriodo[]"):
        assert select_name == "idPeriodo[]"
        return {"2021-2026": "1", "2016-2021": "2"}

    scraper = RawBancadaScraper()
    monkeypatch.setattr(scraper, "get_options", fake_get_options)
    monkeypatch.setattr(
        scraper,
        "get_html_with_selections",
        lambda url, period, cond: f"<html>{period}-{cond}</html>",
    )
    monkeypatch.setattr(scraper, "update_tracking", lambda b: b)

    scraper.get_raw_bancadas(only_current=True)

    assert len(scraper.bancadas_list) == 1
    bancada = scraper.bancadas_list[0]
    assert bancada.legislative_period == "2021-2026"
    assert bancada.raw_html == "<html>1-eej</html>"


def test_get_raw_bancadas_all_periods_single_condition(monkeypatch):
    monkeypatch.setattr(bancadas, "RawBancada", _DummyRawBancada)

    scraper = RawBancadaScraper()
    monkeypatch.setattr(
        scraper,
        "get_options",
        lambda url, select_name="idPeriodo[]": {
            "2021-2026": "1",
            "2016-2021": "2",
        },
    )
    monkeypatch.setattr(
        scraper,
        "get_html_with_selections",
        lambda url, period, cond: f"<html>{period}-{cond}</html>",
    )
    monkeypatch.setattr(scraper, "update_tracking", lambda b: b)

    scraper.get_raw_bancadas(only_current=False)

    assert len(scraper.bancadas_list) == 2
    assert [b.legislative_period for b in scraper.bancadas_list] == [
        "2021-2026",
        "2016-2021",
    ]
    assert [b.raw_html for b in scraper.bancadas_list] == [
        "<html>1-eej</html>",
        "<html>2-eej</html>",
    ]


Base = declarative_base()


class RawBancadaTrackingTest(Base):
    __tablename__ = "raw_bancadas"

    id = Column(Integer, primary_key=True, autoincrement=True)
    timestamp = Column(DateTime, nullable=False)
    legislative_period = Column(String, nullable=False)
    raw_html = Column(String, nullable=False)
    last_update = Column(Boolean, nullable=False, default=False)
    changed = Column(Boolean, nullable=False, default=False)
    processed = Column(Boolean, nullable=False, default=False)


def test_update_tracking_marks_first_snapshot_changed(monkeypatch):
    monkeypatch.setattr(bancadas, "RawBancada", RawBancadaTrackingTest)

    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    TestSession = sessionmaker(bind=engine)

    scraper = RawBancadaScraper()
    scraper.engine = engine
    scraper.Session = TestSession

    bancada = RawBancadaTrackingTest(
        timestamp=datetime.datetime.now(),
        legislative_period="2021-2026",
        raw_html="<html>v1</html>",
        last_update=False,
        changed=False,
        processed=False,
    )

    tracked = scraper.update_tracking(bancada)

    assert tracked.changed is True
    assert tracked.last_update is True
    assert tracked.processed is False


def test_update_tracking_marks_identical_snapshot_processed(monkeypatch):
    monkeypatch.setattr(bancadas, "RawBancada", RawBancadaTrackingTest)

    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    TestSession = sessionmaker(bind=engine)

    scraper = RawBancadaScraper()
    scraper.engine = engine
    scraper.Session = TestSession

    now = datetime.datetime.now()
    with TestSession() as session:
        session.add(
            RawBancadaTrackingTest(
                timestamp=now,
                legislative_period="2021-2026",
                raw_html="<html>same</html>",
                last_update=True,
                changed=True,
                processed=False,
            )
        )
        session.commit()

    new_snapshot = RawBancadaTrackingTest(
        timestamp=now + datetime.timedelta(minutes=1),
        legislative_period="2021-2026",
        raw_html="<html>same</html>",
        last_update=False,
        changed=False,
        processed=False,
    )

    tracked = scraper.update_tracking(new_snapshot)

    assert tracked.changed is False
    assert tracked.last_update is True
    assert tracked.processed is True

    with TestSession() as session:
        previous = session.query(RawBancadaTrackingTest).one()
        assert previous.last_update is False


def test_update_tracking_marks_changed_snapshot_and_flips_previous(monkeypatch):
    monkeypatch.setattr(bancadas, "RawBancada", RawBancadaTrackingTest)

    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    TestSession = sessionmaker(bind=engine)

    scraper = RawBancadaScraper()
    scraper.engine = engine
    scraper.Session = TestSession

    now = datetime.datetime.now()
    with TestSession() as session:
        session.add(
            RawBancadaTrackingTest(
                timestamp=now,
                legislative_period="2021-2026",
                raw_html="<html>old</html>",
                last_update=True,
                changed=True,
                processed=False,
            )
        )
        session.commit()

    new_snapshot = RawBancadaTrackingTest(
        timestamp=now + datetime.timedelta(minutes=1),
        legislative_period="2021-2026",
        raw_html="<html>new</html>",
        last_update=False,
        changed=False,
        processed=False,
    )

    tracked = scraper.update_tracking(new_snapshot)

    assert tracked.changed is True
    assert tracked.last_update is True
    assert tracked.processed is False

    with TestSession() as session:
        previous = session.query(RawBancadaTrackingTest).one()
        assert previous.last_update is False


class RawBancadaInsertTest(Base):
    __tablename__ = "raw_bancadas_insert"

    id = Column(Integer, primary_key=True, autoincrement=True)
    timestamp = Column(DateTime, nullable=False)
    legislative_period = Column(String, nullable=False)
    raw_html = Column(String, nullable=False)


def test_add_bancadas_to_db_success():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    TestSession = sessionmaker(bind=engine)

    scraper = RawBancadaScraper()
    scraper.engine = engine
    scraper.Session = TestSession

    now = datetime.datetime.now()
    scraper.bancadas_list = [
        RawBancadaInsertTest(
            timestamp=now,
            legislative_period="2021-2026",
            raw_html="<html>1</html>",
        ),
        RawBancadaInsertTest(
            timestamp=now,
            legislative_period="2016-2021",
            raw_html="<html>2</html>",
        ),
    ]

    result = scraper.add_bancadas_to_db()
    assert result is True

    with TestSession() as session:
        count = session.query(RawBancadaInsertTest).count()
        assert count == 2


def test_add_bancadas_to_db_raises_when_empty_list():
    scraper = RawBancadaScraper()
    scraper.bancadas_list = []

    with pytest.raises(AssertionError):
        scraper.add_bancadas_to_db()


def test_add_bancadas_to_db_handles_sqlalchemy_error():
    class DummySession:
        def __init__(self):
            self.rollback_called = False
            self.close_called = False

        def bulk_save_objects(self, objs):
            raise SQLAlchemyError("Boom")

        def commit(self):
            pass

        def rollback(self):
            self.rollback_called = True

        def close(self):
            self.close_called = True

    scraper = RawBancadaScraper()
    scraper.bancadas_list = [object()]

    dummy_session = DummySession()
    scraper.Session = lambda: dummy_session

    result = scraper.add_bancadas_to_db()

    assert result is False
    assert dummy_session.rollback_called is True
    assert dummy_session.close_called is True
