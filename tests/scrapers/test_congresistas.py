import json
from datetime import datetime

import pytest
from lxml.html import fromstring
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from backend.scrapers.congresistas import (
    RawCongresistasScraper,
    BASE_URL,
    API_MEMBERSHIP,
)
from backend.database.raw_models import Base, RawCongresista
from backend.scrapers.utils import get_cong_website

# ---------- helpers for DB tests ----------


def _setup_inmemory_db():
    """Create in-memory SQLite engine and session factory for tests."""
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    SessionLocal = sessionmaker(bind=engine)
    return engine, SessionLocal


# ---------- small helper methods ----------


@pytest.mark.parametrize(
    "txt, expected",
    [
        ("Cargos", True),
        ("Cargos del congresista", True),
        ("cargos de la congresista", True),
        ("Información", False),
        ("", False),
        ("otros temas", False),
    ],
)
def test_is_cargos_label(txt, expected):
    cong_scraper = RawCongresistasScraper()
    assert cong_scraper._is_cargos_label(txt.lower()) is expected


def test_score_link_text():
    cong_scraper = RawCongresistasScraper()

    base = "cargos"
    with_congresista = "cargos del congresista"
    generic = "link cualquiera"

    assert cong_scraper._score_link_text(generic) == 0
    assert cong_scraper._score_link_text(base) < cong_scraper._score_link_text(
        with_congresista
    )


def test_get_best_cargos_link():
    cong_scraper = RawCongresistasScraper()
    html = """
    <html><body>
      <a href="/link1">Otros cargos</a>
      <a href="/link2">Cargos del congresista</a>
      <a href="/link3">Página</a>
    </body></html>
    """
    doc = fromstring(html)
    base_url = "https://www.congreso.gob.pe/perfil/"

    best = cong_scraper.get_best_cargos_link(doc, base_url)
    # urljoin(base_url, "/link2") => "https://www.congreso.gob.pe/link2"
    assert best == "https://www.congreso.gob.pe/link2"


def test_get_cong_website():
    profile_content = """
    <html><body>
      <div class="web">
        <span>Web:</span>
        <span><a href="https://example.com/perfil/123">Sitio</a></span>
      </div>
    </body></html>
    """
    url = get_cong_website(profile_content)
    assert url == "https://example.com/perfil/123"


# ---------- get_dict_periodos ----------


def test_get_dict_periodos(monkeypatch):
    cong_scraper = RawCongresistasScraper()

    def fake_parse_url(url, *args, **kwargs):
        assert url == BASE_URL
        html = """
        <html><body>
          <select name="idRegistroPadre">
            <option value="1">Periodo A</option>
            <option value="2">Periodo B</option>
          </select>
        </body></html>
        """
        return fromstring(html)

    monkeypatch.setattr("backend.scrapers.congresistas.parse_url", fake_parse_url)

    cong_scraper.get_dict_periodos()
    assert cong_scraper.periods == {"Periodo A": "1", "Periodo B": "2"}


# ---------- create_raw_congresista (old periods) ----------


def test_create_raw_congresista_old_period(monkeypatch):
    cong_scraper = RawCongresistasScraper()

    monkeypatch.setattr(
        "backend.scrapers.congresistas.get_cong_website",
        lambda content: "https://example.com/perfil/old",
    )

    monkeypatch.setattr(
        cong_scraper,
        "get_profile_content",
        lambda link: "PROFILE_HTML",
    )

    period = "Parlamentario 2001 - 2006"
    cong_link = "/perfil/1"

    raw = cong_scraper.create_raw_congresista(period, cong_link)

    assert isinstance(raw, RawCongresista)
    assert raw.leg_period == period
    assert raw.website == "https://example.com/perfil/old"
    assert raw.profile_content == "PROFILE_HTML"
    assert raw.memberships_content is None


# ---------- create_raw_congresista (modern period, success path) ----------


