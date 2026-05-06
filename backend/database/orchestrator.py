from __future__ import annotations

import time
from datetime import date, datetime, timedelta
from typing import Type, Callable

from loguru import logger
from sqlalchemy import create_engine, func
from sqlalchemy.orm import sessionmaker

from backend.config import (
    settings,
    directories,
    stop_logging_to_console,
    resume_logging_to_console,
)
from backend.database import models as db_models
from backend.database.models import Bill, Motion, Ley
from backend.database.crud import (
    pipeline_bills as crud_bills,
    pipeline_core as crud_core,
    pipeline_motions as crud_motions,
)
from backend.database.crud.pipeline_core import (
    ProcessStats,
    ScraperStats,
    upsert_scraper_run,
)
from backend.database.raw_models import (
    RawBase,
    RawBancada,
    RawBill,
    RawCommittee,
    RawCongresista,
    RawLey,
    RawMotion,
    RawOrganization,
)
from backend.process.bancadas import process_bancada
from backend.process.bills import (
    process_bill,
    process_bill_organizations,
    process_bill_text,
    find_organization_schema,
)
from backend.process.congresistas import (
    process_cong_memberships,
    process_profile_content,
    get_cong_data,
)
from backend.process.motions import (
    find_motion_organization_schema,
    process_motion,
    process_motion_organizations,
    process_motion_text,
)
from backend.process.organizations import (
    process_chambers,
    process_committee,
    process_admin_org,
)
from backend.process.leyes import process_leyes
from backend.process.schema import Membership, Organization
from backend.process.utils import get_current_leg_year
from backend.scrapers.bancadas import RawBancadaScraper
from backend.scrapers.bills import RawBillScraper
from backend.scrapers.bills_documents import RawBillDocumentScraper
from backend.scrapers.committees import RawCommitteeScraper
from backend.scrapers.congresistas import RawCongresistasScraper
from backend.scrapers.leyes import RawLeyesScraper
from backend.scrapers.motions import RawMotionScraper
from backend.scrapers.motions_documents import RawMotionDocumentScraper
from backend.scrapers.organizations import RawOrganizationScraper


