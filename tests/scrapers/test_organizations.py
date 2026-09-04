from datetime import datetime

import pytest
from lxml.html import fromstring
from sqlalchemy import create_engine
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import sessionmaker

from playwright.sync_api import TimeoutError as PlaywrightTimeoutError

import backend.scrapers.organizations as organizations
from backend.database.raw_models import Base, RawOrganization
from backend.scrapers.organizations import BASE_URLS, RawOrganizationScraper


# ---------- helpers ----------


def make_scraper():
    """
    Avoid calling RawOrganizationScraper.__init__ because it creates
    a real engine from settings.DB_URL.
    """
    scraper = RawOrganizationScraper.__new__(RawOrganizationScraper)
    scraper.urls = BASE_URLS
    return scraper


def setup_inmemory_db():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    SessionLocal = sessionmaker(bind=engine)
    return engine, SessionLocal


class FakePage:
    def __init__(
        self,
        content="<html>OK</html>",
        timeout_on_selector=False,
        timeout_on_function=False,
        timeout_on_content=False,
    ):
        self._content = content
        self.timeout_on_selector = timeout_on_selector
        self.timeout_on_function = timeout_on_function
        self.timeout_on_content = timeout_on_content

        self.goto_calls = []
        self.selector_waits = []
        self.evaluate_calls = []
        self.function_waits = []
        self.timeout_waits = []

    def goto(self, url, wait_until=None):
        self.goto_calls.append((url, wait_until))

    def wait_for_selector(self, selector, state=None):
        self.selector_waits.append((selector, state))
        if self.timeout_on_selector:
            raise PlaywrightTimeoutError("selector timed out")
        return True

    def evaluate(self, script, arg):
        self.evaluate_calls.append((script, arg))
        return [arg["value"]]

    def wait_for_function(self, script, arg=None):
        self.function_waits.append((script, arg))
        if self.timeout_on_function:
            raise PlaywrightTimeoutError("function timed out")
        return True

    def wait_for_timeout(self, timeout):
        self.timeout_waits.append(timeout)

    def content(self):
        if self.timeout_on_content:
            raise PlaywrightTimeoutError("content timed out")
        return self._content


class FakeBrowser:
    def __init__(self, page):
        self.page = page
        self.closed = False

    def new_page(self):
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


class FakePlaywright:
    def __init__(self, chromium):
        self.chromium = chromium

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False


# ---------- get_options ----------


def test_get_options_parses_select(monkeypatch):
    scraper = make_scraper()

    def fake_parse_url(url):
        html = """
        <html><body>
          <select name="idRegistroPadre">
            <option value="2025">2024-2025</option>
            <option value="2024">2023-2024</option>
            <option value=""></option>
          </select>
        </body></html>
        """
        return fromstring(html)

    monkeypatch.setattr(organizations, "parse_url", fake_parse_url)

    options = scraper.get_options(
        url="https://fake-url.test",
        select_name="idRegistroPadre",
    )

    assert options == {
        "2024-2025": "2025",
        "2023-2024": "2024",
    }


def test_get_options_returns_empty_when_parse_fails(monkeypatch):
    scraper = make_scraper()

    monkeypatch.setattr(organizations, "parse_url", lambda url: None)

    assert scraper.get_options("https://fake-url.test") == {}


# ---------- get_html_with_selections ----------


def test_get_html_with_selections_success(monkeypatch):
    scraper = make_scraper()

    page = FakePage(content="<html>organization data</html>")
    browser = FakeBrowser(page)
    chromium = FakeChromium(browser)
    playwright = FakePlaywright(chromium)

    monkeypatch.setattr(organizations, "sync_playwright", lambda: playwright)

    html = scraper.get_html_with_selections(
        url="https://fake-url.test",
        period_value="2025",
    )

    assert html == "<html>organization data</html>"
    assert chromium.launch_calls == [True]
    assert page.goto_calls == [("https://fake-url.test", "domcontentloaded")]
    assert page.selector_waits == [
        ('select[name="idRegistroPadre"]', "attached"),
        ("table.congresistas", "visible"),
    ]
    assert [call[1] for call in page.evaluate_calls] == [
        {
            "selector": 'select[name="idRegistroPadre"]',
            "value": "2025",
        }
    ]
    assert [call[1] for call in page.function_waits] == [
        {
            "selector": 'select[name="idRegistroPadre"]',
            "value": "2025",
        }
    ]
    assert page.timeout_waits == [1000]
    assert browser.closed is True


