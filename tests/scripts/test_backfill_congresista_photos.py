"""Unit tests for scripts/backfill_congresista_photos.py's --force
row-selection query, against a real in-memory DB."""

import importlib.util
from pathlib import Path

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from backend.database import models as db_models
from backend.database.models import Base

REPO_ROOT = Path(__file__).resolve().parents[2]


def _load_script():
    spec = importlib.util.spec_from_file_location(
        "backfill_congresista_photos",
        REPO_ROOT / "scripts" / "backfill_congresista_photos.py",
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


mod = _load_script()


def _make_session():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    SessionLocal = sessionmaker(bind=engine)
    return SessionLocal()


def test_build_query_default_only_selects_missing_photos():
    db = _make_session()
    with_photo = db_models.Congresista(
        full_name="Has Photo", website="w1", photo_url="p1", photo_bytes=b"\xff\xd8\xff"
    )
    without_photo = db_models.Congresista(
        full_name="No Photo", website="w2", photo_url="p2", photo_bytes=None
    )
    db.add_all([with_photo, without_photo])
    db.commit()

    rows = db.scalars(mod.build_query(force=False)).all()

    assert [r.full_name for r in rows] == ["No Photo"]


def test_build_query_force_selects_everyone():
    db = _make_session()
    with_photo = db_models.Congresista(
        full_name="Has Photo", website="w1", photo_url="p1", photo_bytes=b"\xff\xd8\xff"
    )
    without_photo = db_models.Congresista(
        full_name="No Photo", website="w2", photo_url="p2", photo_bytes=None
    )
    db.add_all([with_photo, without_photo])
    db.commit()

    rows = db.scalars(mod.build_query(force=True)).all()

    assert {r.full_name for r in rows} == {"Has Photo", "No Photo"}


def test_build_query_respects_limit():
    db = _make_session()
    for i in range(3):
        db.add(
            db_models.Congresista(
                full_name=f"Cong {i}", website=f"w{i}", photo_url=f"p{i}"
            )
        )
    db.commit()

    rows = db.scalars(mod.build_query(force=True, limit=2)).all()

    assert len(rows) == 2
