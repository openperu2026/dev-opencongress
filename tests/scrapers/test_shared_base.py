from datetime import datetime, UTC

from sqlalchemy import create_engine
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import sessionmaker

from backend.database.raw_models import Base, RawLey
from backend.scrapers.base import SharedRawScraperBase


def setup_inmemory_db():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    SessionLocal = sessionmaker(bind=engine)
    return engine, SessionLocal


class _DummyLeyScraper(SharedRawScraperBase):
    """Minimal concrete scraper for exercising the shared base directly,
    using RawLey (bare autoincrement PK) as the backing model."""

    def track(self, ley: RawLey) -> list[RawLey]:
        def lookup(session):
            return (
                session.query(RawLey)
                .filter(RawLey.id == ley.id)
                .order_by(RawLey.timestamp.desc())
                .first()
            )

        return self._update_tracking(ley, lookup)


def test_update_tracking_no_prior_row_returns_single_item_list():
    _, SessionLocal = setup_inmemory_db()
    scraper = _DummyLeyScraper(engine=SessionLocal().get_bind())

    ley = RawLey(id="1", timestamp=datetime.now(UTC), data="<xml>v1</xml>")
    result = scraper.track(ley)

    assert result == [ley]
    assert ley.changed is True
    assert ley.last_update is True
    assert ley.processed is False


def test_update_tracking_unchanged_returns_empty_list_and_does_not_flip():
    _, SessionLocal = setup_inmemory_db()

    with SessionLocal() as session:
        existing = RawLey(
            id="1",
            timestamp=datetime.now(UTC),
            data="<xml>same</xml>",
            last_update=True,
            changed=True,
            processed=False,
        )
        session.add(existing)
        session.commit()

    scraper = _DummyLeyScraper(engine=SessionLocal().get_bind())
    scraper.Session = SessionLocal

    new = RawLey(id="1", timestamp=datetime.now(UTC), data="<xml>same</xml>")
    result = scraper.track(new)

    assert result == []

    with SessionLocal() as session:
        row = session.query(RawLey).filter(RawLey.id == "1").first()
        assert row.last_update is True


def test_update_tracking_changed_flips_previous_and_records_for_compensation():
    _, SessionLocal = setup_inmemory_db()

    with SessionLocal() as session:
        existing = RawLey(
            id="1",
            timestamp=datetime.now(UTC),
            data="<xml>v1</xml>",
            last_update=True,
            changed=True,
            processed=False,
        )
        session.add(existing)
        session.commit()

    scraper = _DummyLeyScraper(engine=SessionLocal().get_bind())
    scraper.Session = SessionLocal

    new = RawLey(id="1", timestamp=datetime.now(UTC), data="<xml>v2</xml>")
    result = scraper.track(new)

    assert len(result) == 2
    assert result[0] is new
    assert new.changed is True
    assert new.last_update is True
    assert new.processed is False
    assert scraper._tracking_updates == [(RawLey, (1,))]

    with SessionLocal() as session:
        row = session.query(RawLey).filter(RawLey.id == "1").first()
        assert row.last_update is False


def test_add_to_db_empty_buffer_returns_false():
    _, SessionLocal = setup_inmemory_db()
    scraper = _DummyLeyScraper(engine=SessionLocal().get_bind())

    assert scraper._add_to_db([], "Leyes") is False


def test_add_to_db_success_clears_tracking_updates():
    _, SessionLocal = setup_inmemory_db()
    scraper = _DummyLeyScraper(engine=SessionLocal().get_bind())
    scraper.Session = SessionLocal
    scraper._tracking_updates = [(RawLey, ("stale",))]

    ley = RawLey(id="1", timestamp=datetime.now(UTC), data="<xml>v1</xml>")
    assert scraper._add_to_db([ley], "Leyes") is True
    assert scraper._tracking_updates == []

    with SessionLocal() as session:
        assert session.query(RawLey).filter(RawLey.id == "1").count() == 1


def test_add_to_db_failure_restores_flipped_last_update():
    """Regression test for the compensation mechanism (/plan-eng-review
    Phase 2, 2026-09-04, generalized from leyes.py to all 7 scrapers): if
    the bulk-save fails after update_tracking already flipped a previous
    row's last_update, that flip must be restored -- otherwise a failed
    load run permanently loses track of which row is "current" for that
    entity."""
    _, SessionLocal = setup_inmemory_db()

    with SessionLocal() as session:
        existing = RawLey(
            id="1",
            timestamp=datetime.now(UTC),
            data="<xml>v1</xml>",
            last_update=True,
            changed=True,
            processed=False,
        )
        session.add(existing)
        session.commit()

    scraper = _DummyLeyScraper(engine=SessionLocal().get_bind())
    scraper.Session = SessionLocal

    new = RawLey(id="1", timestamp=datetime.now(UTC), data="<xml>v2</xml>")
    tracked = scraper.track(new)
    assert (
        SessionLocal().query(RawLey).filter(RawLey.id == "1").first().last_update
        is False
    )

    def boom(*args, **kwargs):
        raise SQLAlchemyError("forced failure")

    session_for_save = SessionLocal()
    scraper.session = session_for_save
    scraper.Session = lambda: session_for_save
    session_for_save.bulk_save_objects = boom

    ok = scraper._add_to_db(tracked, "Leyes")
    assert ok is False

    with SessionLocal() as session:
        restored = session.query(RawLey).filter(RawLey.id == "1").first()
        assert restored.last_update is True
