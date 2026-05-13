import os
from datetime import date
from loguru import logger
from pathlib import Path
from tqdm import tqdm

from pydantic import ConfigDict
from pydantic_settings import BaseSettings


# Directories
class Directories:
    """
    Directories used by the application.

    Attributes:
        ROOT_DIR (Path): The root directory of the project.
        DATA (Path): The directory containing data.
        RAW_DATA (Path): The directory containing raw data.
        PROCESSED_DATA (Path): The directory containing processed data.
        LOGS (Path): The directory containing logs.
    """

    ROOT_DIR = Path(__file__).resolve().parent.parent

    DATA = ROOT_DIR / "data"
    RAW_DATA = DATA / "raw"
    PROCESSED_DATA = DATA / "processed"

    DOCUMENTS = RAW_DATA / "documents"
    BILL_DOCUMENTS = DOCUMENTS / "bills"
    MOTION_DOCUMENTS = DOCUMENTS / "motions"

    LOGS = ROOT_DIR / "logs"
    LOGS_SCRAPERS = LOGS / "scrapers"
    LOGS_PROCESS = LOGS / "process"

    def __init__(self):
        for dir in [
            self.DATA,
            self.RAW_DATA,
            self.PROCESSED_DATA,
            self.DOCUMENTS,
            self.BILL_DOCUMENTS,
            self.MOTION_DOCUMENTS,
            self.LOGS,
            self.LOGS_SCRAPERS,
            self.LOGS_PROCESS,
        ]:
            dir.mkdir(exist_ok=True)

    @classmethod
    def scraper_log(cls, scraper_name: str, log_date: date | None = None) -> Path:
        log_date = log_date or date.today()

        scraper_log_dir = cls.LOGS_SCRAPERS / scraper_name
        scraper_log_dir.mkdir(parents=True, exist_ok=True)

        return scraper_log_dir / f"{log_date.isoformat()}.log"

    @classmethod
    def process_log(cls, process_name: str, log_date: date | None = None) -> Path:
        log_date = log_date or date.today()

        process_log_dir = cls.LOGS_PROCESS / process_name
        process_log_dir.mkdir(parents=True, exist_ok=True)

        return process_log_dir / f"{log_date.isoformat()}.log"


directories = Directories()


# Settings
class Settings(BaseSettings):
    """
    Settings for the application.

    The settings are loaded from the following sources in order of priority:

    1. Environment variables
    2. `.env` file in the root directory of the project
    3. Default values

    The settings are used to configure the application, such as setting up the database connection.
    """

    # This should change depending on where the DB will be stored
    DB_URL: str = os.getenv(
        "DB_URL",
        "postgresql+psycopg://opencongress:opencongress@db:5432/opencongress",
    )
    AWS_ACCESS_KEY_ID: str | None = os.getenv("AWS_ACCESS_KEY_ID")
    AWS_SECRET_ACCESS_KEY: str | None = os.getenv("AWS_SECRET_ACCESS_KEY")
    AWS_REGION: str | None = os.getenv("AWS_REGION")
    AWS_S3_BUCKET_NAME: str | None = os.getenv("AWS_S3_BUCKET_NAME")
    AWS_S3_PREFIX: str | None = os.getenv("AWS_S3_PREFIX")

    # This is only in case we need some API_KEYS. Allow us to handle safely.
    model_config = ConfigDict(
        env_file=directories.ROOT_DIR / ".env",
    )


settings = Settings()


class LogManager:
    """
    Manage project logging destinations.

    Supports:
    - logging to console with tqdm.write
    - logging to a custom file
    - logging to daily scraper files
    - logging to daily process files
    """

    LOG_FORMAT = "{time} | {level} | {file}:{function}:{line} | {message}"

    def __init__(self, directories):
        self.directories = directories

    def daily_log_file(
        self,
        base_log_dir: Path,
        name: str,
        log_date: date | None = None,
    ) -> Path:
        """
        Return a daily log file path.

        Example
        -------
        logs/scrapers/2026-05-13/bills.log
        logs/process/2026-05-13/bills.log
        """

        log_date = log_date or date.today()

        return base_log_dir / log_date.isoformat() / f"{name}.log"

    def to_file(
        self,
        filename: str | Path,
        mode: str = "a",
    ) -> None:
        """
        Redirect logs to a file and remove existing handlers.
        """

        filename = Path(filename)
        filename.parent.mkdir(parents=True, exist_ok=True)

        logger.remove()

        logger.add(
            filename,
            format=self.LOG_FORMAT,
            level="INFO",
            colorize=False,
            catch=True,
            mode=mode,
            encoding="utf-8",
        )

    def to_console(self) -> None:
        """
        Redirect logs to the console using tqdm.write.
        """

        logger.remove()

        logger.add(
            lambda msg: tqdm.write(msg, end=""),
            format=self.LOG_FORMAT,
            level="INFO",
            colorize=True,
            catch=True,
        )

    def to_scraper_file(
        self,
        scraper_name: str,
        log_date: date | None = None,
        mode: str = "a",
    ) -> None:
        """
        Redirect logs to a daily file for one scraper.

        Example
        -------
        logs/scrapers/2026-05-13/bills.log
        """

        filename = self.daily_log_file(
            base_log_dir=self.directories.LOGS_SCRAPERS,
            name=scraper_name,
            log_date=log_date,
        )

        self.to_file(filename=filename, mode=mode)

    def to_process_file(
        self,
        process_name: str,
        log_date: date | None = None,
        mode: str = "a",
    ) -> None:
        """
        Redirect logs to a daily file for one process.

        Example
        -------
        logs/process/2026-05-13/bills.log
        """

        filename = self.daily_log_file(
            base_log_dir=self.directories.LOGS_PROCESS,
            name=process_name,
            log_date=log_date,
        )

        self.to_file(filename=filename, mode=mode)


log_manager = LogManager(directories)
