import html as html_lib
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
    def _parse_parliament_table(html_doc) -> list[dict]:
        """Parse a `table#parliamentTable`-shaped page (confirmed live
        2026-08-31 for Junta de Portavoces) into row dicts keyed by header
        label -- column set/order varies by page (e.g. committees have 5
        columns incl. Foto, this admin-org table has 4), so cells are
        matched by header text, not position.
        """
        table = html_doc.xpath('//*[@id="parliamentTable"]')
        if not table:
            return []
        headers = [
            th.text_content().strip().upper() for th in table[0].xpath(".//thead//th")
        ]
        if not headers:
            return []
        rows = []
        for tr in table[0].xpath(".//tbody/tr"):
            cells = tr.xpath("./td")
            if len(cells) != len(headers):
                continue
            rows.append(dict(zip(headers, cells)))
        return rows

    @staticmethod
    def _build_admin_org_html(rows: list[dict]) -> str:
        """Synthesize the `.congresistas`-shaped HTML (5 cells: _, name,
        website, _, cargo, with a throwaway header row) that
        process_admin_org() (backend/process/organizations.py) already
        parses -- keeps that function's contract stable, zero changes needed
        there for the 2026-2031 path.
        """
        body_rows = ["<tr><td>h</td><td>h</td><td>h</td><td>h</td><td>h</td></tr>"]
        for row in rows:
            name_cell = row.get("APELLIDOS Y NOMBRES")
            cargo_cell = row.get("CARGO")
            if name_cell is None or cargo_cell is None:
                continue
            name_text = html_lib.escape(name_cell.text_content().strip())
            cargo_text = html_lib.escape(cargo_cell.text_content().strip())
            links = name_cell.xpath(".//a/@href")
            website = links[0] if links else "#"
            body_rows.append(
                "<tr><td></td>"
                f"<td>{name_text}</td>"
                f'<td><a href="{html_lib.escape(website)}">link</a></td>'
                "<td></td>"
                f"<td>{cargo_text}</td></tr>"
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
        rows = self._parse_parliament_table(html_doc)
        if not rows:
            logger.warning(f"No table#parliamentTable found for {type_org} at {url}")
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

        Confirmed live 2026-08-31: Junta de Portavoces exposes
        table#parliamentTable. Mesa Directiva did not expose that table in
        this pass (likely prose/a different layout) -- handled defensively
        below, producing no row rather than guessing a wrong structure.
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
