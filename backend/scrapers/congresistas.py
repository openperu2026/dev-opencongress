import html as html_lib
import json
import re
from loguru import logger
from datetime import datetime

from lxml.html import HtmlElement
from urllib.parse import urljoin

from sqlalchemy.orm import sessionmaker
from sqlalchemy import create_engine
from sqlalchemy.exc import SQLAlchemyError

from backend.config import settings
from backend.core.constants import CHAMBER_BASE_URLS, CHAMBER_LEG_PERIOD_LABEL
from backend.database.raw_models import RawCongresista
from backend.scrapers.utils import (
    parse_url,
    get_url_text,
    normalize_text,
    get_cong_website,
)

BASE_URL = "https://www3.congreso.gob.pe/pagina/congresistas"
API_MEMBERSHIP = "https://wb2server.congreso.gob.pe/vll/cargos/api/"
DB_PATH = settings.DB_URL

# 2026-2031 term: separate listing slug per chamber, confirmed live 2026-08-31
# (senado.../senador/, diputados.../diputado/).
CHAMBER_LISTING_SLUG = {"Senadores": "senador", "Diputados": "diputado"}


class RawCongresistasScraper:
    """
    Class to scrape congresistas raw data from the congress web page.

    Two independent scraping paths live in this class (see the section
    headers below): LEGACY covers every period through 2021-2026 via the
    unicameral www3.congreso.gob.pe dropdown site; 2026-2031 BICAMERAL TERM
    covers the current term via the new per-chamber senado/diputados
    microsites. Both write RawCongresista rows to the same table
    (distinguished by the `chamber` column: NULL for legacy, "Senadores"/
    "Diputados" for the new term) and both are consumed unmodified by
    process_profile_content() (backend/process/congresistas.py) -- see the
    SHARED section at the bottom for the methods common to both paths.
    """

    def __init__(self):
        # Engine and session maker for DB
        self.engine = create_engine(DB_PATH)
        self.url = BASE_URL
        self.Session = sessionmaker(bind=self.engine)

        self.periods = {}
        self.raw_congresistas: list[RawCongresista] = []

    # =====================================================================
    # LEGACY (through 2021-2026) -- www3.congreso.gob.pe, dropdown-driven
    # =====================================================================

    def get_dict_periodos(self):
        parse = parse_url(self.url)
        periodos = parse.xpath('//*[@name="idRegistroPadre"]/option')
        self.periods = {elem.text: elem.get("value") for elem in periodos}

    def extract_table(self, period) -> HtmlElement:
        parse = parse_url(self.url, {"idRegistroPadre": period})
        table = parse.xpath('//*[@class="congresistas"]')
        return table[0]

    def get_urls_from_table(self, period) -> list[str]:
        html = self.extract_table(period)
        cong_links = html.xpath(
            '//*[@class="congresistas"]//tr//td//*[@class="conginfo"]/@href'
        )
        return cong_links

    def get_profile_content(self, cong_link: str) -> str:
        full_url = self.url + cong_link
        return get_url_text(full_url)

    def _is_cargos_label(self, txt: str) -> bool:
        """
        Helper function to assert if the labels inside the webpage is related to cargos.
        We care about labels like: 'Cargos', 'Cargos del congresista', 'Cargos de la congresista', etc.
        """
        if "cargo" not in txt:
            return False
        # soft preference for congresista/parlamentario but we don't force it
        return True

    def _score_link_text(self, txt: str) -> int:
        """
        Higher score means that is more like what we want from the cargos url.
        """
        score = 0
        if "cargo" in txt:
            score += 2
        if "congres" in txt or "parlament" in txt:
            score += 2
        if "cargos del" in txt or "cargos de la" in txt:
            score += 1
        return score

    def get_best_cargos_link(self, doc: HtmlElement, base_url: str) -> str | None:
        """
        Method
        """
        # collect all <a> and <button> (just in case)
        candidates = doc.xpath("//a | //button")

        best_href = None
        best_score = -1

        for node in candidates:
            raw_text = node.text_content()
            txt = normalize_text(raw_text)

            if not self._is_cargos_label(txt):
                continue

            # try common URL carriers
            href = node.get("href") or node.get("data-href") or node.get("onclick")
            if not href:
                continue

            s = self._score_link_text(txt)
            if s > best_score:
                best_score = s
                best_href = href

        if best_href:
            return urljoin(base_url, best_href)

        # fallback: None found
        return None

    def create_raw_congresista(
        self, period: str, cong_link: str
    ) -> RawCongresista | None:
        profile_content = self.get_profile_content(cong_link)
        website = get_cong_website(profile_content)

        if period in [
            "Parlamentario 2001 - 2006",
            "Parlamentario 2000 - 2001",
            "Parlamentario 1995 - 2000",
            "CCD 1992 -1995",
        ]:
            return RawCongresista(
                timestamp=datetime.now(),
                leg_period=period,
                website=website,
                profile_content=profile_content,
                memberships_content=None,
            )
        else:
            html_cong = parse_url(website)
            cargos_url = self.get_best_cargos_link(html_cong, website)
            if not cargos_url:
                return RawCongresista(
                    timestamp=datetime.now(),
                    leg_period=period,
                    website=website,
                    profile_content=profile_content,
                    memberships_content=None,
                )
        try:
            cargos = parse_url(cargos_url)

            iframe = cargos.xpath('//*[@id="objContents"]/div[2]/p/iframe')
            if not iframe:
                raise IndexError("No iframe found in cargos page")
            api_call = iframe[0].get("src")
            match = re.search(r"(listar/)(.*)", api_call)
            if not match:
                raise ValueError(f"Invalid iframe src pattern: {api_call}")
            api_id = match.group(2)
        except (IndexError, ValueError, AttributeError, TypeError) as e:
            logger.warning(f"Failed to extract API ID for {cong_link}: {e}")
            logger.warning(f"Congresista partially extracted from {website}")
            return RawCongresista(
                timestamp=datetime.now(),
                leg_period=period,
                website=website,
                profile_content=profile_content,
                memberships_content=None,
            )

        memberships_content = get_url_text(API_MEMBERSHIP + api_id)

        raw_congresista = RawCongresista(
            timestamp=datetime.now(),
            leg_period=period,
            website=website,
            profile_content=profile_content,
            memberships_content=memberships_content,
        )
        logger.success(f"Congresista successfully extracted from {website}")
        return raw_congresista

    # =====================================================================
    # 2026-2031 BICAMERAL TERM -- senado/diputados.congreso.gob.pe,
    # confirmed live 2026-08-31 (Phase B plan, Step B0). No dropdown/period
    # selector on these sites at all -- each domain serves only the current
    # term's roster.
    # =====================================================================

    def get_chamber_roster(self, chamber: str) -> list[dict]:
        """Fetch the 2026-2031 congresista roster for one chamber.

        Confirmed live 2026-08-31: the listing page at
        {senado|diputados}.congreso.gob.pe/{senador|diputado}/ embeds its full
        roster (60 Senado / 130 Diputados) as a single
        <script type="application/json"> inside a [data-congresista-app]
        container -- pagination is client-side only (no query-string/XHR
        fallback), so this one GET returns everyone. No Playwright needed.
        Each entry: {name, partido, group, district, gender, condition,
        period, email, photo, url}. `group` is the bancada/grupo
        parlamentario, already resolved -- reused by get_chamber_bancadas().
        """
        base_url = CHAMBER_BASE_URLS[chamber]
        slug = CHAMBER_LISTING_SLUG[chamber]
        listing_url = f"{base_url}/{slug}/"
        listing_html = parse_url(listing_url)
        if listing_html is None:
            logger.warning(f"Failed to fetch chamber roster page: {listing_url}")
            return []

        scripts = listing_html.xpath(
            '//*[@data-congresista-app]//script[@type="application/json"]/text()'
        )
        if not scripts:
            logger.warning(f"No embedded roster JSON found at {listing_url}")
            return []

        try:
            roster = json.loads(scripts[0])
        except (ValueError, TypeError) as e:
            logger.warning(f"Failed to parse roster JSON at {listing_url}: {e}")
            return []

        return roster if isinstance(roster, list) else []

    def _get_chamber_votes(self, profile_url: str) -> str:
        """Fetch "Votación obtenida" from a 2026-2031 profile page.

        Confirmed live 2026-08-31: value found via a `*summary__label`/
        `*summary__value` pair -- prefix (senador-/diputado-) varies by
        chamber, so matched by class suffix rather than the full name.
        """
        html = parse_url(profile_url)
        if html is None:
            return "0"
        labels = html.xpath(
            '//*[contains(@class, "summary__label") '
            'and normalize-space(text())="Votación obtenida"]'
        )
        if not labels:
            return "0"
        value_node = labels[0].getnext()
        if value_node is None:
            return "0"
        return value_node.text_content().strip() or "0"

    @staticmethod
    def _parse_cargos_date(value: str | None) -> str | None:
        """Convert the cargos-table's dd/mm/yyyy date text to an ISO date
        string, matching what to_datetime() (backend/process/utils.py)
        already expects. Kept scoped to this one new page's date format
        rather than widening to_datetime() itself, which parses ISO/epoch
        values used broadly elsewhere.
        """
        if not value:
            return None
        try:
            return datetime.strptime(value.strip(), "%d/%m/%Y").date().isoformat()
        except ValueError:
            return None

    def _get_chamber_cargos(self, profile_url: str) -> str | None:
        """Fetch and parse a 2026-2031 congresista's own cargos sub-page.

        Confirmed live 2026-09-02 (both chambers, same URL pattern):
        {profile_url}sobre-el-integrante/cargos/ holds a table.cargos-table
        with one row per membership (committee, admin org, or bancada),
        each row's org name in a <small title="..."> and its dates as
        plain dd/mm/yyyy text. This is now the SOLE source of 2026-2031
        membership data for admin orgs AND committees -- see
        organizations.py::_build_admin_org_html's docstring for the other
        half of this decision (org-page scrapes build Organization records
        only, never Membership rows, for this term).

        Synthesizes the same {"data": [...]} JSON shape the legacy cargos
        API already produces, so process_cong_memberships() (backend/
        process/congresistas.py) needs zero changes -- dates are converted
        to ISO here since that function's to_datetime() only parses
        ISO/epoch.
        """
        cargos_url = urljoin(profile_url, "sobre-el-integrante/cargos/")
        html_doc = parse_url(cargos_url)
        if html_doc is None:
            logger.warning(f"Failed to fetch cargos page: {cargos_url}")
            return None

        rows = html_doc.xpath(
            '//table[contains(@class, "cargos-table")]//tr[@data-cargos-row]'
        )
        memberships = []
        for row in rows:
            small_nodes = row.xpath(".//small")
            org_name = small_nodes[0].text_content().strip() if small_nodes else ""
            if not org_name:
                logger.warning(f"Skipping cargos row with no org name at {cargos_url}")
                continue

            strong_nodes = row.xpath(".//strong")
            strong_text = strong_nodes[0].text_content().strip() if strong_nodes else ""
            if strong_text.lower() == "grupo parlamentario":
                # Bancada membership -- already scraped via the dedicated
                # RawBancadaScraper.get_chamber_bancadas path (Phase B1);
                # routing it through here too would double-source the same
                # fact, and map_org_fields() has no Bancada case at all
                # (it would silently default to org_type="Comisión").
                continue

            cargo_nodes = row.xpath(
                './/td[@data-label="Cargo"]//span[contains(@class, "cargos-badge--role")]'
            )
            cargo_text = cargo_nodes[0].text_content().strip() if cargo_nodes else ""

            desde_nodes = row.xpath('.//td[@data-label="Desde"]')
            hasta_nodes = row.xpath('.//td[@data-label="Hasta"]')
            fecha_inicio = self._parse_cargos_date(
                desde_nodes[0].text_content() if desde_nodes else None
            )
            fecha_fin = self._parse_cargos_date(
                hasta_nodes[0].text_content() if hasta_nodes else None
            )
            if fecha_inicio is None:
                logger.warning(
                    f"Skipping cargos row for {org_name!r} with unparseable "
                    f"Desde date at {cargos_url}"
                )
                continue

            memberships.append(
                {
                    "desOrgano": org_name,
                    "desOrganoCongresista": org_name,
                    "desCargo": cargo_text,
                    "fechaInicio": fecha_inicio,
                    "fechaFin": fecha_fin,
                }
            )

        if not memberships:
            return None
        return json.dumps({"data": memberships})

    @staticmethod
    def _synthesize_chamber_profile_html(entry: dict, votes: str) -> str:
        """Build a minimal HTML doc using the SAME class names
        process_profile_content() (backend/process/congresistas.py) already
        parses for legacy congresistas -- keeps that function's contract
        (.nombres/.grupo/.foto/.votacion/.representa/.condicion) stable
        regardless of which site the data came from, so it needs zero
        changes for the 2026-2031 path.
        """
        name = html_lib.escape(entry.get("name") or "")
        group = html_lib.escape(entry.get("group") or entry.get("partido") or "")
        district = html_lib.escape(entry.get("district") or "")
        condition = html_lib.escape(entry.get("condition") or "")
        photo = html_lib.escape(entry.get("photo") or "")
        votes_escaped = html_lib.escape(votes)
        return (
            "<html><body>"
            f'<div class="nombres"><span>Label</span><span>{name}</span></div>'
            f'<div class="grupo"><span>Label</span><span>{group}</span></div>'
            f'<div class="votacion"><span>Label</span><span>{votes_escaped}</span></div>'
            f'<div class="representa"><span>Label</span><span>{district}</span></div>'
            f'<div class="condicion"><span>Label</span><span>{condition}</span></div>'
            f'<div class="foto"><img src="{photo}"/></div>'
            "</body></html>"
        )

    def create_chamber_congresista(self, chamber: str, entry: dict) -> RawCongresista:
        profile_url = entry.get("url", "")
        votes = self._get_chamber_votes(profile_url) if profile_url else "0"
        profile_content = self._synthesize_chamber_profile_html(entry, votes)
        memberships_content = (
            self._get_chamber_cargos(profile_url) if profile_url else None
        )

        return RawCongresista(
            timestamp=datetime.now(),
            leg_period=CHAMBER_LEG_PERIOD_LABEL,
            chamber=chamber,
            website=profile_url,
            profile_content=profile_content,
            memberships_content=memberships_content,
        )

    def extract_chamber_congresistas(
        self, chamber: str, roster: list[dict]
    ) -> list[RawCongresista]:
        """Build+track RawCongresista rows for one chamber from an
        already-fetched roster (see get_chamber_roster)."""

        congresistas = []
        for entry in roster:
            congresistas.append(
                self.update_tracking(self.create_chamber_congresista(chamber, entry))
            )
            logger.success(
                f"Congresista successfully extracted from {entry.get('url')}"
            )

        self.raw_congresistas = congresistas
        return congresistas

    # =====================================================================
    # LEGACY (through 2021-2026), continued
    # =====================================================================

    def extract_cong_from_period(
        self, period_key: str, period_value: str
    ) -> list[RawCongresista]:
        congresistas = []

        links = self.get_urls_from_table(period_value)
        for cong_link in links:
            new_cong = self.create_raw_congresista(period_key, cong_link)
            congresistas.append(self.update_tracking(new_cong))

        return congresistas

    # =====================================================================
    # SHARED -- used by both the legacy and 2026-2031 code paths above
    # =====================================================================

    def update_tracking(self, congresista: RawCongresista) -> RawCongresista:
        """Update the tracking columns of a RawCongresista object.

        Period-agnostic: dedupes on `website` alone, which is already
        unique per person regardless of chamber/period, so no chamber
        filter is needed here (unlike RawBancada/RawCommittee/
        RawOrganization's trackers, which do need one -- see those files).
        """

        with self.Session() as session:
            last_congresista = (
                session.query(RawCongresista)
                .filter(RawCongresista.website == congresista.website)
                .order_by(RawCongresista.timestamp.desc())
                .first()
            )

            # First ever version of this congresista
            if last_congresista is None:
                congresista.changed = True
                congresista.last_update = True
                congresista.processed = False
            else:
                # Compare last vs new
                congresista.changed = congresista != last_congresista
                congresista.last_update = True
                congresista.processed = not congresista.changed

                # Update the old version AFTER comparison
                last_congresista.last_update = False
                session.add(last_congresista)
                session.commit()

            return congresista

    # =====================================================================
    # LEGACY (through 2021-2026), continued
    # =====================================================================

    def extract_and_load_all(self, only_current: bool = False) -> list[RawCongresista]:
        assert self.periods, (
            "You need to extract all the available periods before extracting the tables"
        )

        periods = self.periods
        if only_current:
            first = next(iter(self.periods.items()), None)
            periods = dict([first]) if first else {}

        for period, value in periods.items():
            self.raw_congresistas = self.extract_cong_from_period(period, value)
            self.add_congresistas_to_db()

        return self.raw_congresistas

    # =====================================================================
    # SHARED -- used by both the legacy and 2026-2031 code paths above
    # =====================================================================

    def add_congresistas_to_db(self) -> bool:
        """
        Add the raw congresistas to the database.
        Returns True on success, False on failure

        Period-agnostic: bulk-saves whatever is currently in
        self.raw_congresistas, set by either extract_cong_from_period()
        (legacy) or extract_chamber_congresistas() (2026-2031).
        """

        assert self.raw_congresistas, (
            "Congresistas must be scraped before it can be saved"
        )

        session = self.Session()

        try:
            session.bulk_save_objects(self.raw_congresistas)
            session.commit()
            logger.success(
                f"Added {len(self.raw_congresistas)} congresistas to Raw Congresistas table"
            )
            return True
        except SQLAlchemyError as e:
            logger.error(f"Failed to add committees: {str(e)}")
            session.rollback()
            return False
        finally:
            # Close Session
            session.close()


if __name__ == "__main__":
    scraper = RawCongresistasScraper()
    scraper.get_dict_periodos()
    scraper.extract_and_load_all()
