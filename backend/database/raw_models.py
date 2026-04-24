from sqlalchemy import (
    Column,
    Integer,
    String,
    DateTime,
    Boolean,
    Index,
    PrimaryKeyConstraint,
)
from sqlalchemy.orm import declarative_base
from sqlalchemy.sql import expression
from sqlalchemy.inspection import inspect

Base = declarative_base()


class RawBase(Base):
    __abstract__ = True

    # Common columns for all the tables
    timestamp = Column(DateTime, nullable=False)
    last_update = Column(
        Boolean, nullable=False, server_default=expression.false(), default=False
    )
    changed = Column(
        Boolean, nullable=False, server_default=expression.false(), default=False
    )
    processed = Column(
        Boolean, nullable=False, server_default=expression.false(), default=False
    )

    # Columns to ignore in ALL raw models
    _ignore_eq = ["timestamp", "last_update", "changed", "processed"]

    def __eq__(self, other):
        """
        Compare two model instances for value-based equality.

        In this case, we are considering two objects equal when they are instances
        of the same class and all column values match, excluding any columns listed
        in `_ignore_eq`.

        This is useful when we want to determine whether two records represent
        the same underlying data and flag the changes accordingly in the raw ingestion.

        Args:
            other: Another object to compare against.

        Returns:
            bool: True if both objects are the same model type and all
            non-ignored column values are equal, otherwise False.
        """

        if not isinstance(other, self.__class__):
            return False

        mapper = inspect(self).mapper

        for col in mapper.columns:
            name = col.key
            if name in self._ignore_eq:
                continue
            if getattr(self, name) != getattr(other, name):
                return False

        return True

    __hash__ = None


class RawBancada(RawBase):
    """
    Represents a raw scraped of all bancadas in the peruvian parliament with its
    congressmembers that belongs to them.

    Attributes:
        id (str): Unique identifier for the bancada.
        leg_period (str): Legislative period
        raw_html (str): Html text
        timestamp (datetime): timestamp of the scraping task
        last_update (bool): Column that indicates if this tuple is the last update for the bill_id
        changed (bool): Column that indicates if the last update has any difference from the previous update
        processed (bool): Column that indicates if the last update with changes have been updated
    """

    __tablename__ = "raw_bancadas"

    id = Column(Integer, primary_key=True, autoincrement=True)
    legislative_period = Column(String, nullable=False)
    raw_html = Column(String, nullable=False)


class RawBill(RawBase):
    """
    Represents a raw scraped bill in the peruvian parliament.

    Attributes:
        id (str): Unique identifier for the bill.
        general (str): Main bill info
        committees (str) Information about committees
        congresistas (str) Information about authors and proponents
        steps (str) Information about bill steps
        timestamp (datetime): timestamp of the scraping task
        last_update (bool): Column that indicates if this tuple is the last update for the bill_id
        changed (bool): Column that indicates if the last update has any difference from the previous update
        processed (bool): Column that indicates if the last update with changes have been updated
    """

    __tablename__ = "raw_bills"

    id = Column(String, nullable=False)
    general = Column(String, nullable=True)
    committees = Column(String, nullable=True)
    congresistas = Column(String, nullable=True)
    steps = Column(String, nullable=True)

    __table_args__ = (
        PrimaryKeyConstraint("id", "timestamp", name="pk_raw_bills"),
        Index(
            "ix_raw_bills_pipeline",
            "id",
            "last_update",
            "changed",
            "processed",
        ),
    )


