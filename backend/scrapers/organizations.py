import html as html_lib
import json
from loguru import logger
from typing import Literal
from datetime import datetime

from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeoutError

from sqlalchemy.orm import sessionmaker
from sqlalchemy import create_engine
from sqlalchemy.exc import SQLAlchemyError

from backend.config import settings
from backend.core.constants import CHAMBER_BASE_URLS
from backend.database.raw_models import RawOrganization
from backend.scrapers.utils import parse_url


BASE_URLS = {
    "Junta de Portavoces": "https://www3.congreso.gob.pe/pagina/junta-de-portavoces",
    "Consejo Directivo": "https://www3.congreso.gob.pe/pagina/consejodirectivo",
    "Mesa Directiva": "https://www3.congreso.gob.pe/pagina/mesa-directiva",
    "Comisión Permanente": "https://www3.congreso.gob.pe/pagina/comision-permanente",
}

DB_PATH = settings.DB_URL

# 2026-2031 term. "Consejo Directivo" is deliberately absent -- confirmed
# live 2026-08-31 that diputados.congreso.gob.pe/consejo-directivo/ 404s;
# treated as removed under the new structure (Phase B plan, Step B0 item 4).
# Comisión Permanente is scraped once as a single joint entity, not per
# chamber -- see get_chamber_organizations.
CHAMBER_ADMIN_ORG_SLUGS = {
    "Junta de Portavoces": "junta-de-portavoces",
    "Mesa Directiva": "mesa-directiva",
}
COMISION_PERMANENTE_URL = "https://www.congreso.gob.pe/comision-permanente/"
CHAMBER_ORG_YEAR = "2026"