def test_get_html_with_selections_returns_none_on_playwright_timeout(monkeypatch):
    scraper = make_scraper()

    page = FakePage(timeout_on_selector=True)
    browser = FakeBrowser(page)
    chromium = FakeChromium(browser)
    playwright = FakePlaywright(chromium)

    monkeypatch.setattr(organizations, "sync_playwright", lambda: playwright)

    html = scraper.get_html_with_selections(
        url="https://fake-url.test",
        period_value="2025",
    )

    assert html is None
    assert browser.closed is True


# ---------- get_raw_organizations ----------


def test_get_raw_organizations_builds_organization_list_only_current(monkeypatch):
    scraper = make_scraper()
    scraper.urls = {
        "Mesa Directiva": "https://mesa.test",
        "Consejo Directivo": "https://consejo.test",
    }

    monkeypatch.setattr(
        scraper,
        "get_options",
        lambda url, select_name="idRegistroPadre": {
            "2024-2025": "2025",
            "2023-2024": "2024",
        },
    )

    def fake_get_html_with_selections(url, period_value):
        if url == "https://consejo.test":
            return None
        return f"<html>url={url}, period={period_value}</html>"

    monkeypatch.setattr(
        scraper,
        "get_html_with_selections",
        fake_get_html_with_selections,
    )
    monkeypatch.setattr(scraper, "update_tracking", lambda org: org)

    scraper.get_raw_organizations(only_current=True)

    assert hasattr(scraper, "organizations_list")
    assert len(scraper.organizations_list) == 1

    org = scraper.organizations_list[0]
    assert org.legislative_year == "2024-2025"
    assert org.type_org == "Mesa Directiva"
    assert org.raw_html == "<html>url=https://mesa.test, period=2025</html>"
    assert org.processed is False
    assert org.last_update is True


def test_get_raw_organizations_all_years(monkeypatch):
    scraper = make_scraper()
    scraper.urls = {
        "Mesa Directiva": "https://mesa.test",
    }

    monkeypatch.setattr(
        scraper,
        "get_options",
        lambda url, select_name="idRegistroPadre": {
            "2024-2025": "2025",
            "2023-2024": "2024",
        },
    )
    monkeypatch.setattr(
        scraper,
        "get_html_with_selections",
        lambda url, period_value: f"<html>period={period_value}</html>",
    )
    monkeypatch.setattr(scraper, "update_tracking", lambda org: org)

    scraper.get_raw_organizations(only_current=False)

    assert len(scraper.organizations_list) == 2
    assert [org.legislative_year for org in scraper.organizations_list] == [
        "2024-2025",
        "2023-2024",
    ]
    assert [org.raw_html for org in scraper.organizations_list] == [
        "<html>period=2025</html>",
        "<html>period=2024</html>",
    ]


# ---------- update_tracking ----------


def test_update_tracking_first_version_marks_changed():
    engine, SessionLocal = setup_inmemory_db()

    scraper = make_scraper()
    scraper.Session = SessionLocal

    org = RawOrganization(
        timestamp=datetime(2026, 1, 1),
        legislative_year="2025-2026",
        type_org="Mesa Directiva",
        raw_html="<html>new</html>",
        changed=False,
        processed=True,
        last_update=False,
    )

    result = scraper.update_tracking(org)

    assert result.changed is True
    assert result.processed is False
    assert result.last_update is True


