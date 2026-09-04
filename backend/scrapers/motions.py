import json
from collections.abc import Callable
from datetime import datetime
from loguru import logger

from backend.core.constants import (
    CHAMBER_LABEL_TO_COD_TIPO_PARL,
    CHAMBER_LABEL_TO_ID_SUFFIX,
    LEG_PERIOD_TO_PER_PAR_ID,
)
from backend.database.raw_models import RawMotion
from backend.scrapers.base import SharedRawScraperBase
from backend.scrapers.utils import get_url_text

BASE_URL = "https://api.congreso.gob.pe/smociones-portal-service"

# 2026-2031 term: motions' per-chamber detail endpoint uses a BARE YEAR
# (2026), confirmed live 2026-09-01 -- do NOT reuse bills.py's full
# period-string route convention here, they differ.
CHAMBER_LEG_PERIOD = "2026-2031"


class RawMotionScraper(SharedRawScraperBase):
    """
    Class to scrape and store raw bill information.

    Two independent scraping paths (see section headers below): LEGACY
    (through 2021-2026) builds motion_id/motion_url from a bare year and
    the hardcoded "C" chamber code via scrape_motion(). 2026-2031
    BICAMERAL TERM builds them from a chamber + the fixed period-start
    year via scrape_chamber_motion() -- confirmed live to use the SAME
    URL shape as legacy, just S/D instead of C. Both are thin wrappers
    that build id/url and delegate to the SAME __fetch_and_track_motion
    helper (below) for the actual fetch/parse/track sequence.
    """

    def __init__(self, session=None, engine=None):
        super().__init__(session=session, engine=engine)

        # Mapping raw section name to RawMotion attribute name
        self.section_mapping = {
            "firmantes": "congresistas",
            "seguimientos": "steps",
        }

        # List of raw bills objects
        self.raw_motions = []

    def _apply_sections(self, raw_motion: RawMotion, data: dict) -> RawMotion:
        """Pop congresistas/steps out of data, dump the remainder as
        general. Shared by both create_raw_motion (legacy) and
        create_chamber_raw_motion (2026-2031). Mutates ``data``."""
        for raw_name, attribute_name in self.section_mapping.items():
            # Grab expected section, use English value to signal no section
            # (since sections can be empty lists themselves)
            attribute_value = data.pop(raw_name, "Not Found")
            if attribute_value == "Not Found":
                logger.warning(
                    f"{raw_motion.id} - Missing Attribute: {raw_name} ({attribute_name})"
                )
            else:
                setattr(raw_motion, attribute_name, json.dumps(attribute_value))

        raw_motion.general = json.dumps(data)
        return raw_motion

    def __fetch_and_track_motion(
        self,
        motion_id: str,
        motion_url: str,
        create_fn: Callable[[dict], RawMotion],
    ) -> None:
        """Fetch+parse the detail JSON, build the RawMotion via create_fn,
        and update tracking. Shared by scrape_motion (legacy) and
        scrape_chamber_motion (2026-2031) -- only id/url construction and
        which create_* method builds the row differ."""
        response = get_url_text(motion_url)

        if response:
            resp = json.loads(response)
            new_motion = create_fn(resp["data"])
            self.raw_motions.extend(self.update_tracking(new_motion))
            logger.success(f"Successfully scraped Raw Motion {motion_id}")
        else:
            return None

    # =====================================================================
    # LEGACY (through 2021-2026) -- bare-year id/url, hardcoded "C" chamber
    # code
    # =====================================================================

    def scrape_motion(self, year: str, motion_number: str) -> None:
        """
        Scrape key sections: general, congresistas, steps

        Returns tuple with result of scrape, error message if relevant
        """
        motion_id = f"{year}_{motion_number}"
        motion_url = f"{BASE_URL}/mocion/C/{year}/{motion_number}"
        self.__fetch_and_track_motion(
            motion_id,
            motion_url,
            lambda data: self.create_raw_motion(year, motion_number, data),
        )

    def create_raw_motion(self, year: str, motion_number: str, data: dict) -> RawMotion:
        # Initialize raw bill with id and timestamp
        raw_motion = RawMotion(
            id=f"{year}_{motion_number}",
            timestamp=datetime.now(),
            processed=False,
            last_update=True,
        )
        return self._apply_sections(raw_motion, data)

    # =====================================================================
    # 2026-2031 BICAMERAL TERM -- chamber-prefixed id, bare-year url,
    # confirmed live 2026-09-01. Response body shape confirmed matching
    # legacy's firmantes/seguimientos keys.
    # =====================================================================

    def scrape_chamber_motion(self, chamber: str, motion_number: int) -> None:
        """Scrape one 2026-2031 motion for one chamber."""
        year = LEG_PERIOD_TO_PER_PAR_ID[CHAMBER_LEG_PERIOD]
        cod_tipo_parl = CHAMBER_LABEL_TO_COD_TIPO_PARL[chamber]
        motion_id = f"{motion_number:05d}-{CHAMBER_LEG_PERIOD}-{CHAMBER_LABEL_TO_ID_SUFFIX[chamber]}"
        motion_url = f"{BASE_URL}/mocion/{cod_tipo_parl}/{year}/{motion_number}"
        self.__fetch_and_track_motion(
            motion_id,
            motion_url,
            lambda data: self.create_chamber_raw_motion(motion_id, data),
        )

    def create_chamber_raw_motion(self, motion_id: str, data: dict) -> RawMotion:
        raw_motion = RawMotion(
            id=motion_id,
            timestamp=datetime.now(),
            processed=False,
            last_update=True,
        )
        return self._apply_sections(raw_motion, data)

    # =====================================================================
    # SHARED -- used by both the legacy and 2026-2031 code paths above
    # =====================================================================

    def update_tracking(self, motion: RawMotion) -> list[RawMotion]:
        """Update the tracking columns of a RawMotion object"""

        def lookup(session):
            return (
                session.query(RawMotion)
                .filter(RawMotion.id == motion.id)
                .order_by(RawMotion.timestamp.desc())
                .first()
            )

        return self._update_tracking(motion, lookup)

    def add_motions_to_db(self) -> bool:
        """
        Add the raw motions to the database.
        Returns True on success, False on failure.
        """
        return self._add_to_db(self.raw_motions, "Motions")

    def load_raw_motions(self):
        self.add_motions_to_db()
        self.raw_motions = []