class RawBillDocument(RawBase):
    """
    Raw documents url and text content extracted by scrape_raw_bills_documents.py

    Attributes:
        bill_id (str): Unique identifier for the bill.
        step_id (str): Event to which the document is related to.
        file_id (str): id related to the document
        step_date (datetime): date of the event related to the document
        url (str): complete document's url (congress website).
        s3_key (str): s3_key that maps the location of the document on the AWS S3 Bucket
        local_path (str): local path where the document is located.
        timestamp (datetime): timestamp of the scraping task
        last_update (bool): Column that indicates if this tuple is the last update for the bill_id
        changed (bool): Column that indicates if the last update has any difference from the previous update
        processed (bool): Column that indicates if the last update with changes have been updated
    """

    __tablename__ = "raw_bill_documents"

    __table_args__ = (
        Index(
            "ix_raw_bills_documents_pipeline",
            "bill_id",
            "step_id",
            "file_id",
            "last_update",
            "changed",
            "processed",
        ),
    )

    bill_id = Column(String, primary_key=True)
    step_id = Column(String, primary_key=True)
    file_id = Column(String, primary_key=True)
    step_date = Column(DateTime, nullable=False)
    url = Column(String, nullable=False)
    s3_key = Column(String, nullable=True)
    local_path = Column(String, nullable=True)


class RawBillPage(RawBase):
    __tablename__ = "raw_bill_pages"

    bill_id = Column(String, primary_key=True)
    step_id = Column(String, primary_key=True)
    file_id = Column(String, primary_key=True)
    page_num = Column(Integer, primary_key=True)
    text = Column(String, nullable=False)
    model = Column(String, nullable=False)

    __table_args__ = (
        Index(
            "ix_raw_bills_pages_pipeline",
            "bill_id",
            "step_id",
            "file_id",
            "page_num",
            "last_update",
            "changed",
            "processed",
        ),
    )


class RawCommittee(RawBase):
    """
    Represents a raw scraped committee in the peruvian parliament.

    Attributes:
        id (str): Unique identifier for raw committee.
        legislative_year (int): Legislative year
        committee_type (str): Type of committee in the parliament
        raw_html (str): Html text
        timestamp (datetime): timestamp of the scraping task
        last_update (bool): Column that indicates if this tuple is the last update for the bill_id
        changed (bool): Column that indicates if the last update has any difference from the previous update
        processed (bool): Column that indicates if the last update with changes have been updated
    """

    __tablename__ = "raw_committees"

    id = Column(Integer, primary_key=True, autoincrement=True)
    legislative_year = Column(Integer, nullable=False)
    committee_type = Column(String, nullable=False)
    raw_html = Column(String, nullable=False)


class RawCongresista(RawBase):
    """
    Represents a raw scraped information of congresistas

    Attributes:
        id (str): Unique identifier for raw congresista.
        leg_period (str): Legislative period related to the congresista
        website (str): Congresista's website url
        profile_content (str): Html text from the website's profile tab
        memberships_content (str): API response to memberships of the congresista in json format
        timestamp: Time stamp of the scrape process
        last_update (bool): Column that indicates if this tuple is the last update for the bill_id
        changed (bool): Column that indicates if the last update has any difference from the previous update
        processed (bool): Column that indicates if the last update with changes have been updated
    """

    __tablename__ = "raw_congresistas"

    id = Column(Integer, primary_key=True, nullable=False, autoincrement=True)
    leg_period = Column(String, nullable=False)
    website = Column(String, nullable=False)
    profile_content = Column(String, nullable=False)
    memberships_content = Column(String, nullable=True)

    __table_args__ = (
        Index(
            "ix_raw_congresistas_pipeline",
            "id",
            "last_update",
            "changed",
            "processed",
        ),
    )


class RawLey(RawBase):
    """
    Represents a raw law extracted from the Peruvian congress web page.

    Attributes:
        id (str): Unique identifier for the organization.
        data (str): raw data xml information related to the law
        timestamp (datetime): timestamp of the scraping task
        last_update (bool): Column that indicates if this tuple is the last update for the bill_id
        changed (bool): Column that indicates if the last update has any difference from the previous update
        processed (bool): Column that indicates if the last update with changes have been updated
    """

    __tablename__ = "raw_leyes"

    id = Column(Integer, primary_key=True, autoincrement=True)
    data = Column(String, nullable=False)


