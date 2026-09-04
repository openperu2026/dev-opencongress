from datetime import datetime, UTC
from loguru import logger

from backend.scrapers.base import SharedRawScraperBase
from backend.scrapers.utils import get_url_text
from backend.database.raw_models import RawLey

BASE_URL = "https://api.congreso.gob.pe/adlp-visor-service/expediente/ley?numley="


class RawLeyesScraper(SharedRawScraperBase):
    """
    Class to scrape and store raw ley information
    """

    def __init__(self, session=None, engine=None):
        super().__init__(session=session, engine=engine)

        # List of raw leyes objects
        self.raw_leyes = []

    def scrape_ley(self, ley_number: int) -> None:
        """
        Scrape data from ley api request
        """

        ley_url = f"{BASE_URL}{ley_number}"
        response = get_url_text(ley_url)

        if response:
            # Successfully built the raw ley!
            ley = self.create_raw_ley(ley_number, response)
            self.raw_leyes.extend(self.update_tracking(ley))
            logger.success(f"Successfully scraped Raw Ley {ley_number}")
        else:
            return None

    def create_raw_ley(self, ley_number: int, data: str) -> RawLey:
        # Initialize raw ley with id and timestamp
        raw_ley = RawLey(
            id=ley_number, timestamp=datetime.now(UTC), data=data, processed=False
        )

        return raw_ley

    def update_tracking(self, ley: RawLey) -> list[RawLey]:
        """Update the tracking columns of a RawLey object."""

        def lookup(session):
            return (
                session.query(RawLey)
                .filter(RawLey.id == ley.id)
                .order_by(RawLey.timestamp.desc())
                .first()
            )

        return self._update_tracking(ley, lookup)

    def add_leyes_to_db(self) -> bool:
        """
        Add the raw leyes to the database.
        Returns True on success, False on failure.
        """
        return self._add_to_db(self.raw_leyes, "Leyes")

    def load_raw_leyes(self):
        if self.add_leyes_to_db():
            self.raw_leyes = []