def test_update_tracking_existing_same_version_marks_not_changed():
    engine, SessionLocal = setup_inmemory_db()

    scraper = make_scraper()
    scraper.Session = SessionLocal

    old = RawOrganization(
        timestamp=datetime(2026, 1, 1),
        legislative_year="2025-2026",
        type_org="Mesa Directiva",
        raw_html="<html>same</html>",
        changed=True,
        processed=False,
        last_update=True,
    )

    with SessionLocal() as session:
        session.add(old)
        session.commit()

    new = RawOrganization(
        timestamp=datetime(2026, 1, 2),
        legislative_year="2025-2026",
        type_org="Mesa Directiva",
        raw_html="<html>same</html>",
        changed=False,
        processed=False,
        last_update=True,
    )

    result = scraper.update_tracking(new)

    assert result.changed is False
    assert result.processed is True
    assert result.last_update is True

    with SessionLocal() as session:
        old_from_db = session.query(RawOrganization).first()
        assert old_from_db.last_update is False


def test_update_tracking_existing_different_version_marks_changed():
    engine, SessionLocal = setup_inmemory_db()

    scraper = make_scraper()
    scraper.Session = SessionLocal

    old = RawOrganization(
        timestamp=datetime(2026, 1, 1),
        legislative_year="2025-2026",
        type_org="Mesa Directiva",
        raw_html="<html>old</html>",
        changed=True,
        processed=False,
        last_update=True,
    )

    with SessionLocal() as session:
        session.add(old)
        session.commit()

    new = RawOrganization(
        timestamp=datetime(2026, 1, 2),
        legislative_year="2025-2026",
        type_org="Mesa Directiva",
        raw_html="<html>new</html>",
        changed=False,
        processed=False,
        last_update=True,
    )

    result = scraper.update_tracking(new)

    assert result.changed is True
    assert result.processed is False
    assert result.last_update is True

    with SessionLocal() as session:
        old_from_db = session.query(RawOrganization).first()
        assert old_from_db.last_update is False


# ---------- add_organizations_to_db ----------


def test_add_organizations_to_db_persists():
    engine, SessionLocal = setup_inmemory_db()

    scraper = make_scraper()
    scraper.Session = SessionLocal

    scraper.organizations_list = [
        RawOrganization(
            timestamp=datetime(2026, 1, 1),
            legislative_year="2025-2026",
            type_org="Mesa Directiva",
            raw_html="<html>data</html>",
            changed=True,
            processed=False,
            last_update=True,
        )
    ]

    assert scraper.add_organizations_to_db() is True

    with SessionLocal() as session:
        rows = session.query(RawOrganization).all()

    assert len(rows) == 1
    assert rows[0].legislative_year == "2025-2026"
    assert rows[0].type_org == "Mesa Directiva"
    assert rows[0].raw_html == "<html>data</html>"


def test_add_organizations_to_db_asserts_when_empty():
    scraper = make_scraper()
    scraper.organizations_list = []

    with pytest.raises(AssertionError):
        scraper.add_organizations_to_db()


def test_add_organizations_to_db_handles_sqlalchemy_error():
    scraper = make_scraper()

    scraper.organizations_list = [
        RawOrganization(
            timestamp=datetime.now(),
            legislative_year="2025-2026",
            type_org="Mesa Directiva",
            raw_html="<html></html>",
        )
    ]

    class DummySession:
        def __init__(self):
            self.rolled_back = False
            self.closed = False

        def bulk_save_objects(self, objs):
            raise SQLAlchemyError("boom")

        def commit(self):
            pass

        def rollback(self):
            self.rolled_back = True

        def close(self):
            self.closed = True

    dummy_session = DummySession()
    scraper.Session = lambda: dummy_session

    assert scraper.add_organizations_to_db() is False
    assert dummy_session.rolled_back is True
    assert dummy_session.closed is True


def test_get_raw_organizations_aborts_when_no_years(monkeypatch):
    scraper = make_scraper()
    scraper.urls = {
        "Mesa Directiva": "https://mesa.test",
    }

    warnings = []

    monkeypatch.setattr(
        scraper,
        "get_options",
        lambda url, select_name="idRegistroPadre": {},
    )
    monkeypatch.setattr(
        "backend.scrapers.organizations.logger.warning",
        lambda message: warnings.append(message),
    )

    scraper.get_raw_organizations()

    assert scraper.organizations_list == []
    assert any("No years found for type=Mesa Directiva" in msg for msg in warnings)


# ---------- 2026-2031 chamber admin orgs (Phase B1) ----------