def test_create_raw_congresista_modern_success(monkeypatch):
    cong_scraper = RawCongresistasScraper()

    # Avoid network: stub profile content
    monkeypatch.setattr(
        cong_scraper, "get_profile_content", lambda link: "<html>PROFILE</html>"
    )

    # IMPORTANT: get_cong_website is now a module-level imported function
    monkeypatch.setattr(
        "backend.scrapers.congresistas.get_cong_website",
        lambda content: "https://example.com/perfil/123",
    )

    def fake_parse_url(url, *args, **kwargs):
        if url.startswith("https://example.com/perfil"):
            html = """
            <html><body>
              <a href="/cargos/999">Cargos del congresista</a>
            </body></html>
            """
            return fromstring(html)
        if url.startswith("https://example.com/cargos/999"):
            html = """
            <html><body>
              <div id="objContents">
                <div></div>
                <div>
                  <p><iframe src="https://some.site/listar/ABC123"></iframe></p>
                </div>
              </div>
            </body></html>
            """
            return fromstring(html)
        raise AssertionError(f"Unexpected URL in fake_parse_url: {url}")

    monkeypatch.setattr("backend.scrapers.congresistas.parse_url", fake_parse_url)

    def fake_get_url_text(url):
        assert url == API_MEMBERSHIP + "ABC123"
        return '{"ok": true}'

    monkeypatch.setattr("backend.scrapers.congresistas.get_url_text", fake_get_url_text)

    raw = cong_scraper.create_raw_congresista("Congresistas 2021-2026", "/perfil/123")

    assert raw.website == "https://example.com/perfil/123"
    assert raw.profile_content == "<html>PROFILE</html>"
    assert raw.memberships_content == '{"ok": true}'


# ---------- create_raw_congresista (partial failure -> no iframe) ----------


def test_create_raw_congresista_partial_failure(monkeypatch):
    cong_scraper = RawCongresistasScraper()

    monkeypatch.setattr(cong_scraper, "get_profile_content", lambda link: "PROFILE")

    # get_cong_website is module-level now
    monkeypatch.setattr(
        "backend.scrapers.congresistas.get_cong_website",
        lambda content: "https://example.com/perfil/abc",
    )

    # parse_url always returns a doc without iframe, so the try-block fails
    def fake_parse_url(url, *args, **kwargs):
        html = "<html><body>No iframe here</body></html>"
        return fromstring(html)

    monkeypatch.setattr("backend.scrapers.congresistas.parse_url", fake_parse_url)

    # If get_best_cargos_link is still an instance method, this is fine:
    monkeypatch.setattr(
        cong_scraper,
        "get_best_cargos_link",
        lambda doc, base_url: "https://example.com/cargos-no-iframe",
    )

    raw = cong_scraper.create_raw_congresista("Congresistas 2016-2021", "/perfil/abc")

    assert isinstance(raw, RawCongresista)
    assert raw.leg_period == "Congresistas 2016-2021"
    assert raw.website == "https://example.com/perfil/abc"
    assert raw.profile_content == "PROFILE"
    # and because it fails to find the iframe / membership:
    assert raw.memberships_content is None


# ---------- extract_cong_from_period ----------


def test_extract_cong_from_period_uses_links_and_creator(monkeypatch):
    cong_scraper = RawCongresistasScraper()

    monkeypatch.setattr(
        cong_scraper, "get_urls_from_table", lambda value: ["/perfil/1", "/perfil/2"]
    )
    monkeypatch.setattr(
        cong_scraper,
        "create_raw_congresista",
        lambda period, link: f"raw-{period}-{link}",
    )

    # avoid DB + object-shape requirements. update_tracking now returns a
    # list (empty when unchanged) -- the caller .extend()s it, so the mock
    # must match that contract.
    monkeypatch.setattr(cong_scraper, "update_tracking", lambda x: [x])

    res = cong_scraper.extract_cong_from_period("Periodo X", "1")

    assert res == ["raw-Periodo X-/perfil/1", "raw-Periodo X-/perfil/2"]


# ---------- extract_and_load_all ----------


def test_extract_and_load_all_requires_periods():
    cong_scraper = RawCongresistasScraper()
    cong_scraper.periods = {}
    with pytest.raises(AssertionError):
        cong_scraper.extract_and_load_all()


