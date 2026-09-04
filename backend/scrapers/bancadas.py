import html as html_lib
from loguru import logger
from typing import Literal
from datetime import datetime

from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeoutError

from sqlalchemy.orm import sessionmaker
from sqlalchemy import create_engine
from sqlalchemy.exc import SQLAlchemyError

from backend.config import settings
from backend.core.constants import CHAMBER_LEG_PERIOD_LABEL
from backend.database.raw_models import RawBancada
from backend.scrapers.utils import parse_url


BASE_URL = "https://www3.congreso.gob.pe/pagina/grupos-parlamentarios"
DB_PATH = settings.DB_URL


class RawBancadaScraper:
    """
    Class to scrape Grupos Parlamentarios' raw data from the congress web page.

    Two independent scraping paths (see section headers below): LEGACY
    (through 2021-2026) scrapes a real per-bancada membership table from
    www3.congreso.gob.pe. 2026-2031 BICAMERAL TERM does NOT scrape a
    membership table at all -- the real grupos-parlamentarios/ page on the
    new sites carries no member data (confirmed live 2026-08-31, Phase B
    plan Step B0 item 2) -- membership is instead derived from the
    congresistas roster's own `group` field and synthesized into the same
    HTML shape process_bancada() already parses. Both paths write RawBancada
    rows to the same table (chamber column: NULL for legacy, "Senadores"/
    "Diputados" for the new term).
    """

    def __init__(self):
        # Engine and session maker for DB
        self.engine = create_engine(DB_PATH)
        self.url = BASE_URL
        self.Session = sessionmaker(bind=self.engine)

    # =====================================================================
    # LEGACY (through 2021-2026) -- www3.congreso.gob.pe, dropdown-driven,
    # real per-bancada membership table (.table-cng)
    # =====================================================================

    def get_options(
        self,
        url: str,
        select_name: Literal["idPeriodo[]", "keyCondicion[]"] = "idPeriodo[]",
    ) -> dict[str, str]:
        """
        Functions that fetchs all the possible options that are in the dropdown list in the html file

        Args:
            - url (str): link to the html
            - select_name (str): the name of the dropdown element
        """
        parse = parse_url(url)

        if parse is None:
            return {}

        options = parse.xpath(f'//*[@name="{select_name}"]/option')
        return {
            elem.text: elem.get("value") for elem in options if elem.text is not None
        }

    def get_html_with_selections(
        self, url: str, period_value: str, condition_value: str = ""
    ) -> str | None:
        browser = None
        page = None

        try:
            with sync_playwright() as p:
                browser = p.chromium.launch(headless=True)

                try:
                    page = browser.new_page()
                    page.goto(url, wait_until="domcontentloaded")

                    page.wait_for_selector(
                        'select[name="idPeriodo[]"]', state="attached"
                    )
                    page.wait_for_selector(
                        'select[name="keyCondicion[]"]', state="attached"
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
                            "selector": 'select[name="idPeriodo[]"]',
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
                            "selector": 'select[name="idPeriodo[]"]',
                            "value": period_value,
                        },
                    )

                    page.evaluate(
                        js_set_select,
                        {
                            "selector": 'select[name="keyCondicion[]"]',
                            "value": condition_value,
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
                            "selector": 'select[name="keyCondicion[]"]',
                            "value": condition_value,
                        },
                    )

                    page.wait_for_selector(".table-cng", state="visible")
                    page.wait_for_timeout(1000)

                    return page.content()

                finally:
                    browser.close()

        except PlaywrightTimeoutError as e:
            logger.error(f"Error found: {e}")
            return None

    def get_raw_bancadas(self, only_current: bool = True) -> None:
        dict_periods = self.get_options(url=self.url, select_name="idPeriodo[]")
        dict_condicion = {"en Ejercicio": "eej"}

        if only_current:
            # Only scrape current period
            key, val = list(dict_periods.items())[0]
            dict_periods = {key: val}

        final_lst = []
        for period_key, period in dict_periods.items():
            cond_key, cond = next(iter(dict_condicion.items()))
            logger.info(
                f"Scraping bancada for period {period_key} and condition {cond_key}"
            )

            html = self.get_html_with_selections(self.url, period, cond)

            if html is not None:
                new_bancada = RawBancada(
                    timestamp=datetime.now(),
                    legislative_period=period_key,
                    raw_html=html,
                    changed=False,
                    processed=False,
                    last_update=True,
                )
                final_lst.append(self.update_tracking(new_bancada))

        self.bancadas_list = final_lst
        logger.success(
            f"Successfully extracted {len(self.bancadas_list)} raw html bancadas"
        )

    # =====================================================================
    # 2026-2031 BICAMERAL TERM -- derived from the congresistas roster, not
    # scraped from grupos-parlamentarios/ directly (see class docstring)
    # =====================================================================

    @staticmethod
    def build_chamber_bancada_html(roster: list[dict]) -> str:
        """Synthesize a `table.table-cng`-shaped HTML blob -- the same shape
        process_bancada() (backend/process/bancadas.py) already parses --
        from the congresistas roster's `group` field, grouped by bancada.

        Confirmed live 2026-08-31 (Phase B plan, Step B0 item 2): the real
        grupos-parlamentarios/ page carries no per-bancada membership table
        for 2026-2031 (just a static name + regulations-doc-link list) --
        the congresistas roster is the only source of "who belongs to which
        bancada" for the new term, so this reconstructs process_bancada()'s
        expected internal shape instead of adding a second parser. Each
        membership row uses 2 <td> cells (not 1) because process_bancada()
        treats a single-<td> row with no <h2> as a row to skip, not a
        membership row -- see its `len(childs) == 1` branch.
        """
        groups: dict[str, list[str]] = {}
        for entry in roster:
            group = (entry.get("group") or "").strip()
            name = (entry.get("name") or "").strip()
            if not group or not name:
                continue
            groups.setdefault(group, []).append(name)

        rows: list[str] = []
        for bancada_name, members in groups.items():
            rows.append(f"<tr><td><h2>{html_lib.escape(bancada_name)}</h2></td></tr>")
            for member_name in members:
                rows.append(
                    "<tr><td></td>"
                    f'<td><span class="conginfo">{html_lib.escape(member_name)}</span></td></tr>'
                )

        return f'<table class="table-cng"><tbody>{"".join(rows)}</tbody></table>'

    def get_chamber_bancadas(
        self, chamber: str, roster: list[dict]
    ) -> list[RawBancada]:
        """Build+track the one RawBancada row for one chamber's 2026-2031
        bancadas, derived from an already-fetched congresista roster (see
        RawCongresistasScraper.get_chamber_roster)."""
        raw_html = self.build_chamber_bancada_html(roster)
        new_bancada = RawBancada(
            timestamp=datetime.now(),
            legislative_period=CHAMBER_LEG_PERIOD_LABEL,
            chamber=chamber,
            raw_html=raw_html,
            changed=False,
            processed=False,
            last_update=True,
        )
        self.bancadas_list = [self.update_tracking(new_bancada)]
        return self.bancadas_list

    # =====================================================================
    # SHARED -- used by both the legacy and 2026-2031 code paths above
    # =====================================================================

    def update_tracking(self, bancada: RawBancada) -> RawBancada:
        """Update the tracking columns of a RawBancada object.

        Scoped by (legislative_period, chamber): the chamber filter matters
        for the 2026-2031 path specifically -- both chambers share the same
        legislative_period label ("Parlamentario 2026 - 2031"), so without
        it a Senado scrape and a Diputados scrape would collide and clobber
        each other's last_update tracking.
        """

        with self.Session() as session:
            last_bancada = (
                session.query(RawBancada)
                .filter(
                    RawBancada.legislative_period == bancada.legislative_period,
                    RawBancada.chamber == bancada.chamber,
                    RawBancada.last_update.is_(True),
                )
                .order_by(RawBancada.timestamp.desc())
                .first()
            )

            # First ever version of this bancada
            if last_bancada is None:
                bancada.changed = True
                bancada.last_update = True
                bancada.processed = False
            else:
                # Compare last vs new
                bancada.changed = self._snapshot_changed(bancada, last_bancada)
                bancada.last_update = True
                bancada.processed = not bancada.changed

                # Update the old version AFTER comparison
                last_bancada.last_update = False
                session.add(last_bancada)
                session.commit()

            return bancada

    @staticmethod
    def _snapshot_changed(current: RawBancada, previous: RawBancada) -> bool:
        return (
            current.legislative_period != previous.legislative_period
            or current.raw_html != previous.raw_html
        )

    def add_bancadas_to_db(self) -> bool:
        """
        Add the bancadas to the database.
        Returns True on success, False on failure.
        """
        assert self.bancadas_list, "Bancadas must be scraped before it can be saved"

        session = self.Session()

        try:
            session.bulk_save_objects(self.bancadas_list)
            session.commit()
            logger.success(
                f"Added {len(self.bancadas_list)} bancadas to Raw Bancadas table"
            )
            return True
        except SQLAlchemyError as e:
            logger.error(f"Failed to add bancadas: {e}")
            session.rollback()
            return False
        finally:
            # Close Session
            session.close()


if __name__ == "__main__":
    scraper = RawBancadaScraper()
    scraper.get_raw_bancadas(only_current=False)
    scraper.add_bancadas_to_db()