_PARLIAMENT_TABLE_HTML = """
<html><body>
  <table id="parliamentTable">
    <thead><tr>
      <th>APELLIDOS Y NOMBRES</th><th>CARGO</th>
      <th>GRUPO PARLAMENTARIO</th><th>EMAIL</th>
    </tr></thead>
    <tbody>
      <tr>
        <td><a href="https://senado.congreso.gob.pe/senador/juarez-gallegos-carmen-patricia/">
          Juarez Gallegos, Carmen Patricia</a></td>
        <td>Titular</td>
        <td>FUERZA POPULAR</td>
        <td>pjuarez@congreso.gob.pe</td>
      </tr>
      <tr>
        <td><a href="https://senado.congreso.gob.pe/senador/andres-lujan-serafin/">
          Andres Lujan, Serafin</a></td>
        <td></td>
        <td>JUNTOS POR EL PERU</td>
        <td>sandres@congreso.gob.pe</td>
      </tr>
    </tbody>
  </table>
</body></html>
"""


def test_parse_parliament_table_matches_by_header_text():
    scraper = make_scraper()
    rows = scraper._parse_parliament_table(fromstring(_PARLIAMENT_TABLE_HTML))

    assert len(rows) == 2
    assert rows[0]["cargo"] == "Titular"
    assert "Juarez Gallegos" in rows[0]["name"]
    assert rows[0]["website"] == (
        "https://senado.congreso.gob.pe/senador/juarez-gallegos-carmen-patricia/"
    )
    # Empty CARGO cell (Andres Lujan) still yields a row, cargo="" not dropped.
    assert rows[1]["cargo"] == ""


_COMISION_PERMANENTE_TABLE_HTML = """
<html><body>
  <table>
    <thead><tr>
      <th>Foto</th><th>Apellidos y Nombres</th>
      <th>Grupo Parlamentario</th><th>e-Mail</th>
    </tr></thead>
    <tbody>
      <tr>
        <td><img/></td>
        <td><a href="https://senado.congreso.gob.pe/senador/aguinaga-recuenco-alejandro-aurelio/">
          Aguinaga Recuenco, Alejandro Aurelio</a></td>
        <td>FUERZA POPULAR</td>
        <td>aaguinaga@congreso.gob.pe</td>
      </tr>
    </tbody>
  </table>
</body></html>
"""


def test_parse_parliament_table_falls_back_when_no_id_present():
    """Comisión Permanente's real page has a <table> with no id at all and
    no Cargo column -- confirmed live 2026-09-02."""
    scraper = make_scraper()
    rows = scraper._parse_parliament_table(fromstring(_COMISION_PERMANENTE_TABLE_HTML))

    assert len(rows) == 1
    assert "Aguinaga Recuenco" in rows[0]["name"]
    assert rows[0]["cargo"] is None


_MESA_DIRECTIVA_SENADO_HTML = """
<html><body>
  <div id="mesa-directiva-section">
    <div class="md-top-row">
      <div class="md-profile">
        <a class="md-name" href="https://senado.congreso.gob.pe/senador/torres-morales-miguel-angel/">Torres Morales, Miguel Ángel</a>
        <span class="md-role">Presidente</span>
      </div>
    </div>
    <div class="md-bottom-row">
      <div class="md-profile">
        <a class="md-name" href="https://senado.congreso.gob.pe/senador/munante-barrios-alejandro/">Muñante Barrios, Alejandro</a>
        <span class="md-role">Primer Vicepresidente</span>
      </div>
    </div>
  </div>
</body></html>
"""

_MESA_DIRECTIVA_DIPUTADOS_HTML = """
<html><body>
  <div class="congresista-results__body" data-results-body=""></div>
  <script type="application/json" data-congresista-dataset>[
    {"name": "Reto Otero, Oscar de Jesús", "campo_adicional": "Presidencia",
     "url": "https://diputados.congreso.gob.pe/diputado/reto-otero-oscar-de-jesus/"},
    {"name": "Marquez Huanca, Analí", "campo_adicional": "Vicepresidencia",
     "url": "https://diputados.congreso.gob.pe/diputado/marquez-huanca-anali/"}
  ]</script>
</body></html>
"""