def test_extract_and_load_all_calls_add(monkeypatch):
    cong_scraper = RawCongresistasScraper()
    cong_scraper.periods = {"Periodo X": "1", "Periodo Y": "2"}

    calls = []

    def fake_extract(period_key, period_value):
        calls.append((period_key, period_value))
        return [f"raw-{period_key}"]

    def fake_add():
        calls.append("add_called")
        return True

    cong_scraper.extract_cong_from_period = fake_extract
    cong_scraper.add_congresistas_to_db = fake_add

    result = cong_scraper.extract_and_load_all()

    # last iteration's raw_congresistas should be returned
    assert result == ["raw-Periodo Y"]
    # extract called twice, add called twice
    assert calls.count("add_called") == 2
    assert ("Periodo X", "1") in calls
    assert ("Periodo Y", "2") in calls


# ---------- add_congresistas_to_db ----------


def test_add_congresistas_to_db_persists(monkeypatch):
    engine, SessionLocal = _setup_inmemory_db()

    cong_scraper = RawCongresistasScraper()
    cong_scraper.engine = engine
    cong_scraper.Session = SessionLocal

    cong = RawCongresista(
        timestamp=datetime(2021, 1, 1),
        leg_period="Periodo Test",
        website="https://example.com",
        profile_content="<html></html>",
        memberships_content="{}",
    )
    cong_scraper.raw_congresistas = [cong]

    assert cong_scraper.add_congresistas_to_db() is True

    with SessionLocal() as session:
        count = session.query(RawCongresista).count()
        assert count == 1
        db_cong = session.query(RawCongresista).first()
        assert db_cong.leg_period == "Periodo Test"
        assert db_cong.website == "https://example.com"


def test_update_tracking_unchanged_returns_empty_list():
    """Regression test for the store-only-if-changed fix (/plan-eng-review
    Phase 2, 2026-09-04): re-tracking an identical congresista snapshot
    must return [] so a caller's .extend() appends nothing, instead of
    unconditionally storing a duplicate raw row on every scrape run
    forever."""
    engine, SessionLocal = _setup_inmemory_db()
    with SessionLocal() as session:
        cong_scraper = RawCongresistasScraper(session=session)

        first = RawCongresista(
            timestamp=datetime(2025, 1, 1),
            leg_period="Periodo Test",
            website="https://example.com/juan",
            profile_content="<html>v1</html>",
            memberships_content=None,
            last_update=True,
            processed=True,
            changed=False,
        )
        session.add(first)
        session.commit()

        second = RawCongresista(
            timestamp=datetime(2025, 2, 1),
            leg_period="Periodo Test",
            website="https://example.com/juan",
            profile_content="<html>v1</html>",
            memberships_content=None,
        )
        tracked = cong_scraper.update_tracking(second)

        assert tracked == []
        assert (
            session.query(RawCongresista)
            .filter(RawCongresista.last_update.is_(True))
            .count()
            == 1
        )


def test_add_congresistas_to_db_returns_false_when_empty():
    """An empty buffer is now the ROUTINE outcome of an all-unchanged
    scrape run -- must return False gracefully, not raise/assert."""
    cong_scraper = RawCongresistasScraper()
    cong_scraper.raw_congresistas = []

    assert cong_scraper.add_congresistas_to_db() is False


def test_add_congresistas_to_db_handles_sqlalchemy_error(monkeypatch):
    cong_scraper = RawCongresistasScraper()
    cong_scraper.raw_congresistas = [
        RawCongresista(
            timestamp=datetime.now(),
            leg_period="Periodo",
            website="https://example.com",
            profile_content="HTML",
            memberships_content=None,
        )
    ]

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
        return dummy_session

    cong_scraper.Session = fake_sessionmaker

    ok = cong_scraper.add_congresistas_to_db()
    assert ok is False
    assert dummy_session.rolled_back is True


# ---------- 2026-2031 chamber scraping (Phase B1) ----------

_ROSTER_ENTRY = {
    "name": "Aguinaga Recuenco, Alejandro Aurelio",
    "partido": "Fuerza Popular",
    "group": "Fuerza Popular",
    "district": "Lambayeque",
    "gender": "Masculino",
    "condition": "En Ejercicio",
    "period": "2026 - 2031",
    "email": "aaguinaga@congreso.gob.pe",
    "photo": "https://senado.congreso.gob.pe/wp-content/uploads/2026/07/foto.png",
    "url": "https://senado.congreso.gob.pe/senador/aguinaga-recuenco-alejandro-aurelio/",
}