class RawMotion(RawBase):
    """
    Represents a raw scraped motion in the peruvian parliament.

    Attributes:
        id (str): Unique identifier for the motion.
        general (str): Main motion info
        congresistas (str) Information about authors and proponents
        steps (str) Information about motion steps
        timestamp (datetime): timestamp of the scraping task
        last_update (bool): Column that indicates if this tuple is the last update for the bill_id
        changed (bool): Column that indicates if the last update has any difference from the previous update
        processed (bool): Column that indicates if the last update with changes have been updated
    """

    __tablename__ = "raw_motions"

    id = Column(String, nullable=False)
    general = Column(String, nullable=True)
    congresistas = Column(String, nullable=True)
    steps = Column(String, nullable=True)

    __table_args__ = (
        PrimaryKeyConstraint("id", "timestamp", name="pk_raw_motions"),
        Index(
            "ix_raw_motions_pipeline",
            "id",
            "last_update",
            "changed",
            "processed",
        ),
    )


class RawMotionDocument(RawBase):
    """
    Raw documents url and text content extracted by scrape_raw_motions_documents.py

    Attributes:
        motion_id (str): Unique identifier for the motion.
        step_id (str): Event to which the document is related to.
        file_id (str): id related to the document
        step_date (datetime): date of the event related to the document
        url (str): complete document's url.
        s3_key (str): s3_key that maps the location of the document on the AWS S3 Bucket
        local_path (str): local path where the document is located.
        timestamp (datetime): timestamp of the scraping task
        last_update (bool): Column that indicates if this tuple is the last update for the bill_id
        changed (bool): Column that indicates if the last update has any difference from the previous update
        processed (bool): Column that indicates if the last update with changes have been updated
    """

    __tablename__ = "raw_motion_documents"

    motion_id = Column(String, primary_key=True)
    step_id = Column(String, primary_key=True)
    file_id = Column(String, primary_key=True)
    step_date = Column(DateTime, nullable=False)
    url = Column(String, nullable=False)
    s3_key = Column(String, nullable=True)
    local_path = Column(String, nullable=True)

    __table_args__ = (
        Index(
            "ix_raw_motion_documents_pipeline",
            "motion_id",
            "step_id",
            "file_id",
            "last_update",
            "changed",
            "processed",
        ),
    )


class RawMotionPage(RawBase):
    __tablename__ = "raw_motion_pages"

    motion_id = Column(String, primary_key=True)
    step_id = Column(String, primary_key=True)
    file_id = Column(String, primary_key=True)
    page_num = Column(Integer, primary_key=True)
    text = Column(String, nullable=False)
    model = Column(String, nullable=False)

    __table_args__ = (
        Index(
            "ix_raw_motions_pages_pipeline",
            "motion_id",
            "step_id",
            "file_id",
            "page_num",
            "last_update",
            "changed",
            "processed",
        ),
    )


class RawOrganization(RawBase):
    """
    Represents a raw scraped organization in the peruvian parliament such as
    Junta de Portavoces, Consejo Directivo, Mesa Directiva y Comisión Permanente.

    Attributes:
        id (str): Unique identifier for the organization.
        legislative_year (str): Legislative year
        org_link (str): Organization's website
        raw_html (str): Html text
        timestamp (datetime): timestamp of the scraping task
        last_update (bool): Column that indicates if this tuple is the last update for the bill_id
        changed (bool): Column that indicates if the last update has any difference from the previous update
        processed (bool): Column that indicates if the last update with changes have been updated
    """

    __tablename__ = "raw_organizations"

    id = Column(Integer, primary_key=True, autoincrement=True)
    legislative_year = Column(Integer, nullable=False)
    type_org = Column(String, nullable=False)
    org_link = Column(String, nullable=False)
    raw_html = Column(String, nullable=False)


class ScraperRun(Base):
    """
    Stores the metadata on the scrapers jobs for future analysis and future pipeline automations.

    Attributes:
        run_id (int): Unique identifier of the scraper run
        scraper_name (str): Name of the scraper file that ran
        start_time (datetime): Time when the scraper started running
        end_time (datetime): Time when the scraper stop running
        scraped_rows (int): Number of rows scraped within the run
    """

    __tablename__ = "scraper_runs"

    run_id = Column(Integer, primary_key=True, autoincrement=True)
    scraper_name = Column(String, nullable=False)
    start_time = Column(DateTime, nullable=False)
    end_time = Column(DateTime, nullable=False)
    scraped_rows = Column(Integer, nullable=False)