def test_parse_mesa_directiva_senado_extracts_profiles():
    scraper = make_scraper()
    rows = scraper._parse_mesa_directiva_senado(fromstring(_MESA_DIRECTIVA_SENADO_HTML))

    assert len(rows) == 2
    assert rows[0]["name"] == "Torres Morales, Miguel Ángel"
    assert rows[0]["cargo"] == "Presidente"
    assert rows[0]["website"] == (
        "https://senado.congreso.gob.pe/senador/torres-morales-miguel-angel/"
    )


def test_parse_mesa_directiva_diputados_extracts_rows():
    scraper = make_scraper()
    rows = scraper._parse_mesa_directiva_diputados(
        fromstring(_MESA_DIRECTIVA_DIPUTADOS_HTML)
    )

    assert len(rows) == 2
    assert rows[0]["name"] == "Reto Otero, Oscar de Jesús"
    assert rows[0]["cargo"] == "Presidencia"
    assert rows[0]["website"] == (
        "https://diputados.congreso.gob.pe/diputado/reto-otero-oscar-de-jesus/"
    )


def test_parse_parliament_table_missing_returns_empty():
    scraper = make_scraper()
    assert (
        scraper._parse_parliament_table(fromstring("<html><body></body></html>")) == []
    )


def test_scrape_admin_org_page_roundtrips_through_process_admin_org(monkeypatch):
    """CRITICAL: proves the synthesized `.congresistas` blob (5 cells, one
    throwaway header row) is byte-compatible with process_admin_org()'s
    existing xpath contract, and confirms the confirmed 2026-2031 design:
    org-page scrapes build ONLY the Organization record, never Membership
    rows -- all membership data for this term comes from each congresista's
    own cargos page instead (congresistas.py::_get_chamber_cargos)."""
    from backend.process.organizations import process_admin_org

    scraper = make_scraper()
    monkeypatch.setattr(
        "backend.scrapers.organizations.parse_url",
        lambda url, *a, **k: fromstring(_PARLIAMENT_TABLE_HTML),
    )

    raw_org = scraper._scrape_admin_org_page(
        "https://senado.congreso.gob.pe/junta-de-portavoces/",
        "Junta de Portavoces",
        "Senadores",
        "2026",
    )

    assert raw_org is not None
    assert raw_org.chamber == "Senadores"
    assert raw_org.legislative_year == "2026"

    org_schema, memberships = process_admin_org(raw_org)

    assert org_schema.org_name == "Junta de Portavoces"
    assert org_schema.parent_org_name == "Senado de la República"
    # Cargo is always blanked out by _build_admin_org_html for 2026-2031
    # rows now, so process_admin_org's existing blank-cargo skip drops
    # every row -- zero memberships, even though real names/cargos were
    # parsed and are present in raw_html.
    assert memberships == []


def test_scrape_admin_org_page_missing_table_returns_none(monkeypatch):
    """Genuine failure case (site structure changed again): prose with no
    #mesa-directiva-section at all -- the real Senado Mesa Directiva
    parser must still return None, not crash."""
    scraper = make_scraper()
    monkeypatch.setattr(
        "backend.scrapers.organizations.parse_url",
        lambda url, *a, **k: fromstring("<html><body>prose, no section</body></html>"),
    )
    result = scraper._scrape_admin_org_page(
        "https://senado.congreso.gob.pe/mesa-directiva/",
        "Mesa Directiva",
        "Senadores",
        "2026",
    )
    assert result is None


def test_scrape_admin_org_page_mesa_directiva_senado_builds_org_no_membership(
    monkeypatch,
):
    from backend.process.organizations import process_admin_org

    scraper = make_scraper()
    monkeypatch.setattr(
        "backend.scrapers.organizations.parse_url",
        lambda url, *a, **k: fromstring(_MESA_DIRECTIVA_SENADO_HTML),
    )

    raw_org = scraper._scrape_admin_org_page(
        "https://senado.congreso.gob.pe/mesa-directiva/",
        "Mesa Directiva",
        "Senadores",
        "2026",
    )

    assert raw_org is not None
    org_schema, memberships = process_admin_org(raw_org)
    assert org_schema.org_name == "Mesa Directiva"
    assert memberships == []