class OpenPeruOrchestrator:
    """
    End-to-end ETL orchestrator:
      1) scrape raw tables
      2) process raw rows into Pydantic DTOs
      3) load SQLAlchemy models into the clean DB
    """

    def __init__(self, db_url: str = settings.DB_URL):
        self.db_engine = create_engine(db_url, pool_pre_ping=True)
        self.DBSession = sessionmaker(
            bind=self.db_engine, autocommit=False, autoflush=False
        )

        # Ensure schemas exist before the pipeline runs.
        db_models.Base.metadata.create_all(self.db_engine)

    # -----------------------------
    # Public API
    # -----------------------------
    def _recent_raw_exists(self, raw_model: RawBase, days: int = 7) -> bool:
        """
        Query to check recent changes in a period of time in any RawDB table (default 7 days / 1 week)
        """
        cutoff = datetime.now() - timedelta(days=days)
        with self.DBSession() as raw_db:
            last_ts = raw_db.query(func.max(raw_model.timestamp)).scalar()
            return bool(last_ts and last_ts >= cutoff)

    def _get_approved_ids(self, model: Bill | Motion) -> list[str]:
        with self.DBSession() as db:
            approved_col = (
                model.bill_approved if model is Bill else model.motion_approved
            )
            ids = [
                row[0]
                for row in db.query(model.id).filter(approved_col.is_(True)).all()
            ]
        return ids

    def _get_ids_to_update(
        self,
        raw_model: Type[RawBill] | Type[RawMotion] | Type[RawLey],
        model: Type[Bill] | Type[Motion] | Type[Ley],
        days: int = 7,
    ) -> list[str] | None:
        """
        Return ids that should be refreshed this week:
          - latest snapshot is older than `max_age_days`
          - latest snapshot is not approved
        """
        cutoff = datetime.now() - timedelta(days=days)

        with self.DBSession() as raw_db:
            latest_rows = raw_db.query(raw_model).filter(raw_model.last_update).all()
            pending_ids: list[str] = []

            for row in latest_rows:
                if row.timestamp > cutoff:
                    continue
                if row.id in self._get_approved_ids(model):
                    continue
                pending_ids.append(row.id)

            return pending_ids

    def _load_scraper_results(self, scraper_name: str) -> None:
        stats = self.scraper_results[scraper_name]
        with self.DBSession() as db:
            upsert_scraper_run(db, scraper_name, stats)
        logger.info(
            f"Results for scraper/{scraper_name}: Time: {(stats.end_time - stats.start_time).seconds}s | Rows scraped: {stats.scrapped}"
        )

    def run_scrapers(
        self,
        *,
        scrape_bills: bool = True,
        scrape_motions: bool = True,
        scrape_leyes: bool = True,
        scrape_others: bool = True,
        only_current: bool = True,
        weekly_days: int = 7,
        others_days: int = 7,
        bill_year: int | None = None,
        bill_start: int | None = None,
        bill_end: int | None = None,
        ley_start: int | None = None,
        ley_end: int | None = None,
        motion_year: int | None = None,
        motion_start: int | None = None,
        motion_end: int | None = None,
        scrape_documents: bool = False,
    ) -> None:
        """
        Run raw scrapers. Bills/motions scraping requires explicit ranges.
        """
        logger.info("Starting processing pipeline")
        self.scraper_results: dict[str, ScraperStats] = dict()

        if scrape_others:
            logger.info(
                "Running reference scrapers (congresistas, bancadas, committees, organizations)"
            )

            stop_logging_to_console(
                filename=directories.LOGS_SCRAPERS / "congresistas.log"
            )
            if self._recent_raw_exists(RawCongresista, days=others_days):
                logger.info(
                    f"Skipping congresistas scrape: latest raw scrape is within {others_days} days"
                )
            else:
                cong = RawCongresistasScraper()
                start_time = datetime.now()
                cong.get_dict_periodos()
                scraped_congs = cong.extract_and_load_all(only_current=only_current)
                end_time = datetime.now()
                self.scraper_results["congresistas.py"] = ScraperStats(
                    start_time, end_time, len(scraped_congs)
                )

                resume_logging_to_console()
                self._load_scraper_results("congresistas.py")

            stop_logging_to_console(filename=directories.LOGS_SCRAPERS / "bancadas.log")
            if self._recent_raw_exists(RawBancada, days=others_days):
                logger.info(
                    f"Skipping bancadas scrape: latest raw scrape is within {others_days} days"
                )
            else:
                banc = RawBancadaScraper()
                start_time = datetime.now()
                banc.get_raw_bancadas(only_current=only_current)
                scraped_banc = banc.add_bancadas_to_db()
                end_time = datetime.now()
                self.scraper_results["bancadas.py"] = ScraperStats(
                    start_time, end_time, int(scraped_banc)
                )

                resume_logging_to_console()
                self._load_scraper_results("bancadas.py")

            stop_logging_to_console(
                filename=directories.LOGS_SCRAPERS / "committees.log"
            )
            if self._recent_raw_exists(RawCommittee, days=others_days):
                logger.info(
                    f"Skipping committees scrape: latest raw scrape is within {others_days} days"
                )
            else:
                comm = RawCommitteeScraper()
                start_time = datetime.now()
                comm.get_raw_committees(only_current=only_current)
                scraped_comm = len(comm.committee_list)
                end_time = datetime.now()
                comm.add_committees_to_db()
                self.scraper_results["committees.py"] = ScraperStats(
                    start_time, end_time, scraped_comm
                )

                resume_logging_to_console()
                self._load_scraper_results("committees.py")

            stop_logging_to_console(
                filename=directories.LOGS_SCRAPERS / "organizations.log"
            )
            if self._recent_raw_exists(RawOrganization, days=others_days):
                logger.info(
                    f"Skipping organizations scrape: latest raw scrape is within {others_days} days"
                )
            else:
                org = RawOrganizationScraper()
                start_time = datetime.now()
                org.get_raw_organizations(only_current=only_current)
                scraped_orgs = len(org.organizations_list)
                end_time = datetime.now()
                org.add_organizations_to_db()
                self.scraper_results["organizations.py"] = ScraperStats(
                    start_time, end_time, scraped_orgs
                )

                resume_logging_to_console()
                self._load_scraper_results("organizations.py")

        stop_logging_to_console(filename=directories.LOGS_SCRAPERS / "bills.log")
        if scrape_bills:
            scraper = RawBillScraper()
            if all(v is not None for v in [bill_year, bill_start, bill_end]):
                self.scraper_results["bills.py"] = self._scrape_range(
                    scraper=scraper,
                    scrape_fn=scraper.scrape_bill,
                    buffer_attr="raw_bills",
                    load_fn=scraper.load_raw_bills,
                    year=int(bill_year),
                    start=int(bill_start),
                    end=int(bill_end),
                    flush_every=100,
                    entity_name="Bills",
                )
            else:
                self.scraper_results["bills.py"] = self._scrape_pending_weekly(
                    raw_model=RawBill,
                    model=Bill,
                    scraper=scraper,
                    scrape_fn=scraper.scrape_bill,
                    buffer_attr="raw_bills",
                    load_fn=scraper.load_raw_bills,
                    max_age_days=weekly_days,
                    flush_every=100,
                )

            resume_logging_to_console()
            self._load_scraper_results("bills.py")

        stop_logging_to_console(filename=directories.LOGS_SCRAPERS / "motions.log")
        if scrape_motions:
            scraper = RawMotionScraper()
            if all(v is not None for v in [motion_year, motion_start, motion_end]):
                self.scraper_results["motions.py"] = self._scrape_range(
                    scraper=scraper,
                    scrape_fn=scraper.scrape_motion,
                    buffer_attr="raw_motions",
                    load_fn=scraper.load_raw_motions,
                    year=int(motion_year),
                    start=int(motion_start),
                    end=int(motion_end),
                    flush_every=100,
                    entity_name="Motions",
                )
            else:
                self.scraper_results["motions.py"] = self._scrape_pending_weekly(
                    raw_model=RawMotion,
                    model=Motion,
                    scraper=scraper,
                    scrape_fn=scraper.scrape_motion,
                    buffer_attr="raw_motions",
                    load_fn=scraper.load_raw_motions,
                    max_age_days=weekly_days,
                    flush_every=100,
                )

            resume_logging_to_console()
            self._load_scraper_results("motions.py")

        stop_logging_to_console(filename=directories.LOGS_SCRAPERS / "documents.log")
        if scrape_documents and (scrape_bills or scrape_motions):
            doc_bill_run, doc_motion_run = self._scrape_pending_documents()
            self.scraper_results["bills_documents.py"] = doc_bill_run
            self.scraper_results["motions_documents.py"] = doc_motion_run

            resume_logging_to_console()
            self._load_scraper_results("bills_documents.py")
            self._load_scraper_results("motions_documents.py")

        stop_logging_to_console(filename=directories.LOGS_SCRAPERS / "leyes.log")
        if scrape_leyes:
            scraper = RawLeyesScraper()
            if all(v is not None for v in [ley_start, ley_end]):
                self.scraper_results["leyes.py"] = self._scrape_range(
                    scraper=scraper,
                    scrape_fn=scraper.scrape_ley,
                    buffer_attr="raw_leyes",
                    load_fn=scraper.load_raw_leyes,
                    year=None,
                    start=int(ley_start),
                    end=int(ley_end),
                    flush_every=100,
                    entity_name="Ley",
                )
            else:
                self.scraper_results["leyes.py"] = self._scrape_pending_weekly(
                    raw_model=RawLey,
                    model=Ley,
                    scraper=scraper,
                    scrape_fn=scraper.scrape_ley,
                    buffer_attr="raw_leyes",
                    load_fn=scraper.load_raw_leyes,
                    max_age_days=weekly_days,
                    flush_every=100,
                    entity_name="Ley",
                )

            resume_logging_to_console()
            self._load_scraper_results("leyes.py")

    def run_processing(
        self,
        *,
        process_bills: bool = True,
        process_motions: bool = True,
        process_leyes: bool = True,
        process_others: bool = True,
        include_documents: bool = True,
        bills_limit: int | None = None,
        leyes_limit: int | None = None,
        motions_limit: int | None = None,
    ) -> dict[str, ProcessStats]:
        """
        Process raw -> clean tables.
        """
        logger.info("Starting processing pipeline")
        summary: dict[str, ProcessStats] = {}

        if process_others:
            stop_logging_to_console(
                filename=directories.LOGS_PROCESS / "organizations.log"
            )
            summary["organizations"] = self._process_organization_definitions()
            summary["admin_memberships"] = self._process_admin_memberships()
            summary["bancadas"] = self._process_bancadas()
            resume_logging_to_console()

            stop_logging_to_console(
                filename=directories.LOGS_PROCESS / "congresistas.log"
            )
            summary["congresistas"] = self._process_congresistas()
            resume_logging_to_console()

        if process_bills:
            stop_logging_to_console(filename=directories.LOGS_PROCESS / "bills.log")
            summary["bills"] = self._process_bills(
                include_documents=include_documents,
                limit=bills_limit,
            )
            resume_logging_to_console()

        if process_motions:
            stop_logging_to_console(filename=directories.LOGS_PROCESS / "motions.log")
            summary["motions"] = self._process_motions(
                include_documents=include_documents,
                limit=motions_limit,
            )
            resume_logging_to_console()

        if process_leyes:
            stop_logging_to_console(filename=directories.LOGS_PROCESS / "leyes.log")
            summary["leyes"] = self._process_leyes(limit=leyes_limit)
            resume_logging_to_console()

        return summary

    # -----------------------------
    # Scraping internals
    # -----------------------------
    def _scrape_range(
        self,
        scraper,
        scrape_fn: Callable[[str, str], None],
        buffer_attr: str,
        load_fn: Callable[[], None],
        year: int | None,
        start: int,
        end: int,
        flush_every: int = 100,
        entity_name: str = "items",
    ) -> ScraperStats:
        logger.info(f"Scraping {entity_name} in range {year}_{start}..{year}_{end}")

        start_time = datetime.now()
        count = 0

        for number in range(start, end + 1):
            if entity_name == "Ley":
                scrape_fn(str(number))
            else:
                scrape_fn(str(year), str(number))

            current_length = len(getattr(scraper, buffer_attr))

            if current_length >= flush_every:
                count += current_length
                load_fn()

        remaining = len(getattr(scraper, buffer_attr))

        if remaining:
            count += remaining
            load_fn()

        end_time = datetime.now()
        return ScraperStats(start_time, end_time, count)

    def _scrape_pending_weekly(
        self,
        raw_model: Type[RawBill] | Type[RawMotion] | Type[RawLey],
        model: Type[Bill] | Type[Motion] | Type[Ley],
        scraper,
        scrape_fn: Callable[[str, str], None],
        buffer_attr: str,
        load_fn: Callable[[], None],
        max_age_days: int = 7,
        flush_every: int = 100,
        entity_name: str = "items",
    ) -> ScraperStats:
        pending_ids = self._get_ids_to_update(raw_model, model, max_age_days)
        start_time = datetime.now()
        count = 0

        for idx, item_id in enumerate(pending_ids, start=1):
            year, number = item_id.split("_", 1)

            if entity_name == "Ley":
                scrape_fn(str(number))
            else:
                scrape_fn(str(year), str(number))

            current_length = len(getattr(scraper, buffer_attr))

            if current_length >= flush_every:
                count += current_length
                load_fn()

            if idx % 10 == 0:
                time.sleep(2)

        remaining = len(getattr(scraper, buffer_attr))

        if remaining:
            count += remaining
            load_fn()

        end_time = datetime.now()
        return ScraperStats(start_time, end_time, count)

    def _scrape_pending_documents(self) -> tuple[ScraperStats, ScraperStats]:
        logger.info("Scraping pending bill and motion documents")

        bill_docs = RawBillDocumentScraper()
        start_time = datetime.now()
        count = 0
        for bill_id in bill_docs.get_bills_pending_documents():
            bill_docs.get_bill_documents(
                bill_id=bill_id, update=False, download_local=True, upload_s3=False
            )
            count += len(bill_docs.documents)
            bill_docs.load_raw_documents()
        end_time = datetime.now()
        doc_bill_run = ScraperStats(start_time, end_time, count)

        motion_docs = RawMotionDocumentScraper()
        start_time = datetime.now()
        count = 0
        for motion_id in motion_docs.get_motions_pending_documents():
            motion_docs.get_motion_documents(
                motion_id=motion_id, update=False, download_local=True, upload_s3=False
            )
            count += len(motion_docs.documents)
            motion_docs.load_raw_documents()
        end_time = datetime.now()
        doc_motion_run = ScraperStats(start_time, end_time, count)

        return doc_bill_run, doc_motion_run

    def _scrape_leyes_range(
        self, ley_start: int, ley_end: int, flush_every: int = 100
    ) -> ScraperStats:
        logger.info(f"Scraping leyes in range {ley_start}..{ley_end}")
        scraper = RawLeyesScraper()
        start_time = datetime.now()
        count = 0
        for ley_number in range(ley_start, ley_end + 1):
            scraper.scrape_ley(ley_number)
            count_leyes = len(scraper.raw_leyes)
            if count_leyes >= flush_every:
                count += count_leyes
                scraper.load_raw_leyes()

        remaining = len(scraper.raw_leyes)
        if remaining:
            count += remaining
            scraper.load_raw_leyes()
        end_time = datetime.now()
        return ScraperStats(start_time, end_time, count)

    # -----------------------------
    # Processing internals
    # -----------------------------
    def _membership_dates(self, membership: Membership) -> tuple[date, date]:
        seed = membership.start_date or membership.time_stamp
        leg_year = get_current_leg_year(seed)
        derived_start = date(leg_year, 7, 28)
        derived_end = date(leg_year + 1, 7, 28)

        start = membership.start_date or derived_start
        if isinstance(start, datetime):
            start = start.date()

        end = membership.end_date
        if isinstance(end, datetime):
            end = end.date()
        if end is None or end < start:
            end = derived_end

        return start, end

    def _upsert_organization_with_count(
        self, db, org_schema: Organization
    ) -> tuple[db_models.Organization, bool]:
        pre = crud_core.find_organization(
            db,
            org_name=org_schema.org_name,
            org_type=org_schema.org_type,
        )
        org = crud_core.upsert_organization(db, org_schema)
        return org, pre is None

    def _upsert_membership_schema(
        self,
        db,
        *,
        cong: db_models.Congresista,
        org: db_models.Organization,
        membership: Membership,
    ) -> db_models.Membership:
        start_date, end_date = self._membership_dates(membership)
        extra_fields = {
            "condicion": membership.condicion,
            "votes_in_election": membership.votes_in_election,
            "dist_electoral": membership.dist_electoral,
        }
        extra_fields = {k: v for k, v in extra_fields.items() if v is not None}
        return crud_core.upsert_membership(
            db=db,
            person_id=cong.id,
            org_id=org.org_id,
            leg_period=membership.leg_period,
            membership_type=org.org_type,
            role=membership.role,
            start_date=start_date,
            end_date=end_date,
            extra_fields=extra_fields,
        )

    def _process_congresistas(self) -> ProcessStats:
        stats = ProcessStats()
        clean_inserted = 0
        clean_updated = 0

        CONG_JSON = directories.PROCESSED_DATA / "cong_info_2021_2026.json"

        dict_cong_data = get_cong_data(CONG_JSON)
        with self.DBSession() as raw_db, self.DBSession() as db:
            rows = (
                raw_db.query(RawCongresista)
                .filter(
                    RawCongresista.last_update.is_(True),
                    RawCongresista.processed.is_(False),
                )
                .all()
            )
            for raw_cong in rows:
                try:
                    # TODO: Remove this range to process all years
                    if raw_cong.leg_period not in [
                        "Parlamentario 2021 - 2026",
                        "Parlamentario 2016 - 2021",
                    ]:
                        raw_cong.processed = False
                        stats.skipped += 1
                        continue
                    cong_schema, org_schemas, profile_memberships = (
                        process_profile_content(raw_cong, dict_cong_data)
                    )
                    pre = crud_core.find_congresista(
                        db,
                        name=cong_schema.full_name,
                        website=cong_schema.website,
                    )
                    cong = crud_core.upsert_congresista(db, cong_schema)
                    if pre is None:
                        clean_inserted += 1
                    else:
                        clean_updated += 1

                    for org_schema in org_schemas:
                        self._upsert_organization_with_count(db, org_schema)

                    memberships = profile_memberships
                    if raw_cong.memberships_content:
                        memberships.extend(
                            process_cong_memberships(raw_cong, cong_schema)
                        )
                    for ms in memberships:
                        # TODO: We need to implement a fuzzy match for finding organization
                        org = crud_core.find_organization(
                            db=db,
                            org_name=ms.org_name,
                            org_type=ms.org_type,
                        )
                        if org is None:
                            stats.skipped += 1
                            continue
                        self._upsert_membership_schema(
                            db,
                            cong=cong,
                            org=org,
                            membership=ms,
                        )

                    raw_cong.processed = True
                    stats.processed += 1
                except Exception as exc:
                    logger.exception(
                        f"Error processing RawCongresista id={raw_cong.id}: {exc}"
                    )
                    db.rollback()
                    stats.errors += 1
            db.commit()
            raw_db.commit()
        logger.info(
            f"[congresistas] raw_total={len(rows)} processed={stats.processed} skipped={stats.skipped} errors={stats.errors} clean_inserted={clean_inserted} clean_updated={clean_updated}"
        )
        return stats

    def _process_organization_definitions(self) -> ProcessStats:
        stats = ProcessStats()
        clean_inserted = 0
        clean_updated = 0
        with self.DBSession() as raw_db, self.DBSession() as db:
            for org_schema in process_chambers():
                _, inserted = self._upsert_organization_with_count(db, org_schema)
                if inserted:
                    clean_inserted += 1
                else:
                    clean_updated += 1

            # Committees
            committees = (
                raw_db.query(RawCommittee)
                .filter(
                    RawCommittee.last_update.is_(True),
                    RawCommittee.processed.is_(False),
                )
                .all()
            )

            for raw_comm in committees:
                try:
                    # TODO: Remove this range to process all years
                    if int(raw_comm.legislative_year) not in range(2016, 2027):
                        raw_comm.processed = False
                        stats.skipped += 1
                        continue
                    for org_schema in process_committee(raw_comm):
                        _, inserted = self._upsert_organization_with_count(
                            db, org_schema
                        )
                        if inserted:
                            clean_inserted += 1
                        else:
                            clean_updated += 1
                    raw_comm.processed = True
                    stats.processed += 1
                except Exception as exc:
                    logger.exception(
                        f"Error processing RawCommittee id={raw_comm.id}: {exc}"
                    )
                    db.rollback()
                    stats.errors += 1

            # Administrative organization definitions. RawOrganization is marked
            # processed only after its memberships are loaded.
            organizations = (
                raw_db.query(RawOrganization)
                .filter(
                    RawOrganization.last_update.is_(True),
                    RawOrganization.processed.is_(False),
                )
                .all()
            )
            for raw_org in organizations:
                try:
                    # TODO: Remove this range to process all years
                    if int(raw_org.legislative_year) not in range(2016, 2027):
                        raw_org.processed = False
                        stats.skipped += 1
                        continue
                    org_schema, _ = process_admin_org(raw_org)
                    _, inserted = self._upsert_organization_with_count(db, org_schema)
                    if inserted:
                        clean_inserted += 1
                    else:
                        clean_updated += 1
                    stats.processed += 1
                except Exception as exc:
                    logger.exception(
                        f"Error processing RawOrganization id={raw_org.id}: {exc}"
                    )
                    db.rollback()
                    stats.errors += 1

            db.commit()
            raw_db.commit()
        logger.info(
            f"[organization_definitions] raw_committees={len(committees)} raw_orgs={len(organizations)} processed={stats.processed} skipped={stats.skipped} errors={stats.errors} clean_inserted={clean_inserted} clean_updated={clean_updated}"
        )
        return stats

    def _process_admin_memberships(self) -> ProcessStats:
        stats = ProcessStats()
        with self.DBSession() as raw_db, self.DBSession() as db:
            organizations = (
                raw_db.query(RawOrganization)
                .filter(
                    RawOrganization.last_update.is_(True),
                    RawOrganization.processed.is_(False),
                )
                .all()
            )
            for raw_org in organizations:
                try:
                    if int(raw_org.legislative_year) not in range(2016, 2027):
                        raw_org.processed = False
                        stats.skipped += 1
                        continue
                    org_schema, membership_list = process_admin_org(raw_org)
                    org, _ = self._upsert_organization_with_count(db, org_schema)
                    missing = False
                    for ms in membership_list:
                        cong = crud_core.find_congresista(
                            db,
                            name=ms.cong_name,
                            website=ms.website,
                        )
                        if cong is None:
                            missing = True
                            stats.skipped += 1
                            continue
                        self._upsert_membership_schema(
                            db,
                            cong=cong,
                            org=org,
                            membership=ms,
                        )
                    raw_org.processed = not missing
                    stats.processed += 1
                except Exception as exc:
                    logger.exception(
                        f"Error processing RawOrganization memberships id={raw_org.id}: {exc}"
                    )
                    db.rollback()
                    stats.errors += 1

            db.commit()
            raw_db.commit()
        logger.info(
            f"[admin_memberships] raw_orgs={len(organizations)} processed={stats.processed} skipped={stats.skipped} errors={stats.errors}"
        )
        return stats

    def _process_bancadas(self) -> ProcessStats:
        stats = ProcessStats()
        clean_inserted = 0
        clean_updated = 0
        with self.DBSession() as raw_db, self.DBSession() as db:
            rows = (
                raw_db.query(RawBancada)
                .filter(
                    RawBancada.last_update.is_(True), RawBancada.processed.is_(False)
                )
                .all()
            )
            for raw_bancada in rows:
                try:
                    if raw_bancada.legislative_period not in [
                        "Parlamentario 2021 - 2026"
                    ]:
                        raw_bancada.processed = False
                        stats.skipped += 1
                        continue
                    bancadas, memberships = process_bancada(raw_bancada)
                    org_index: dict[tuple[str, str], db_models.Organization] = {}
                    for bancada in bancadas:
                        org, inserted = self._upsert_organization_with_count(
                            db, bancada
                        )
                        org_index[(org.org_name.lower(), org.org_type)] = org
                        if inserted:
                            clean_inserted += 1
                        else:
                            clean_updated += 1

                    missing = False
                    for ms in memberships:
                        cong = crud_core.find_congresista(
                            db,
                            name=ms.cong_name,
                            website=ms.website,
                        )
                        org = org_index.get((ms.org_name.lower(), ms.org_type.value))
                        if cong is None or org is None:
                            missing = True
                            stats.skipped += 1
                            continue
                        self._upsert_membership_schema(
                            db,
                            cong=cong,
                            org=org,
                            membership=ms,
                        )

                    raw_bancada.processed = not missing
                    stats.processed += 1
                except Exception as exc:
                    logger.exception(
                        f"Error processing RawBancada id={raw_bancada.id}: {exc}"
                    )
                    db.rollback()
                    stats.errors += 1

            db.commit()
            raw_db.commit()
        logger.info(
            f"[bancadas] raw_total={len(rows)} processed={stats.processed} skipped={stats.skipped} errors={stats.errors} clean_inserted={clean_inserted} clean_updated={clean_updated}"
        )
        return stats

    def _process_bills(
        self, *, include_documents: bool, limit: int | None
    ) -> ProcessStats:
        stats = ProcessStats()
        clean_inserted = 0
        clean_updated = 0
        with self.DBSession() as raw_db, self.DBSession() as db:
            query = raw_db.query(RawBill).filter(
                RawBill.last_update.is_(True), RawBill.processed.is_(False)
            )
            if limit is not None:
                query = query.limit(limit)
            rows = query.all()

            for raw_bill in rows:
                try:
                    bill_schema, bill_congs, bill_steps = process_bill(raw_bill)

                    author = None
                    if bill_schema.author_name:
                        author = crud_core.find_congresista(
                            db,
                            name=bill_schema.author_name,
                            website=bill_schema.author_web,
                        )
                    if author is None:
                        logger.warning(
                            f"Skipping RawBill id={raw_bill.id}: author not found"
                        )
                        stats.skipped += 1
                        continue

                    bancada = None
                    if bill_schema.bancada_name:
                        bancada = crud_core.find_organization(
                            db,
                            org_name=bill_schema.bancada_name,
                            org_type="Bancada",
                        )
                    if bancada is None:
                        logger.warning(
                            f"Skipping RawBill id={raw_bill.id}: bancada not found"
                        )
                        stats.skipped += 1
                        continue

                    bill_orgs = process_bill_organizations(raw_bill, bill_steps)
                    chamber_schema = find_organization_schema(
                        bill_orgs,
                        org_name="Cámara de Diputados",
                        org_type="Cámara",
                    )

                    if chamber_schema is None:
                        logger.warning(
                            f"Skipping RawBill id={raw_bill.id}: chamber relation not generated"
                        )
                        stats.skipped += 1
                        continue
                    chamber = crud_core.find_organization(
                        db,
                        org_name="Cámara de Diputados",
                        org_type="Cámara",
                    )
                    if chamber is None:
                        logger.warning(
                            f"Skipping RawBill id={raw_bill.id}: Cámara de Diputados organization not found"
                        )
                        stats.skipped += 1
                        continue

                    pre = db.get(db_models.Bill, bill_schema.id)
                    bill = crud_bills.upsert_bill(db, bill_schema)
                    if pre is None:
                        clean_inserted += 1
                    else:
                        clean_updated += 1

                    for step_schema in bill_steps:
                        crud_bills.upsert_bill_step(db, step_schema)

                    for org_schema in bill_orgs:
                        org = crud_core.find_organization(
                            db=db,
                            org_name=org_schema.org_name,
                            org_type=org_schema.org_type,
                        )
                        if org is None:
                            logger.warning(
                                f"Skipping BillOrganization bill_id={bill.id}, org={org_schema.org_name}: organization not found"
                            )
                            stats.skipped += 1
                            continue
                        crud_bills.upsert_bill_organization(
                            db, bill.id, org.org_id, org_schema
                        )

                    presentation_date = chamber_schema.presentation_date
                    for cong_rel in bill_congs:
                        cong = crud_core.find_congresista(
                            db,
                            name=cong_rel.nombre,
                            website=cong_rel.web_page,
                        )
                        if cong is None:
                            stats.skipped += 1
                            continue
                        signer_bancada = crud_core.find_active_bancada_for_person(
                            db, cong.id, presentation_date
                        )
                        if signer_bancada is None:
                            logger.warning(
                                f"Skipping BillCongresistas bill_id={bill.id}, person_id={cong.id}: active bancada not found"
                            )
                            stats.skipped += 1
                            continue
                        crud_bills.upsert_bill_congresista(
                            db,
                            bill.id,
                            cong.id,
                            signer_bancada.org_id,
                            cong_rel.role_type.value
                            if hasattr(cong_rel.role_type, "value")
                            else cong_rel.role_type,
                        )

                    if include_documents:
                        for raw_doc in crud_bills.find_raw_bill_documents(
                            raw_db, bill.id
                        ):
                            pages = crud_bills.find_raw_bill_pages(
                                raw_db, bill.id, raw_doc.step_id, raw_doc.file_id
                            )
                            if not pages:
                                stats.skipped += 1
                                continue
                            try:
                                text_schema = process_bill_text(pages)
                            except ValueError:
                                stats.skipped += 1
                                continue
                            crud_bills.upsert_bill_text(
                                db,
                                bill_id=text_schema.bill_id,
                                step_id=text_schema.step_id,
                                file_id=text_schema.file_id,
                                version_id=text_schema.version_id,
                                text=text_schema.text,
                            )
                            raw_doc.processed = True

                    raw_bill.processed = True
                    stats.processed += 1
                except Exception as exc:
                    logger.exception(
                        f"Error processing RawBill id={raw_bill.id}: {exc}"
                    )
                    db.rollback()
                    stats.errors += 1

            db.commit()
            raw_db.commit()
        logger.info(
            f"[bills] raw_total={len(rows)} processed={stats.processed} skipped={stats.skipped} errors={stats.errors} clean_inserted={clean_inserted} clean_updated={clean_updated}"
        )
        return stats

    def _process_motions(
        self, *, include_documents: bool, limit: int | None
    ) -> ProcessStats:
        stats = ProcessStats()
        clean_inserted = 0
        clean_updated = 0
        with self.DBSession() as raw_db, self.DBSession() as db:
            query = raw_db.query(RawMotion).filter(
                RawMotion.last_update.is_(True), RawMotion.processed.is_(False)
            )
            if limit is not None:
                query = query.limit(limit)
            rows = query.all()

            for raw_motion in rows:
                try:
                    motion_schema, motion_congs, motion_steps = process_motion(
                        raw_motion
                    )

                    author = None
                    if motion_schema.author_name:
                        author = crud_core.find_congresista(
                            db,
                            name=motion_schema.author_name,
                            website=motion_schema.author_web,
                        )
                    if author is None:
                        logger.warning(
                            f"Skipping RawMotion id={raw_motion.id}: author not found"
                        )
                        stats.skipped += 1
                        continue

                    motion_orgs = process_motion_organizations(raw_motion, motion_steps)
                    chamber_schema = find_motion_organization_schema(
                        motion_orgs,
                        org_name="Cámara de Diputados",
                        org_type="Cámara",
                    )
                    if chamber_schema is None:
                        logger.warning(
                            f"Skipping RawMotion id={raw_motion.id}: chamber relation not generated"
                        )
                        stats.skipped += 1
                        continue

                    chamber = crud_core.find_organization(
                        db,
                        org_name="Cámara de Diputados",
                        org_type="Cámara",
                    )
                    if chamber is None:
                        logger.warning(
                            f"Skipping RawMotion id={raw_motion.id}: Cámara de Diputados organization not found"
                        )
                        stats.skipped += 1
                        continue

                    pre = db.get(db_models.Motion, motion_schema.id)
                    motion = crud_motions.upsert_motion(db, motion_schema)
                    if pre is None:
                        clean_inserted += 1
                    else:
                        clean_updated += 1

                    for step_schema in motion_steps:
                        crud_motions.upsert_motion_step(db, step_schema)

                    for org_schema in motion_orgs:
                        org = crud_core.find_organization(
                            db=db,
                            org_name=org_schema.org_name,
                            org_type=org_schema.org_type,
                        )
                        if org is None:
                            logger.warning(
                                f"Skipping MotionOrganization motion_id={motion.id}, org={org_schema.org_name}: organization not found"
                            )
                            stats.skipped += 1
                            continue
                        crud_motions.upsert_motion_organization(
                            db, motion.id, org.org_id, org_schema
                        )

                    presentation_date = chamber_schema.presentation_date
                    for cong_rel in motion_congs:
                        cong = crud_core.find_congresista(
                            db,
                            name=cong_rel.nombre,
                            website=cong_rel.web_page,
                        )
                        if cong is None:
                            stats.skipped += 1
                            continue
                        signer_bancada = crud_core.find_active_bancada_for_person(
                            db, cong.id, presentation_date
                        )
                        if signer_bancada is None:
                            logger.warning(
                                f"Skipping MotionCongresistas motion_id={motion.id}, person_id={cong.id}: active bancada not found"
                            )
                            stats.skipped += 1
                            continue
                        crud_motions.upsert_motion_congresista(
                            db,
                            motion.id,
                            cong.id,
                            signer_bancada.org_id,
                            cong_rel.role_type.value
                            if hasattr(cong_rel.role_type, "value")
                            else cong_rel.role_type,
                        )

                    if include_documents:
                        for raw_doc in crud_motions.find_raw_motion_documents(
                            raw_db, motion.id
                        ):
                            pages = crud_motions.find_raw_motion_pages(
                                raw_db, motion.id, raw_doc.step_id, raw_doc.file_id
                            )
                            if not pages:
                                stats.skipped += 1
                                continue
                            try:
                                text_schema = process_motion_text(pages)
                            except ValueError:
                                stats.skipped += 1
                                continue
                            crud_motions.upsert_motion_text(
                                db,
                                motion_id=text_schema.motion_id,
                                step_id=text_schema.step_id,
                                file_id=text_schema.file_id,
                                version_id=text_schema.version_id,
                                text=text_schema.text,
                            )
                            raw_doc.processed = True

                    raw_motion.processed = True
                    stats.processed += 1
                except Exception as exc:
                    logger.exception(
                        f"Error processing RawMotion id={raw_motion.id}: {exc}"
                    )
                    db.rollback()
                    stats.errors += 1

            db.commit()
            raw_db.commit()
        logger.info(
            f"[motions] raw_total={len(rows)} processed={stats.processed} skipped={stats.skipped} errors={stats.errors} clean_inserted={clean_inserted} clean_updated={clean_updated}"
        )
        return stats

    def _process_leyes(self, *, limit: int | None) -> ProcessStats:
        stats = ProcessStats()
        clean_inserted = 0
        clean_updated = 0
        with self.DBSession() as raw_db, self.DBSession() as db:
            query = raw_db.query(RawLey).filter(
                RawLey.last_update.is_(True), RawLey.processed.is_(False)
            )
            if limit is not None:
                query = query.limit(limit)
            rows = query.all()

            for raw_ley in rows:
                try:
                    ley_schema = process_leyes(raw_ley)
                    if ley_schema is None:
                        raw_ley.processed = False
                        stats.skipped += 1
                        continue
                    pre = db.get(db_models.Ley, ley_schema.id)
                    crud_core.upsert_ley(db, ley_schema)
                    if pre is None:
                        clean_inserted += 1
                    else:
                        clean_updated += 1

                    raw_ley.processed = True
                    stats.processed += 1
                except Exception as exc:
                    logger.exception(f"Error processing RawLey id={raw_ley.id}: {exc}")
                    db.rollback()
                    stats.errors += 1

            db.commit()
            raw_db.commit()
        logger.info(
            f"[leyes] raw_total={len(rows)} processed={stats.processed} skipped={stats.skipped} errors={stats.errors} clean_inserted={clean_inserted} clean_updated={clean_updated}"
        )
        return stats