def test_get_chamber_roster_parses_embedded_json(monkeypatch):
    cong_scraper = RawCongresistasScraper()
    import json as _json

    html = f"""
    <html><body>
      <div data-congresista-app="">
        <script type="application/json">{_json.dumps([_ROSTER_ENTRY])}</script>
      </div>
    </body></html>
    """

    def fake_parse_url(url, *args, **kwargs):
        assert url == "https://senado.congreso.gob.pe/senador/"
        return fromstring(html)

    monkeypatch.setattr("backend.scrapers.congresistas.parse_url", fake_parse_url)

    roster = cong_scraper.get_chamber_roster("Senadores")
    assert roster == [_ROSTER_ENTRY]


def test_get_chamber_roster_missing_script_returns_empty(monkeypatch):
    cong_scraper = RawCongresistasScraper()
    monkeypatch.setattr(
        "backend.scrapers.congresistas.parse_url",
        lambda *a, **k: fromstring("<html><body>no data here</body></html>"),
    )
    assert cong_scraper.get_chamber_roster("Diputados") == []


def test_get_chamber_roster_fetch_failure_returns_empty(monkeypatch):
    cong_scraper = RawCongresistasScraper()
    monkeypatch.setattr("backend.scrapers.congresistas.parse_url", lambda *a, **k: None)
    assert cong_scraper.get_chamber_roster("Senadores") == []


def test_create_chamber_congresista_sets_chamber_and_leg_period(monkeypatch):
    cong_scraper = RawCongresistasScraper()
    monkeypatch.setattr(cong_scraper, "_get_chamber_votes", lambda url: "25,642")
    monkeypatch.setattr(cong_scraper, "_get_chamber_cargos", lambda url: '{"data": []}')

    raw = cong_scraper.create_chamber_congresista("Senadores", _ROSTER_ENTRY)

    assert raw.chamber == "Senadores"
    assert raw.leg_period == "Parlamentario 2026 - 2031"
    assert raw.website == _ROSTER_ENTRY["url"]
    assert raw.memberships_content == '{"data": []}'


def test_create_chamber_congresista_without_url_skips_cargos_fetch(monkeypatch):
    """No profile url -> _get_chamber_cargos must never be called (would
    build a malformed urljoin target)."""
    cong_scraper = RawCongresistasScraper()
    monkeypatch.setattr(cong_scraper, "_get_chamber_votes", lambda url: "0")

    def _boom(url):
        raise AssertionError("_get_chamber_cargos should not be called without a url")

    monkeypatch.setattr(cong_scraper, "_get_chamber_cargos", _boom)

    entry = {**_ROSTER_ENTRY, "url": ""}
    raw = cong_scraper.create_chamber_congresista("Senadores", entry)

    assert raw.memberships_content is None


_CARGOS_TABLE_HTML = """
<html><body>
<section data-cargos-panel="">
<table class="cargos-table"><tbody>
  <tr data-cargos-row="" data-cargos-type="">
    <td data-label="Órgano o comisión"><strong></strong><small title="COMISIÓN PERMANENTE">COMISIÓN PERMANENTE</small></td>
    <td data-label="Cargo"><span class="cargos-badge cargos-badge--role">Titular</span></td>
    <td data-label="Desde">18/08/2026</td>
    <td data-label="Hasta">26/07/2027</td>
    <td data-label="Estado"><span>Activo</span></td>
  </tr>
  <tr data-cargos-row="" data-cargos-type="comision-ordinaria-legislativa">
    <td data-label="Órgano o comisión"><strong>Comisión Ordinaria Legislativa</strong><small title="COMISIÓN DE JUSTICIA Y DERECHOS HUMANOS">COMISIÓN DE JUSTICIA Y DERECHOS HUMANOS</small></td>
    <td data-label="Cargo"><span class="cargos-badge cargos-badge--role">Secretario</span></td>
    <td data-label="Desde">14/08/2026</td>
    <td data-label="Hasta">26/07/2027</td>
    <td data-label="Estado"><span>Activo</span></td>
  </tr>
  <tr data-cargos-row="" data-cargos-type="grupo-parlamentario">
    <td data-label="Órgano o comisión"><strong>Grupo Parlamentario</strong><small title="Fuerza Popular">Fuerza Popular</small></td>
    <td data-label="Cargo"><span class="cargos-badge cargos-badge--role">Titular</span></td>
    <td data-label="Desde">27/07/2026</td>
    <td data-label="Hasta">26/07/2031</td>
    <td data-label="Estado"><span>Activo</span></td>
  </tr>
</tbody></table>
</section>
</body></html>
"""


