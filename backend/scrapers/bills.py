import json
from collections.abc import Callable
from datetime import datetime
from loguru import logger
from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeoutError

from sqlalchemy import select

from backend.core.constants import (
    CHAMBER_LABEL_TO_ID_SUFFIX,
    CHAMBER_LABEL_TO_ROUTE_SLUG,
    LEG_PERIOD_TO_PER_PAR_ID,
)
from backend.database.raw_models import RawBill
from backend.scrapers.base import SharedRawScraperBase
from backend.scrapers.utils import get_url_text

BASE_URL = "https://wb2server.congreso.gob.pe/spley-portal/#"

# 2026-2031 term: RawBill.id uses the full period string ("00006-2026-2031-S",
# confirmed live and matching chamber_label_from_id()'s expectations), but
# the SPA's own per-chamber detail ROUTE uses the bare period-start year
# instead ({BASE_URL}/senado/expediente/2026/6) -- confirmed live 2026-09-01
# by extracting the real router-generated href from a live search result
# page (an earlier session's guess of the full period string in the route
# was wrong and never actually resolved; it happened to look like it worked
# once due to a stale/cached opaque token, not because the route was
# correct). Same bare-year convention as motions.py's detail URL after all
# -- no asymmetry between the two entities' URL shapes.
CHAMBER_LEG_PERIOD = "2026-2031"