def test_scrape_admin_org_page_mesa_directiva_diputados_builds_org_no_membership(
    monkeypatch,
):
    from backend.process.organizations import process_admin_org

    scraper = make_scraper()
    monkeypatch.setattr(
        "backend.scrapers.organizations.parse_url",
        lambda url, *a, **k: fromstring(_MESA_DIRECTIVA_DIPUTADOS_HTML),
    )

    raw_org = scraper._scrape_admin_org_page(
        "https://diputados.congreso.gob.pe/mesa-directiva/",
        "Mesa Directiva",
        "Diputados",
        "2026",
    )

    assert raw_org is not None
    org_schema, memberships = process_admin_org(raw_org)
    assert org_schema.org_name == "Mesa Directiva"
    assert memberships == []


def test_scrape_admin_org_page_comision_permanente_builds_org_no_membership(
    monkeypatch,
):
    """Comisión Permanente's real page has a <table> with no id and no
    Cargo column at all -- must still build the Organization record."""
    from backend.process.organizations import process_admin_org

    scraper = make_scraper()
    monkeypatch.setattr(
        "backend.scrapers.organizations.parse_url",
        lambda url, *a, **k: fromstring(_COMISION_PERMANENTE_TABLE_HTML),
    )

    raw_org = scraper._scrape_admin_org_page(
        "https://www.congreso.gob.pe/comision-permanente/",
        "Comisión Permanente",
        "Congreso",
        "2026",
    )

    assert raw_org is not None
    org_schema, memberships = process_admin_org(raw_org)
    assert org_schema.org_name == "Comisión Permanente"
    assert memberships == []


def test_get_chamber_organizations_skips_pages_without_table(monkeypatch):
    """Genuine failure case: neither org page has real structure -- must
    not crash, just skip both."""
    scraper = make_scraper()
    scraper.update_tracking = lambda o: o

    def fake_parse_url(url, *a, **k):
        if "junta-de-portavoces" in url:
            return fromstring(_PARLIAMENT_TABLE_HTML)
        return fromstring("<html><body>no table</body></html>")

    monkeypatch.setattr("backend.scrapers.organizations.parse_url", fake_parse_url)

    result = scraper.get_chamber_organizations("Senadores")

    assert len(result) == 1
    assert result[0].type_org == "Junta de Portavoces"
    assert result[0].chamber == "Senadores"


def test_get_joint_comision_permanente_tags_congreso_chamber(monkeypatch):
    scraper = make_scraper()
    scraper.update_tracking = lambda o: o
    monkeypatch.setattr(
        "backend.scrapers.organizations.parse_url",
        lambda url, *a, **k: fromstring(_PARLIAMENT_TABLE_HTML),
    )

    result = scraper.get_joint_comision_permanente()

    assert len(result) == 1
    assert result[0].chamber == "Congreso"
    assert result[0].type_org == "Comisión Permanente"


def test_update_tracking_scopes_by_chamber():
    """Regression: Junta de Portavoces for Senadores vs Diputados (same
    type_org, same legislative_year) must not collide in tracking."""
    engine, SessionLocal = setup_inmemory_db()
    scraper = make_scraper()
    scraper.Session = SessionLocal

    senado_org = RawOrganization(
        timestamp=datetime(2026, 1, 1),
        legislative_year="2026",
        chamber="Senadores",
        type_org="Junta de Portavoces",
        raw_html='<table class="congresistas"><tbody></tbody></table>',
    )
    tracked = scraper.update_tracking(senado_org)
    with SessionLocal() as session:
        session.add(tracked)
        session.commit()

    diputados_org = RawOrganization(
        timestamp=datetime(2026, 1, 1, 0, 0, 1),
        legislative_year="2026",
        chamber="Diputados",
        type_org="Junta de Portavoces",
        raw_html='<table class="congresistas"><tbody></tbody></table>',
    )
    tracked_diputados = scraper.update_tracking(diputados_org)

    assert tracked_diputados.changed is True
    assert tracked_diputados.last_update is True
