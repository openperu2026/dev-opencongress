"""Shared base class for all raw scrapers.

Consolidates three things that were previously duplicated -- correctly in
bills.py/motions.py, duplicated-and-buggy in leyes.py/congresistas.py/
bancadas.py/committees.py/organizations.py -- across all 7 raw scrapers:

  1. Session/engine ownership: __init__(session=None, engine=None), with
     session-reuse when the caller passes one in.
  2. update_tracking()'s changed-detection contract: return [] when
     unchanged (so callers .extend() a no-op instead of always storing a
     duplicate row), [obj] for a first-ever row, or [obj, last] when
     changed -- wrapped in try/except/rollback, plus a compensation
     mechanism (originally leyes.py-only) that restores a flipped
     last_update if the later bulk-save fails.
  3. add_*_to_db()'s bulk-save pattern, returning False gracefully on an
     empty buffer (routine now that an unchanged scrape appends nothing)
     instead of asserting/crashing.

Each subclass keeps its own buffer attribute (self.raw_bills, self.raw_leyes,
etc.) and its own entity-specific scrape/create methods; only the shared
tracking/persistence plumbing lives here.
"""

from loguru import logger
from sqlalchemy import create_engine, inspect
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import sessionmaker

from backend.config import settings

DB_PATH = settings.DB_URL


class SharedRawScraperBase:
    def __init__(self, session=None, engine=None):
        if session is not None:
            self.session = session
            self.engine = session.get_bind()
            self.Session = sessionmaker(bind=self.engine)
        else:
            self.engine = engine or create_engine(DB_PATH)
            self.Session = sessionmaker(bind=self.engine)
            self.session = None

        # (model, identity) pairs whose last_update was flipped to False
        # this run -- restored if the later bulk-save fails, so a failed
        # load never leaves a raw table with zero "current" rows for a
        # business id. Identity is the SQLAlchemy primary-key tuple, which
        # works uniformly whether a model's PK is a bare autoincrement id
        # (RawLey, RawCongresista, RawBancada, RawCommittee,
        # RawOrganization) or composite (RawBill/RawMotion's (id,
        # timestamp)).
        self._tracking_updates: list[tuple[type, tuple]] = []

    def _update_tracking(self, obj, lookup_query) -> list:
        """Generic update-tracking body shared by all 7 scrapers.

        ``lookup_query`` is a zero-arg callable (a closure over ``obj`` and
        the caller's own scoping columns) that, given the open session,
        returns the current last_update=True row for this entity's key, or
        None. Comparison uses RawBase.__eq__ (all mapped columns except
        id/timestamp/last_update/changed/processed).
        """
        session = self.session or self.Session()
        try:
            last = lookup_query(session)

            # First ever version of this entity.
            if last is None:
                obj.changed = True
                obj.last_update = True
                obj.processed = False
                return [obj]

            if obj != last:
                obj.changed = True
                obj.last_update = True
                obj.processed = False
                last.last_update = False
                session.add(last)
                session.commit()
                self._tracking_updates.append((type(last), inspect(last).identity))
                return [obj, last]

            # No changes.
            return []
        except SQLAlchemyError as e:
            logger.error(f"Failed to add update tracking to {type(obj).__name__}: {e}")
            session.rollback()
            return []
        finally:
            if self.session is None:
                session.close()

    def _add_to_db(self, buffer: list, entity_name: str) -> bool:
        """Generic bulk-save. Returns False (not an assert) on an empty
        buffer -- routine now that an unchanged scrape appends nothing."""
        if not buffer:
            logger.info(
                f"There are no Raw {entity_name} scraped. Nothing to load to DB."
            )
            return False

        session = self.session or self.Session()
        try:
            session.bulk_save_objects(buffer)
            session.commit()
            logger.success(f"Added {len(buffer)} Raw {entity_name} to table.")
            self._tracking_updates = []
            return True
        except SQLAlchemyError as e:
            logger.error(f"Failed to add {entity_name} to Raw {entity_name} table: {e}")
            session.rollback()
            self._restore_tracking_updates()
            return False
        finally:
            if self.session is None:
                session.close()

    def _restore_tracking_updates(self) -> None:
        if not self._tracking_updates:
            return

        session = self.session or self.Session()
        try:
            for model, identity in self._tracking_updates:
                obj = session.get(model, identity)
                if obj is not None:
                    obj.last_update = True
            session.commit()
        except SQLAlchemyError as e:
            logger.error(f"Failed to restore tracking updates: {e}")
            session.rollback()
        finally:
            if self.session is None:
                session.close()
            self._tracking_updates = []