def test_get_chamber_cargos_builds_legacy_shaped_json_excluding_bancada(monkeypatch):
    cong_scraper = RawCongresistasScraper()
    monkeypatch.setattr(
        "backend.scrapers.congresistas.parse_url",
        lambda url, *a, **k: fromstring(_CARGOS_TABLE_HTML),
    )

    result = cong_scraper._get_chamber_cargos(
        "https://senado.congreso.gob.pe/senador/aguinaga-recuenco-alejandro-aurelio/"
    )

    assert result is not None
    payload = json.loads(result)["data"]
    # Grupo Parlamentario (bancada) row excluded -- only 2 of 3 rows survive.
    assert len(payload) == 2

    permanente = next(
        m for m in payload if m["desOrganoCongresista"] == "COMISIÓN PERMANENTE"
    )
    assert permanente["desCargo"] == "Titular"
    assert permanente["fechaInicio"] == "2026-08-18"
    assert permanente["fechaFin"] == "2027-07-26"

    comision = next(
        m
        for m in payload
        if m["desOrganoCongresista"] == "COMISIÓN DE JUSTICIA Y DERECHOS HUMANOS"
    )
    assert comision["desCargo"] == "Secretario"
    assert comision["fechaInicio"] == "2026-08-14"

    assert not any(m["desOrganoCongresista"] == "Fuerza Popular" for m in payload)


def test_get_chamber_cargos_roundtrips_through_process_cong_memberships(monkeypatch):
    """Confirms the synthesized JSON is byte-compatible with the existing
    (unchanged) legacy membership-processing pipeline."""
    from backend.database.raw_models import RawCongresista
    from backend.database.models import Congresista
    from backend.process.congresistas import process_cong_memberships

    cong_scraper = RawCongresistasScraper()
    monkeypatch.setattr(
        "backend.scrapers.congresistas.parse_url",
        lambda url, *a, **k: fromstring(_CARGOS_TABLE_HTML),
    )
    memberships_content = cong_scraper._get_chamber_cargos(
        "https://senado.congreso.gob.pe/senador/aguinaga-recuenco-alejandro-aurelio/"
    )

    raw_cong = RawCongresista(
        timestamp=datetime.now(),
        leg_period="Parlamentario 2026 - 2031",
        memberships_content=memberships_content,
    )
    cong = Congresista(full_name="Aguinaga Recuenco, Alejandro Aurelio")

    memberships = process_cong_memberships(raw_cong, cong)

    assert len(memberships) == 2
    permanente = next(m for m in memberships if m.org_name == "COMISIÓN PERMANENTE")
    assert permanente.org_type == "Administrativo"
    assert permanente.start_date.isoformat() == "2026-08-18"
    comision = next(
        m
        for m in memberships
        if m.org_name == "COMISIÓN DE JUSTICIA Y DERECHOS HUMANOS"
    )
    assert comision.org_type == "Comisión"


def test_get_chamber_cargos_skips_row_missing_org_name(monkeypatch):
    html = """
    <html><body><table class="cargos-table"><tbody>
      <tr data-cargos-row="" data-cargos-type="">
        <td data-label="Órgano o comisión"><strong></strong><small title=""></small></td>
        <td data-label="Cargo"><span class="cargos-badge cargos-badge--role">Titular</span></td>
        <td data-label="Desde">18/08/2026</td>
        <td data-label="Hasta">26/07/2027</td>
      </tr>
    </tbody></table></body></html>
    """
    cong_scraper = RawCongresistasScraper()
    monkeypatch.setattr(
        "backend.scrapers.congresistas.parse_url",
        lambda url, *a, **k: fromstring(html),
    )

    result = cong_scraper._get_chamber_cargos(
        "https://senado.congreso.gob.pe/senador/x/"
    )
    assert result is None