class RawBillScraper(SharedRawScraperBase):
    """
    Class to scrape and store raw bill information.

    Two independent scraping paths (see section headers below): LEGACY
    (through 2021-2026) builds bill_id/bill_url from a bare year via
    scrape_bill(). 2026-2031 BICAMERAL TERM builds bill_id from the fixed
    period string but bill_url from the bare period-start year (see the
    CHAMBER_LEG_PERIOD comment above) via scrape_chamber_bill(). Both are
    thin wrappers that build id/url and delegate to the SAME
    __fetch_and_track_bill helper (SHARED, below) for the actual
    fetch/parse/track sequence -- chamber-agnostic, only the id/url and
    which create_* method builds the row differ.
    """

    def __init__(self, session=None, engine=None):
        super().__init__(session=session, engine=engine)

        # Mapping raw section name to RawBill attribute name
        self.section_mapping = {
            "general": "general",
            "firmantes": "congresistas",
            "estudioComisiones": "committees",
            "seguimientos": "steps",
        }

        # List of raw bills objects
        self.raw_bills = []

    # =====================================================================
    # SHARED -- used by both the legacy and 2026-2031 code paths below.
    # Both are already chamber-agnostic (only care about the resolved
    # id/url passed in), so no changes are needed for the new term.
    # =====================================================================

    def __get_existing_api_url(self, bill_id: str) -> str | None:
        with self.Session() as db:
            return db.scalar(
                select(RawBill.api_url)
                .where(
                    RawBill.id == bill_id,
                    RawBill.last_update.is_(True),
                    RawBill.api_url.is_not(None),
                )
                .limit(1)
            )

    def __search_api_url(self, bill_url: str) -> str:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            page = browser.new_page()

            try:
                page.goto(
                    "https://wb2server.congreso.gob.pe/spley-portal/",
                    wait_until="domcontentloaded",
                )

                with page.expect_response(
                    lambda r: (
                        "spley-portal-service/expediente/" in r.url
                        and r.request.method == "GET"
                        and r.status == 200
                    ),
                    timeout=10000,
                ) as response_info:
                    page.evaluate("url => { window.location.href = url; }", bill_url)

                return response_info.value.url

            except PlaywrightTimeoutError:
                return None

            finally:
                browser.close()

    # estudioComisiones (committees) is legitimately absent/empty for most
    # bills -- it only fills in once a committee formally studies the bill.
    # The committee-assignment history that actually matters downstream
    # (process_bill_steps -> BillStep.step_committees) comes from a
    # different, always-present field: seguimientos[].desComisiones. So a
    # missing estudioComisiones is expected, not a scrape problem -- log it
    # at debug, not warning.
    _OPTIONAL_SECTIONS = {"estudioComisiones"}

    def _apply_sections(self, raw_bill: RawBill, data: dict) -> RawBill:
        """Populate general/congresistas/committees/steps on an already
        id-stamped RawBill from a fetched detail payload. Shared by both
        create_raw_bill (legacy) and create_chamber_raw_bill (2026-2031)."""
        for raw_name, attribute_name in self.section_mapping.items():
            # Grab expected section, use English value to signal no section
            # (since sections can be empty lists themselves)
            attribute_value = data.get(raw_name, "Not Found")
            if attribute_value == "Not Found":
                log_fn = (
                    logger.debug
                    if raw_name in self._OPTIONAL_SECTIONS
                    else logger.warning
                )
                log_fn(
                    f"{raw_bill.id} - Missing Attribute: {raw_name} ({attribute_name})"
                )
            else:
                setattr(raw_bill, attribute_name, json.dumps(attribute_value))
        return raw_bill

    def __fetch_and_track_bill(
        self,
        bill_id: str,
        bill_url: str,
        create_fn: Callable[[dict, str], RawBill],
    ) -> None:
        """Resolve the API url, fetch+parse the detail JSON, build the
        RawBill via create_fn, and update tracking. Shared by scrape_bill
        (legacy) and scrape_chamber_bill (2026-2031) -- only id/url
        construction and which create_* method builds the row differ."""
        api_url = self.__get_existing_api_url(bill_id)

        if not api_url:
            api_url = self.__search_api_url(bill_url)

        if not api_url:
            logger.warning(f"No API URL found for Raw Bill {bill_id}")
            return

        response = get_url_text(api_url)

        if not response:
            logger.warning(f"No response found for Raw Bill {bill_id}")
            return

        try:
            resp = json.loads(response)
        except json.JSONDecodeError:
            logger.warning(f"Invalid JSON response for Raw Bill {bill_id}")
            return

        bill = create_fn(resp["data"], api_url)

        tracking_result = self.update_tracking(bill)

        if isinstance(tracking_result, list):
            self.raw_bills.extend(tracking_result)
        else:
            self.raw_bills.append(tracking_result)

        logger.success(f"Successfully scraped Raw Bill {bill_id}")

    # =====================================================================
    # LEGACY (through 2021-2026) -- bare-year id/url, discovered via the
    # unicameral SPA route
    # =====================================================================

    def scrape_bill(self, year: str, bill_number: str) -> None:
        """
        Scrape key sections: general, congresistas, committees, steps

        Returns tuple with result of scrape, error message if relevant
        """
        bill_id = f"{year}_{bill_number}"
        bill_url = f"{BASE_URL}/expediente/{year}/{bill_number}"
        self.__fetch_and_track_bill(
            bill_id,
            bill_url,
            lambda data, api_url: self.create_raw_bill(
                year, bill_number, data, api_url
            ),
        )

    def create_raw_bill(
        self, year: str, bill_number: str, data: dict, api_url: str
    ) -> RawBill:
        # Initialize raw bill with id and timestamp
        raw_bill = RawBill(
            id=f"{year}_{bill_number}", timestamp=datetime.now(), processed=False
        )
        self._apply_sections(raw_bill, data)
        raw_bill.api_url = api_url
        return raw_bill

    # =====================================================================
    # 2026-2031 BICAMERAL TERM -- chamber-prefixed id/url, confirmed live
    # 2026-09-01. Reuses the SAME Playwright navigate-and-intercept
    # mechanism as legacy (SHARED section above) unchanged -- only the
    # id/url construction differs.
    # =====================================================================

    def scrape_chamber_bill(self, chamber: str, bill_number: int) -> None:
        """Scrape one 2026-2031 bill for one chamber.

        Live-confirmed 2026-09-01 (post-implementation spot-check, both
        chambers): the detail route resolves via the real opaque
        expediente/{token1}/{token2}?codTipoParl={S|D} GET, and the
        resulting body carries general/firmantes/estudioComisiones/
        seguimientos matching legacy's section_mapping (re-verified live
        2026-09-03: the committee-study section is actually keyed
        "estudioComisiones", not "comisiones" -- that key doesn't exist on
        either term's payload and this scraper had been silently missing it
        for every bill, legacy and 2026-2031 alike, until fixed).
        """
        bill_id = f"{bill_number:05d}-{CHAMBER_LEG_PERIOD}-{CHAMBER_LABEL_TO_ID_SUFFIX[chamber]}"
        bill_url = (
            f"{BASE_URL}/{CHAMBER_LABEL_TO_ROUTE_SLUG[chamber]}/expediente/"
            f"{LEG_PERIOD_TO_PER_PAR_ID[CHAMBER_LEG_PERIOD]}/{bill_number}"
        )
        self.__fetch_and_track_bill(
            bill_id,
            bill_url,
            lambda data, api_url: self.create_chamber_raw_bill(bill_id, data, api_url),
        )

    def create_chamber_raw_bill(
        self, bill_id: str, data: dict, api_url: str
    ) -> RawBill:
        raw_bill = RawBill(id=bill_id, timestamp=datetime.now(), processed=False)
        self._apply_sections(raw_bill, data)
        raw_bill.api_url = api_url
        return raw_bill

    # =====================================================================
    # SHARED -- used by both the legacy and 2026-2031 code paths above
    # =====================================================================

    def update_tracking(self, bill: RawBill) -> list[RawBill]:
        """Update the tracking columns of a RawBill object"""

        def lookup(session):
            return (
                session.query(RawBill)
                .filter(RawBill.id == bill.id)
                .order_by(RawBill.timestamp.desc())
                .first()
            )

        return self._update_tracking(bill, lookup)

    def add_bills_to_db(self) -> bool:
        """
        Add the raw bills to the database.
        Returns True on success, False on failure.
        """
        return self._add_to_db(self.raw_bills, "Bills")

    def load_raw_bills(self):
        self.add_bills_to_db()
        self.raw_bills = []
