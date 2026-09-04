"""Unit tests for scripts/backfill_congresista_id.py."""

import importlib.util
from pathlib import Path
from unittest.mock import patch

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from backend.database import models as db_models
from backend.database.models import Base

REPO_ROOT = Path(__file__).resolve().parents[2]


def _load_script():
    spec = importlib.util.spec_from_file_location(
        "backfill_congresista_id", REPO_ROOT / "scripts" / "backfill_congresista_id.py"
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


def test_build_name_index_merges_both_files(tmp_path, monkeypatch):
    monkeypatch.setattr(mod, "CONG_JSON", tmp_path / "legacy.json")
    monkeypatch.setattr(mod, "CONG_JSON_2026", tmp_path / "current.json")

    def fake_get_cong_data(path, *, leg_period=None):
        if leg_period == "2026-2031":
            return {
                "key": {
                    "full_name": "Alejandro Aurelio Aguinaga Recuenco",
                    "congresista_id": 4,
                }
            }
        return {
            "key": {"full_name": "Ana Maria Torres Vega", "congresista_id": 7},
        }

    with patch.object(mod, "get_cong_data", side_effect=fake_get_cong_data):
        with patch.object(Path, "exists", return_value=True):
            index = mod.build_name_index()

    assert index[mod.normalize_name("Ana Maria Torres Vega", sort_tokens=True)] == 7
    assert (
        index[
            mod.normalize_name("Alejandro Aurelio Aguinaga Recuenco", sort_tokens=True)
        ]
        == 4
    )


def test_build_name_index_skips_missing_files(tmp_path, monkeypatch):
    monkeypatch.setattr(mod, "CONG_JSON", tmp_path / "does-not-exist.json")
    monkeypatch.setattr(mod, "CONG_JSON_2026", tmp_path / "also-missing.json")

    index = mod.build_name_index()

    assert index == {}


def test_main_backfills_matched_rows_only_when_apply(monkeypatch, capsys):
    db = _make_session()
    matched = db_models.Congresista(
        full_name="Ana Maria Torres Vega", website="w1", photo_url="p1"
    )
    unmatched = db_models.Congresista(
        full_name="Someone Unknown", website="w2", photo_url="p2"
    )
    already_set = db_models.Congresista(
        full_name="Already Has One",
        website="w3",
        photo_url="p3",
        congresista_id=999,
    )
    db.add_all([matched, unmatched, already_set])
    db.commit()

    monkeypatch.setattr(
        mod,
        "build_name_index",
        lambda: {mod.normalize_name("Ana Maria Torres Vega", sort_tokens=True): 7},
    )

    class _FakeSessionLocal:
        def __init__(self, *a, **k):
            pass

        def __call__(self):
            return db

    monkeypatch.setattr(mod, "create_engine", lambda *a, **k: None)
    monkeypatch.setattr(mod, "sessionmaker", lambda *a, **k: _FakeSessionLocal())
    monkeypatch.setattr(db, "close", lambda: None)

    monkeypatch.setattr("sys.argv", ["backfill_congresista_id.py"])
    mod.main()

    db.refresh(matched)
    assert matched.congresista_id is None  # dry run: no write

    monkeypatch.setattr("sys.argv", ["backfill_congresista_id.py", "--apply"])
    mod.main()

    db.refresh(matched)
    db.refresh(unmatched)
    db.refresh(already_set)
    assert matched.congresista_id == 7
    assert unmatched.congresista_id is None
    assert already_set.congresista_id == 999