def test_get_chamber_cargos_skips_row_with_malformed_date(monkeypatch):
    html = """
    <html><body><table class="cargos-table"><tbody>
      <tr data-cargos-row="" data-cargos-type="">
        <td data-label="Órgano o comisión"><strong></strong><small title="COMISIÓN PERMANENTE">COMISIÓN PERMANENTE</small></td>
        <td data-label="Cargo"><span class="cargos-badge cargos-badge--role">Titular</span></td>
        <td data-label="Desde">not-a-date</td>
        <td data-label="Hasta">26/07/2027</td>
      </tr>
    </tbody></table></body></html>
    """
    cong_scraper = RawCongresistasScraper()
    monkeypatch.setattr(
        "backend.scrapers.congresistas.parse_url",
        lambda url, *a, **k: fromstring(html),
    )

    result = cong_scraper._get_chamber_cargos(
        "https://senado.congreso.gob.pe/senador/x/"
    )
    assert result is None


def test_parse_cargos_date_converts_ddmmyyyy_to_iso():
    cong_scraper = RawCongresistasScraper()
    assert cong_scraper._parse_cargos_date("18/08/2026") == "2026-08-18"
    assert cong_scraper._parse_cargos_date(None) is None
    assert cong_scraper._parse_cargos_date("") is None
    assert cong_scraper._parse_cargos_date("garbage") is None


def test_synthesized_chamber_profile_roundtrips_through_process_profile_content(
    monkeypatch,
):
    """CRITICAL: proves the scraper's synthetic HTML is byte-compatible with
    process_profile_content()'s existing xpath contract -- the adapter
    pattern this Phase B1 design relies on for zero process-layer changes.

    full_name is asserted in "Nombres Apellidos" order: process_profile_content
    now runs the .nombres text through split_and_sort_name, correctly
    reordering the roster's raw "Apellidos, Nombres" format (found 2026-09
    -- the previous version of this test asserted the unconverted comma
    string as if it were correct, which is exactly the bug that shipped)."""
    from backend.process.congresistas import process_profile_content

    cong_scraper = RawCongresistasScraper()
    monkeypatch.setattr(cong_scraper, "_get_chamber_votes", lambda url: "25,642")
    monkeypatch.setattr(cong_scraper, "_get_chamber_cargos", lambda url: None)

    raw = cong_scraper.create_chamber_congresista("Senadores", _ROSTER_ENTRY)

    cong, orgs, memberships = process_profile_content(raw, {})

    assert cong.full_name == "Alejandro Aurelio Aguinaga Recuenco"
    assert cong.first_name == "Alejandro Aurelio"
    assert cong.last_name == "Aguinaga Recuenco"
    assert cong.photo_url == _ROSTER_ENTRY["photo"]
    assert [o.org_name for o in orgs] == ["Fuerza Popular", "Senado de la República"]
    assert memberships[0].org_name == "Fuerza Popular"
    assert memberships[1].org_name == "Senado de la República"
    assert memberships[1].votes_in_election == 25642
    assert memberships[1].role.value == "Senador"


def test_extract_chamber_congresistas_tracks_all_entries(monkeypatch):
    cong_scraper = RawCongresistasScraper()
    monkeypatch.setattr(cong_scraper, "_get_chamber_votes", lambda url: "0")
    monkeypatch.setattr(cong_scraper, "update_tracking", lambda c: [c])

    second_entry = dict(_ROSTER_ENTRY, name="Otro, Congresista")
    result = cong_scraper.extract_chamber_congresistas(
        "Diputados", [_ROSTER_ENTRY, second_entry]
    )

    assert len(result) == 2
    assert all(r.chamber == "Diputados" for r in result)
    assert cong_scraper.raw_congresistas == result