class RawOrganizationScraper:
    """
    Class to scrape admin-org raw data from the congress web page (Junta de
    Portavoces, Consejo Directivo, Mesa Directiva, Comisión Permanente).

    Two independent scraping paths (see section headers below): LEGACY
    (through 2021-2026) scrapes www3.congreso.gob.pe's year dropdown per
    admin org, one row per (type_org, year). 2026-2031 BICAMERAL TERM
    scrapes the new per-chamber Junta de Portavoces/Mesa Directiva pages
    (Consejo Directivo dropped -- 404-confirmed live 2026-08-31, see
    CHAMBER_ADMIN_ORG_SLUGS) plus the single joint Comisión Permanente page,
    tagged chamber="Congreso". Both paths write RawOrganization rows to the
    same table (chamber column: NULL for legacy, "Senadores"/"Diputados"/
    "Congreso" for the new term) and are both consumed unmodified by
    process_admin_org() (backend/process/organizations.py).
    """

    def __init__(self):
        # Engine and session maker for DB
        self.engine = create_engine(DB_PATH)
        self.urls = BASE_URLS
        self.Session = sessionmaker(bind=self.engine)

    # =====================================================================
    # LEGACY (through 2021-2026) -- www3.congreso.gob.pe, year dropdown
    # per admin org
    # =====================================================================

    def get_options(
        self,
        url: str,
        select_name: Literal["idRegistroPadre"] = "idRegistroPadre",
    ) -> dict[str, str]:
        """
        Functions that fetchs all the possible options that are in the dropdown list in the html file

        Args:
            - url (str): link to the html
            - select_name (str): the name of the dropdown element
        """
        parse = parse_url(url)
        if parse is None:
            logger.warning(f"Failed to parse options page: {url}")
            return {}
        options = parse.xpath(f'//*[@name="{select_name}"]/option')
        return {
            elem.text: elem.get("value") for elem in options if elem.text is not None
        }

    def get_html_with_selections(self, url: str, period_value: str) -> str | None:
        browser = None
        page = None

        try:
            with sync_playwright() as p:
                browser = p.chromium.launch(headless=True)

                try:
                    page = browser.new_page()
                    page.goto(url, wait_until="domcontentloaded")

                    page.wait_for_selector(
                        'select[name="idRegistroPadre"]', state="attached"
                    )

                    js_set_select = """
                    ({ selector, value }) => {
                        const sel = document.querySelector(selector);
                        if (!sel) {
                            return false;
                        }

                        for (const opt of sel.options) {
                            opt.selected = (opt.value === value);
                        }

                        sel.dispatchEvent(new Event("change", { bubbles: true }));
                        return Array.from(sel.selectedOptions).map(opt => opt.value);
                    }
                    """

                    page.evaluate(
                        js_set_select,
                        {
                            "selector": 'select[name="idRegistroPadre"]',
                            "value": period_value,
                        },
                    )
                    page.wait_for_function(
                        """
                        ({ selector, value }) => {
                            const sel = document.querySelector(selector);
                            return !!sel && Array.from(sel.selectedOptions).some(
                                opt => opt.value === value
                            );
                        }
                        """,
                        arg={
                            "selector": 'select[name="idRegistroPadre"]',
                            "value": period_value,
                        },
                    )

                    page.wait_for_selector("table.congresistas", state="visible")
                    page.wait_for_timeout(1000)

                    return page.content()

                finally:
                    browser.close()

        except PlaywrightTimeoutError as e:
            logger.error(f"Error found: {e}")
            return None

    def get_raw_organizations(self, only_current: bool = True) -> None:
        final_lst = []
        for type_org, url in self.urls.items():
            dict_periods = self.get_options(url=url, select_name="idRegistroPadre")

            if not dict_periods:
                logger.warning(f"No years found for type={type_org}")
                continue

            if only_current:
                # Only scrape current period
                key, val = list(dict_periods.items())[0]
                dict_periods = {key: val}

            for year, value in dict_periods.items():
                logger.info(
                    f"Scraping organization for year {year} and type {type_org}"
                )

                html = self.get_html_with_selections(url, value)

                if html is not None:
                    new_org = RawOrganization(
                        timestamp=datetime.now(),
                        org_link=url,
                        legislative_year=year,
                        type_org=type_org,
                        raw_html=html,
                        processed=False,
                        last_update=True,
                    )

                    final_lst.append(self.update_tracking(new_org))

        self.organizations_list = final_lst
        logger.success(
            f"Successfully extracted {len(self.organizations_list)} raw html organization"
        )

    # SHARED (used by update_tracking() below, for both paths)
    @staticmethod
    def _snapshot_changed(current: RawOrganization, previous: RawOrganization) -> bool:
        return (
            current.legislative_year != previous.legislative_year
            or current.type_org != previous.type_org
            or current.raw_html != previous.raw_html
        )

    # =====================================================================
    # 2026-2031 BICAMERAL TERM -- {senado|diputados}.../junta-de-portavoces/,
    # .../mesa-directiva/, plus the single joint Comisión Permanente page
    # =====================================================================

    @staticmethod
    def _find_admin_org_table(html_doc):
        """Locate the members table for an admin-org page. Tries
        id="parliamentTable" first (Junta de Portavoces, confirmed live
        2026-08-31); falls back to any <table> whose <thead> contains a
        header matching "APELLIDOS" (case/accent-insensitive) -- confirmed
        live 2026-09-02 for Comisión Permanente, which has the same
        4-column shape but no id at all. Content-based, not positional, so
        it doesn't depend on this being the only <table> on the page.
        """
        table = html_doc.xpath('//*[@id="parliamentTable"]')
        if table:
            return table[0]
        lower = "abcdefghijklmnopqrstuvwxyzáéíóúñ"
        upper = "ABCDEFGHIJKLMNOPQRSTUVWXYZÁÉÍÓÚÑ"
        fallback = html_doc.xpath(
            f"//table[.//thead//th[contains(translate(normalize-space(text()), "
            f'"{upper}", "{lower}"), "apellidos")]]'
        )
        return fallback[0] if fallback else None

    @staticmethod
    def _parse_parliament_table(html_doc) -> list[dict]:
        """Parse an admin-org members table into normalized row dicts
        {"name": str, "website": str | None, "cargo": str | None}. Column
        set/order varies by page (e.g. Comisión Permanente has no Cargo
        column at all -- confirmed live 2026-09-02), so cells are matched
        by header text, not position, and a missing CARGO header simply
        yields cargo=None for every row rather than dropping them.
        """
        table = RawOrganizationScraper._find_admin_org_table(html_doc)
        if table is None:
            return []
        headers = [
            th.text_content().strip().upper() for th in table.xpath(".//thead//th")
        ]
        if "APELLIDOS Y NOMBRES" not in headers:
            return []
        name_idx = headers.index("APELLIDOS Y NOMBRES")
        cargo_idx = headers.index("CARGO") if "CARGO" in headers else None

        rows = []
        for tr in table.xpath(".//tbody/tr"):
            cells = tr.xpath("./td")
            if len(cells) != len(headers):
                continue
            name_cell = cells[name_idx]
            links = name_cell.xpath(".//a/@href")
            rows.append(
                {
                    "name": name_cell.text_content().strip(),
                    "website": links[0] if links else None,
                    "cargo": (
                        cells[cargo_idx].text_content().strip()
                        if cargo_idx is not None
                        else None
                    ),
                }
            )
        return rows

    @staticmethod
    def _parse_mesa_directiva_senado(html_doc) -> list[dict]:
        """Parse the Senado Mesa Directiva page -- div-based, not a table.
        Confirmed live 2026-09-02: `#mesa-directiva-section` holds
        `.md-profile` divs (inside `.md-top-row`/`.md-bottom-row`), each
        with a `.md-name` link (name + profile url) and a `.md-role` span.
        """
        profiles = html_doc.xpath(
            '//*[@id="mesa-directiva-section"]//div[@class="md-profile"]'
        )
        rows = []
        for profile in profiles:
            name_links = profile.xpath('.//a[@class="md-name"]')
            if not name_links:
                continue
            role_nodes = profile.xpath('.//span[@class="md-role"]')
            rows.append(
                {
                    "name": name_links[0].text_content().strip(),
                    "website": name_links[0].get("href"),
                    "cargo": (
                        role_nodes[0].text_content().strip() if role_nodes else None
                    ),
                }
            )
        return rows

    @staticmethod
    def _parse_mesa_directiva_diputados(html_doc) -> list[dict]:
        """Parse the Diputados Mesa Directiva page.

        Correction (2026-09-02, live spot-check after implementation): the
        page's `.congresista-results__body[data-results-body]` div-based
        rows (as rendered in a browser) are populated by client-side
        JavaScript -- the raw HTTP response `parse_url` fetches has that
        container present but EMPTY, so an xpath over `.congresista-row`
        children always finds zero rows against real traffic (caught by a
        live spot-check, not by the unit tests, which used a pre-rendered
        fixture). The real data source is a `<script type="application/
        json" data-congresista-dataset>` payload embedded earlier in the
        same raw HTML -- same idiom as get_chamber_roster()'s embedded-JSON
        pattern, just a different attribute name and shape: each entry has
        `name`, `campo_adicional` (role/cargo, e.g. "Presidencia"), and
        `url` (profile link).
        """
        scripts = html_doc.xpath("//script[@data-congresista-dataset]/text()")
        if not scripts:
            return []
        try:
            entries = json.loads(scripts[0])
        except (ValueError, TypeError):
            return []
        if not isinstance(entries, list):
            return []

        rows = []
        for entry in entries:
            name = (entry.get("name") or "").strip()
            if not name:
                continue
            rows.append(
                {
                    "name": name,
                    "website": entry.get("url") or None,
                    "cargo": (entry.get("campo_adicional") or "").strip() or None,
                }
            )
        return rows

    @staticmethod
    def _build_admin_org_html(rows: list[dict]) -> str:
        """Synthesize the `.congresistas`-shaped HTML (5 cells: _, name,
        website, _, cargo, with a throwaway header row) that
        process_admin_org() (backend/process/organizations.py) already
        parses -- keeps that function's contract stable, zero changes
        needed there for the 2026-2031 path.

        The cargo cell is ALWAYS left blank here, regardless of what any
        parser found: per the confirmed 2026-2031 design, ALL memberships
        for this term (admin-org and committee alike) come from each
        congresista's own cargos page (congresistas.py::_get_chamber_cargos),
        not from these org-page scrapes. This function is exclusively used
        by the 2026-2031 path (legacy's get_raw_organizations never calls
        it), so this is safe and doesn't touch legacy behavior.
        process_admin_org()'s existing "skip rows with blank cargo" logic
        then naturally guarantees zero Membership rows here, while org
        creation (independent of row content) is unaffected.
        """
        body_rows = ["<tr><td>h</td><td>h</td><td>h</td><td>h</td><td>h</td></tr>"]
        for row in rows:
            name_text = (row.get("name") or "").strip()
            if not name_text:
                continue
            website = row.get("website") or "#"
            body_rows.append(
                "<tr><td></td>"
                f"<td>{html_lib.escape(name_text)}</td>"
                f'<td><a href="{html_lib.escape(website)}">link</a></td>'
                "<td></td>"
                "<td></td></tr>"
            )
        return (
            f'<table class="congresistas"><tbody>{"".join(body_rows)}</tbody></table>'
        )

    def _scrape_admin_org_page(
        self, url: str, type_org: str, chamber: str, year: str
    ) -> RawOrganization | None:
        html_doc = parse_url(url)
        if html_doc is None:
            logger.warning(f"Failed to fetch {type_org} page: {url}")
            return None

        if type_org == "Mesa Directiva" and chamber == "Senadores":
            rows = self._parse_mesa_directiva_senado(html_doc)
        elif type_org == "Mesa Directiva" and chamber == "Diputados":
            rows = self._parse_mesa_directiva_diputados(html_doc)
        else:
            rows = self._parse_parliament_table(html_doc)

        if not rows:
            logger.warning(f"No members found for {type_org} at {url}")
            return None
        return RawOrganization(
            timestamp=datetime.now(),
            org_link=url,
            legislative_year=year,
            chamber=chamber,
            type_org=type_org,
            raw_html=self._build_admin_org_html(rows),
            processed=False,
            last_update=True,
        )

    def get_chamber_organizations(self, chamber: str) -> list[RawOrganization]:
        """Scrape 2026-2031 per-chamber admin orgs: Junta de Portavoces and
        Mesa Directiva. "Consejo Directivo" is deliberately not scraped for
        this term (404-confirmed, see CHAMBER_ADMIN_ORG_SLUGS). Comisión
        Permanente is joint, not per-chamber -- see
        get_joint_comision_permanente, called separately/once.

        Confirmed live 2026-09-02: Junta de Portavoces still exposes
        table#parliamentTable (unchanged); Mesa Directiva uses a different
        div-based structure per chamber, with no table at all -- see
        _parse_mesa_directiva_senado/_parse_mesa_directiva_diputados. Only
        org existence is built from any of these pages -- membership comes
        from each congresista's own cargos page instead (see
        congresistas.py::_get_chamber_cargos and _build_admin_org_html's
        docstring).
        """
        base_url = CHAMBER_BASE_URLS[chamber]
        results = [
            org
            for type_org, slug in CHAMBER_ADMIN_ORG_SLUGS.items()
            if (
                org := self._scrape_admin_org_page(
                    f"{base_url}/{slug}/", type_org, chamber, CHAMBER_ORG_YEAR
                )
            )
            is not None
        ]
        self.organizations_list = [self.update_tracking(org) for org in results]
        return self.organizations_list

    def get_joint_comision_permanente(self) -> list[RawOrganization]:
        """Scrape the single joint Comisión Permanente page, tagged
        chamber="Congreso" per CHAMBER_LABEL_TO_ORG_NAME's existing
        joint-entity convention. Call once, not per chamber.
        """
        org = self._scrape_admin_org_page(
            COMISION_PERMANENTE_URL,
            "Comisión Permanente",
            "Congreso",
            CHAMBER_ORG_YEAR,
        )
        self.organizations_list = [self.update_tracking(org)] if org else []
        return self.organizations_list

    # =====================================================================
    # SHARED -- used by both the legacy and 2026-2031 code paths above
    # =====================================================================

    def update_tracking(self, org: RawOrganization) -> RawOrganization:
        """Update the tracking columns of a RawOrganization object.

        Scoped by (type_org, legislative_year, chamber) -- the chamber
        filter matters for the 2026-2031 path specifically, since e.g.
        "Junta de Portavoces" for Senadores and Diputados would otherwise
        share the same (type_org, year) pair and collide.
        """

        with self.Session() as session:
            last_org = (
                session.query(RawOrganization)
                .filter(
                    RawOrganization.type_org == org.type_org,
                    RawOrganization.legislative_year == org.legislative_year,
                    RawOrganization.chamber == org.chamber,
                    RawOrganization.last_update,
                )
                .order_by(RawOrganization.timestamp.desc())
                .first()
            )

            # First ever version of this org
            if last_org is None:
                org.changed = True
                org.last_update = True
                org.processed = False
            else:
                # Compare last vs new
                org.changed = self._snapshot_changed(org, last_org)
                org.last_update = True
                org.processed = not org.changed

                # Update the old version AFTER comparison
                last_org.last_update = False
                session.add(last_org)
                session.commit()

            return org

    def add_organizations_to_db(self) -> bool:
        """
        Add the organizations to the database.
        Returns True on success, False on failure.
        """
        assert self.organizations_list, (
            "Organizations must be scraped before it can be saved"
        )

        session = self.Session()

        try:
            session.bulk_save_objects(self.organizations_list)
            session.commit()
            logger.success(
                f"Added {len(self.organizations_list)} organizations to Raw Organizations table"
            )
            return True
        except SQLAlchemyError as e:
            logger.error(f"Failed to add organizations: {e}")
            session.rollback()
            return False
        finally:
            # Close Session
            session.close()
