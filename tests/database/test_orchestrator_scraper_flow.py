from __future__ import annotations

from datetime import datetime
from types import SimpleNamespace

from backend.database import orchestrator as orchestrator_module
from backend.database.crud.pipeline_core import ScraperStats
from backend.database.orchestrator import OpenPeruOrchestrator
from backend.database.raw_models import RawBill, RawLey, RawMotion


class DummyStage:
    def __enter__(self):
        return SimpleNamespace(info=lambda *args, **kwargs: None)

    def __exit__(self, exc_type, exc, tb):
        return False


class DummyLogManager:
    def console_logger(self):
        return SimpleNamespace(info=lambda *args, **kwargs: None)

    def stage(self, *args, **kwargs):
        return DummyStage()


class RecordingLogManager:
    """Like DummyLogManager, but records every console.info message so
    tests can assert on which code paths actually ran (distinguishing the
    LEGACY scrape_others block from the current-period chamber block by
    their distinct log messages, since both may leave zero scraper
    instances behind when _recent_raw_exists is mocked True)."""

    def __init__(self):
        self.messages: list[str] = []

    def console_logger(self):
        return SimpleNamespace(info=lambda msg, *a, **k: self.messages.append(msg))

    def stage(self, *args, **kwargs):
        return DummyStage()


class DummyBillScraper:
    raw_bills = []

    def scrape_bill(self, *args):
        pass

    def scrape_chamber_bill(self, *args):
        pass

    def load_raw_bills(self):
        pass


class DummyMotionScraper:
    raw_motions = []

    def scrape_motion(self, *args):
        pass

    def scrape_chamber_motion(self, *args):
        pass

    def load_raw_motions(self):
        pass


class DummyLeyScraper:
    raw_leyes = []

    def scrape_ley(self, *args):
        pass

    def load_raw_leyes(self):
        pass


def _stats(start_second: int, end_second: int, scrapped: int) -> ScraperStats:
    return ScraperStats(
        datetime(2026, 1, 1, 0, 0, start_second),
        datetime(2026, 1, 1, 0, 0, end_second),
        scrapped,
    )


def test_bills_scrape_new_ids_before_pending_daily(monkeypatch):
    calls = []
    orch = OpenPeruOrchestrator.__new__(OpenPeruOrchestrator)

    monkeypatch.setattr(orchestrator_module, "log_manager", DummyLogManager())
    monkeypatch.setattr(
        "backend.scrapers.bills.RawBillScraper",
        DummyBillScraper,
    )
    monkeypatch.setattr(
        orch,
        "_scrape_range",
        lambda **kwargs: (
            calls.append(("range", kwargs["raw_model"])) or _stats(1, 2, 3)
        ),
    )
    monkeypatch.setattr(
        orch,
        "_scrape_pending_daily",
        lambda **kwargs: (
            calls.append(("pending", kwargs["raw_model"], kwargs["model"]))
            or _stats(3, 4, 5)
        ),
    )
    monkeypatch.setattr(
        orch, "_load_scraper_results", lambda name: calls.append(("load", name))
    )

    orch.run_scrapers(
        scrape_bills=True,
        scrape_motions=False,
        scrape_leyes=False,
        scrape_others=False,
        leg_period="2021-2026",
    )

    assert calls == [
        ("range", orchestrator_module.RawBill),
        ("pending", orchestrator_module.RawBill, orchestrator_module.Bill),
        ("load", "bills.py"),
    ]
    assert orch.scraper_results["bills.py"] == _stats(1, 4, 8)


def test_motions_scrape_new_ids_before_pending_daily(monkeypatch):
    calls = []
    orch = OpenPeruOrchestrator.__new__(OpenPeruOrchestrator)

    monkeypatch.setattr(orchestrator_module, "log_manager", DummyLogManager())
    monkeypatch.setattr(
        "backend.scrapers.motions.RawMotionScraper",
        DummyMotionScraper,
    )
    monkeypatch.setattr(
        orch,
        "_scrape_range",
        lambda **kwargs: (
            calls.append(("range", kwargs["raw_model"])) or _stats(1, 2, 7)
        ),
    )
    monkeypatch.setattr(
        orch,
        "_scrape_pending_daily",
        lambda **kwargs: (
            calls.append(("pending", kwargs["raw_model"], kwargs["model"]))
            or _stats(3, 4, 11)
        ),
    )
    monkeypatch.setattr(
        orch, "_load_scraper_results", lambda name: calls.append(("load", name))
    )

    orch.run_scrapers(
        scrape_bills=False,
        scrape_motions=True,
        scrape_leyes=False,
        scrape_others=False,
        leg_period="2021-2026",
    )

    assert calls == [
        ("range", orchestrator_module.RawMotion),
        ("pending", orchestrator_module.RawMotion, orchestrator_module.Motion),
        ("load", "motions.py"),
    ]
    assert orch.scraper_results["motions.py"] == _stats(1, 4, 18)


def test_leyes_only_scrape_new_ids(monkeypatch):
    calls = []
    orch = OpenPeruOrchestrator.__new__(OpenPeruOrchestrator)

    monkeypatch.setattr(orchestrator_module, "log_manager", DummyLogManager())
    monkeypatch.setattr(
        "backend.scrapers.leyes.RawLeyesScraper",
        DummyLeyScraper,
    )
    monkeypatch.setattr(
        orch,
        "_scrape_range",
        lambda **kwargs: (
            calls.append(("range", kwargs["raw_model"])) or _stats(1, 2, 13)
        ),
    )
    monkeypatch.setattr(
        orch,
        "_scrape_pending_daily",
        lambda **kwargs: calls.append(("pending", kwargs["raw_model"])),
    )
    monkeypatch.setattr(
        orch, "_load_scraper_results", lambda name: calls.append(("load", name))
    )

    orch.run_scrapers(
        scrape_bills=False,
        scrape_motions=False,
        scrape_leyes=True,
        scrape_others=False,
    )

    assert calls == [
        ("range", orchestrator_module.RawLey),
        ("load", "leyes.py"),
    ]
    assert orch.scraper_results["leyes.py"] == _stats(1, 2, 13)


def test_scrape_range_starts_after_matching_raw_model(monkeypatch, engine, session):
    session.add(
        RawBill(
            id="2021_100",
            timestamp=datetime(2026, 1, 1),
            last_update=True,
            changed=True,
            processed=False,
        )
    )
    session.add(
        RawMotion(
            id="2021_5",
            timestamp=datetime(2026, 1, 1),
            last_update=True,
            changed=True,
            processed=False,
        )
    )
    session.commit()

    calls = []
    scraper = SimpleNamespace(raw_motions=[])
    orch = OpenPeruOrchestrator(engine=engine)

    def scrape_motion(year, number):
        calls.append((year, number))
        scraper.raw_motions.append(object())

    def load_raw_motions():
        scraper.raw_motions.clear()

    monkeypatch.setattr(orchestrator_module, "get_last_id", lambda entity_name: 7)

    stats = orch._scrape_range(
        scraper=scraper,
        raw_model=RawMotion,
        scrape_fn=scrape_motion,
        buffer_attr="raw_motions",
        load_fn=load_raw_motions,
        flush_every=100,
        entity_name="Motions",
    )

    assert calls == [("2021", "6"), ("2021", "7")]
    assert stats.scrapped == 2


def test_scrape_range_uses_plain_ley_numbers(monkeypatch, engine, session):
    session.add(
        RawLey(
            id=32558,
            data="<root />",
            timestamp=datetime(2026, 1, 1),
            last_update=True,
            changed=True,
            processed=False,
        )
    )
    session.commit()

    calls = []
    scraper = SimpleNamespace(raw_leyes=[])
    orch = OpenPeruOrchestrator(engine=engine)

    def scrape_ley(number):
        calls.append(number)
        scraper.raw_leyes.append(object())

    def load_raw_leyes():
        scraper.raw_leyes.clear()

    monkeypatch.setattr(orchestrator_module, "get_last_id", lambda entity_name: 32560)

    stats = orch._scrape_range(
        scraper=scraper,
        raw_model=RawLey,
        scrape_fn=scrape_ley,
        buffer_attr="raw_leyes",
        load_fn=load_raw_leyes,
        flush_every=100,
        entity_name="Leyes",
    )

    assert calls == [32559, 32560]
    assert stats.scrapped == 2


def test_document_s3_workflow_uploads_backlog_before_scraping_and_new_after(
    monkeypatch,
):
    calls = []
    old_bill = SimpleNamespace(
        bill_id="B-old",
        step_id="1",
        file_id="10",
    )
    new_bill = SimpleNamespace(
        bill_id="B-new",
        step_id="2",
        file_id="20",
    )
    old_motion = SimpleNamespace(
        motion_id="M-old",
        step_id="3",
        file_id="30",
    )
    new_motion = SimpleNamespace(
        motion_id="M-new",
        step_id="4",
        file_id="40",
    )

    class FakeBillDocumentScraper:
        def __init__(self):
            self.documents = []
            self.pending_reads = 0

        def get_docs_pending_s3_upload(self):
            self.pending_reads += 1
            calls.append(("bill_pending", self.pending_reads))
            return [old_bill] if self.pending_reads == 1 else [old_bill, new_bill]

        def get_bills_pending_documents(self):
            calls.append(("bill_ids",))
            return ["B-new"]

        def get_bill_documents(self, *, bill_id, update, download_local):
            calls.append(("bill_scrape", bill_id, update, download_local))
            self.documents.append(new_bill)

        def load_raw_documents(self):
            calls.append(("bill_load",))
            self.documents = []

    class FakeMotionDocumentScraper:
        def __init__(self):
            self.documents = []
            self.pending_reads = 0

        def get_docs_pending_s3_upload(self):
            self.pending_reads += 1
            calls.append(("motion_pending", self.pending_reads))
            return [old_motion] if self.pending_reads == 1 else [old_motion, new_motion]

        def get_motions_pending_documents(self):
            calls.append(("motion_ids",))
            return ["M-new"]

        def get_motion_documents(self, *, motion_id, update, download_local):
            calls.append(("motion_scrape", motion_id, update, download_local))
            self.documents.append(new_motion)

        def load_raw_documents(self):
            calls.append(("motion_load",))
            self.documents = []

    monkeypatch.setattr(
        "backend.scrapers.bills_documents.RawBillDocumentScraper",
        FakeBillDocumentScraper,
    )
    monkeypatch.setattr(
        "backend.scrapers.motions_documents.RawMotionDocumentScraper",
        FakeMotionDocumentScraper,
    )

    orch = OpenPeruOrchestrator.__new__(OpenPeruOrchestrator)

    def fake_upload_documents(
        *,
        scraper,
        documents,
        document_kind,
        phase,
    ):
        del scraper
        entity_attr = "bill_id" if document_kind == "bill" else "motion_id"
        calls.append(
            (
                "upload",
                document_kind,
                phase,
                [getattr(document, entity_attr) for document in documents],
            )
        )

    monkeypatch.setattr(orch, "_upload_documents", fake_upload_documents)

    bill_stats, motion_stats = orch._scrape_pending_documents(upload_s3=True)

    assert calls == [
        ("bill_pending", 1),
        ("motion_pending", 1),
        ("upload", "bill", "backlog", ["B-old"]),
        ("upload", "motion", "backlog", ["M-old"]),
        ("bill_ids",),
        ("bill_scrape", "B-new", False, False),
        ("bill_load",),
        ("motion_ids",),
        ("motion_scrape", "M-new", False, False),
        ("motion_load",),
        ("bill_pending", 2),
        ("motion_pending", 2),
        ("upload", "bill", "new-document", ["B-new"]),
        ("upload", "motion", "new-document", ["M-new"]),
    ]
    assert bill_stats.scrapped == 1
    assert motion_stats.scrapped == 1


def test_upload_documents_continues_after_failures():
    calls = []
    documents = [
        SimpleNamespace(step_id="1", file_id="10"),
        SimpleNamespace(step_id="2", file_id="20"),
        SimpleNamespace(step_id="3", file_id="30"),
    ]

    class FakeScraper:
        def upload_s3(self, document):
            calls.append(document.file_id)
            if document.file_id == "10":
                return False
            if document.file_id == "20":
                raise RuntimeError("upload failed")
            return True

    orch = OpenPeruOrchestrator.__new__(OpenPeruOrchestrator)
    stats = orch._upload_documents(
        scraper=FakeScraper(),
        documents=documents,
        document_kind="bill",
        phase="backlog",
    )

    assert set(calls) == {"10", "20", "30"}
    assert stats.total == 3
    assert stats.succeeded == 1
    assert stats.failed == 2


# ---------- Phase B1: 2026-2031 chamber scraper dispatch ----------


class DummyChamberScraper:
    """Tracks instantiation only -- used for all 4 reference scraper
    classes, since with _recent_raw_exists always True (below) none of
    their methods actually get called."""

    instances: list["DummyChamberScraper"] = []

    def __init__(self):
        DummyChamberScraper.instances.append(self)


def test_run_scrapers_legacy_leg_period_skips_chamber_scrapers(monkeypatch):
    """Regression: leg_period="2021-2026" (or any value other than None/
    "2026-2031") must not touch the new chamber-scraper classes at all."""
    DummyChamberScraper.instances = []
    orch = OpenPeruOrchestrator.__new__(OpenPeruOrchestrator)

    monkeypatch.setattr(orchestrator_module, "log_manager", DummyLogManager())
    monkeypatch.setattr(orch, "_recent_raw_exists", lambda *a, **k: True)
    monkeypatch.setattr(orch, "_load_scraper_results", lambda name: None)
    for mod, name in [
        ("backend.scrapers.congresistas", "RawCongresistasScraper"),
        ("backend.scrapers.bancadas", "RawBancadaScraper"),
        ("backend.scrapers.committees", "RawCommitteeScraper"),
        ("backend.scrapers.organizations", "RawOrganizationScraper"),
    ]:
        monkeypatch.setattr(f"{mod}.{name}", DummyChamberScraper)

    orch.run_scrapers(
        scrape_bills=False,
        scrape_motions=False,
        scrape_leyes=False,
        scrape_others=True,
        leg_period="2021-2026",
    )

    assert DummyChamberScraper.instances == []


def test_run_scrapers_default_leg_period_invokes_chamber_scrapers(monkeypatch):
    """leg_period=None (default) must run the 2026-2031 chamber scrapers
    IN ADDITION TO the legacy scrape -- not instead of it."""
    DummyChamberScraper.instances = []
    orch = OpenPeruOrchestrator.__new__(OpenPeruOrchestrator)

    monkeypatch.setattr(orchestrator_module, "log_manager", DummyLogManager())
    monkeypatch.setattr(orch, "_recent_raw_exists", lambda *a, **k: True)
    monkeypatch.setattr(orch, "_load_scraper_results", lambda name: None)
    for mod, name in [
        ("backend.scrapers.congresistas", "RawCongresistasScraper"),
        ("backend.scrapers.bancadas", "RawBancadaScraper"),
        ("backend.scrapers.committees", "RawCommitteeScraper"),
        ("backend.scrapers.organizations", "RawOrganizationScraper"),
    ]:
        monkeypatch.setattr(f"{mod}.{name}", DummyChamberScraper)

    orch.run_scrapers(
        scrape_bills=False,
        scrape_motions=False,
        scrape_leyes=False,
        scrape_others=True,
        leg_period=None,
    )

    # One instance each for congresistas/bancadas/committees/organizations,
    # created unconditionally at the top of the new chamber block (legacy
    # instantiation is skipped since _recent_raw_exists always returns True).
    assert len(DummyChamberScraper.instances) == 4


def test_run_scrapers_2026_2031_leg_period_invokes_chamber_scrapers(monkeypatch):
    DummyChamberScraper.instances = []
    orch = OpenPeruOrchestrator.__new__(OpenPeruOrchestrator)

    monkeypatch.setattr(orchestrator_module, "log_manager", DummyLogManager())
    monkeypatch.setattr(orch, "_recent_raw_exists", lambda *a, **k: True)
    monkeypatch.setattr(orch, "_load_scraper_results", lambda name: None)
    for mod, name in [
        ("backend.scrapers.congresistas", "RawCongresistasScraper"),
        ("backend.scrapers.bancadas", "RawBancadaScraper"),
        ("backend.scrapers.committees", "RawCommitteeScraper"),
        ("backend.scrapers.organizations", "RawOrganizationScraper"),
    ]:
        monkeypatch.setattr(f"{mod}.{name}", DummyChamberScraper)

    orch.run_scrapers(
        scrape_bills=False,
        scrape_motions=False,
        scrape_leyes=False,
        scrape_others=True,
        leg_period="2026-2031",
    )

    assert len(DummyChamberScraper.instances) == 4


def test_run_scrapers_default_leg_period_skips_legacy_reference_scrape(monkeypatch):
    """Behavior change: leg_period=None (default) must NOT enter the LEGACY
    congresistas/bancadas/committees/organizations block at all anymore --
    that reference data is now historical/stable and opt-in only. The 3
    tests above only assert on scraper *instantiation*, which stays zero
    either way once _recent_raw_exists is mocked True (both blocks' "skip"
    branches short-circuit before ever instantiating anything) -- so they
    can't tell "outer gate skipped the block" apart from "block ran and its
    inner check said skip". This test distinguishes the two via the
    legacy block's own log message, which is only ever emitted from
    inside it."""
    orch = OpenPeruOrchestrator.__new__(OpenPeruOrchestrator)
    log_mgr = RecordingLogManager()

    monkeypatch.setattr(orchestrator_module, "log_manager", log_mgr)
    monkeypatch.setattr(orch, "_recent_raw_exists", lambda *a, **k: True)
    monkeypatch.setattr(orch, "_load_scraper_results", lambda name: None)
    for mod, name in [
        ("backend.scrapers.congresistas", "RawCongresistasScraper"),
        ("backend.scrapers.bancadas", "RawBancadaScraper"),
        ("backend.scrapers.committees", "RawCommitteeScraper"),
        ("backend.scrapers.organizations", "RawOrganizationScraper"),
    ]:
        monkeypatch.setattr(f"{mod}.{name}", DummyChamberScraper)

    orch.run_scrapers(
        scrape_bills=False,
        scrape_motions=False,
        scrape_leyes=False,
        scrape_others=True,
        leg_period=None,
    )

    # Legacy-only message (no chamber name prefix) must never appear.
    assert "Skipping congresistas scrape: latest raw scrape is within 1 day" not in (
        log_mgr.messages
    )
    # Current-period chamber block must still be entered.
    assert any("Starting 2026-2031 congresistas scraper" in m for m in log_mgr.messages)


def test_run_scrapers_legacy_leg_period_runs_legacy_reference_scrape(monkeypatch):
    """The flip side of the test above: an explicit non-current leg_period
    (e.g. "2021-2026") is the opt-in that must actually enter the LEGACY
    block, while skipping the current-period chamber block entirely."""
    orch = OpenPeruOrchestrator.__new__(OpenPeruOrchestrator)
    log_mgr = RecordingLogManager()

    monkeypatch.setattr(orchestrator_module, "log_manager", log_mgr)
    monkeypatch.setattr(orch, "_recent_raw_exists", lambda *a, **k: True)
    monkeypatch.setattr(orch, "_load_scraper_results", lambda name: None)
    for mod, name in [
        ("backend.scrapers.congresistas", "RawCongresistasScraper"),
        ("backend.scrapers.bancadas", "RawBancadaScraper"),
        ("backend.scrapers.committees", "RawCommitteeScraper"),
        ("backend.scrapers.organizations", "RawOrganizationScraper"),
    ]:
        monkeypatch.setattr(f"{mod}.{name}", DummyChamberScraper)

    orch.run_scrapers(
        scrape_bills=False,
        scrape_motions=False,
        scrape_leyes=False,
        scrape_others=True,
        leg_period="2021-2026",
    )

    assert "Skipping congresistas scrape: latest raw scrape is within 1 day" in (
        log_mgr.messages
    )
    assert not any(
        "Starting 2026-2031 congresistas scraper" in m for m in log_mgr.messages
    )


def test_run_scrapers_legacy_leg_period_still_runs_bills_motions_legacy_scrape(
    monkeypatch,
):
    """Regression for the deliberate asymmetry: unlike scrape_others above,
    bills/motions' legacy scrape must run regardless of leg_period -- old
    bills/motions can still gain new documents/votes/status."""
    calls = []
    orch = OpenPeruOrchestrator.__new__(OpenPeruOrchestrator)

    monkeypatch.setattr(orchestrator_module, "log_manager", DummyLogManager())
    monkeypatch.setattr("backend.scrapers.bills.RawBillScraper", DummyBillScraper)
    monkeypatch.setattr("backend.scrapers.motions.RawMotionScraper", DummyMotionScraper)
    monkeypatch.setattr(
        orch,
        "_scrape_range",
        lambda **kwargs: (
            calls.append(("_scrape_range", kwargs["entity_name"])) or _stats(1, 2, 0)
        ),
    )
    monkeypatch.setattr(
        orch,
        "_scrape_pending_daily",
        lambda **kwargs: (
            calls.append(("_scrape_pending_daily", kwargs["entity_name"]))
            or _stats(1, 2, 0)
        ),
    )
    monkeypatch.setattr(orch, "_scrape_chamber_range", lambda **kwargs: _stats(1, 2, 0))
    monkeypatch.setattr(orch, "_load_scraper_results", lambda name: None)

    orch.run_scrapers(
        scrape_bills=True,
        scrape_motions=True,
        scrape_leyes=False,
        scrape_others=False,
        leg_period="2021-2026",
    )

    assert ("_scrape_range", "Bills") in calls
    assert ("_scrape_pending_daily", "Bills") in calls
    assert ("_scrape_range", "Motions") in calls
    assert ("_scrape_pending_daily", "Motions") in calls


def test_recent_raw_exists_is_chamber_scoped(engine, session):
    """Regression: a recent Senado scrape must not suppress the very next
    Diputados scrape (or vice versa) for `days`."""
    from backend.database.raw_models import RawCongresista

    session.add(
        RawCongresista(
            timestamp=datetime.now(),
            leg_period="Parlamentario 2026 - 2031",
            chamber="Senadores",
            website="https://senado.congreso.gob.pe/senador/a/",
            profile_content="<html></html>",
        )
    )
    session.commit()

    orch = OpenPeruOrchestrator.__new__(OpenPeruOrchestrator)
    orch.DBSession = lambda: session

    assert orch._recent_raw_exists(RawCongresista, days=1, chamber="Senadores") is True
    assert orch._recent_raw_exists(RawCongresista, days=1, chamber="Diputados") is False
    assert orch._recent_raw_exists(RawCongresista, days=1, chamber=None) is False
    # Default ("_ANY_") preserves the original table-wide behavior.
    assert orch._recent_raw_exists(RawCongresista, days=1) is True


# ---------- Phase B2: bills/motions bicameral scraping ----------


def test_get_last_id_scraped_legacy_only_unaffected(engine, session):
    """Regression: only legacy ids present, id_suffix=None -> byte-identical
    to pre-Phase-B2 behavior."""
    session.add(
        RawBill(
            id="2021_100",
            timestamp=datetime(2026, 1, 1),
            last_update=True,
            changed=True,
            processed=False,
        )
    )
    session.add(
        RawBill(
            id="2021_50",
            timestamp=datetime(2026, 1, 1),
            last_update=True,
            changed=True,
            processed=False,
        )
    )
    session.commit()

    orch = OpenPeruOrchestrator(engine=engine)
    assert orch._get_last_id_scraped(RawBill) == 100


def test_get_last_id_scraped_mixed_table_no_crash(engine, session):
    """CRITICAL: mixed legacy + new-format ids must not crash and must
    scope the legacy max to legacy-format ids only."""
    session.add(
        RawBill(
            id="2021_100",
            timestamp=datetime(2026, 1, 1),
            last_update=True,
            changed=True,
            processed=False,
        )
    )
    session.add(
        RawBill(
            id="00006-2026-2031-S",
            timestamp=datetime(2026, 1, 1),
            last_update=True,
            changed=True,
            processed=False,
        )
    )
    session.commit()

    orch = OpenPeruOrchestrator(engine=engine)
    # No IndexError, legacy-only max still 100 (unaffected by the new row).
    assert orch._get_last_id_scraped(RawBill) == 100


def test_get_last_id_scraped_chamber_scoped(engine, session):
    for bill_id in ("00006-2026-2031-S", "00003-2026-2031-S", "00102-2026-2031-CD"):
        session.add(
            RawBill(
                id=bill_id,
                timestamp=datetime(2026, 1, 1),
                last_update=True,
                changed=True,
                processed=False,
            )
        )
    session.add(
        RawBill(
            id="2021_9999",
            timestamp=datetime(2026, 1, 1),
            last_update=True,
            changed=True,
            processed=False,
        )
    )
    session.commit()

    orch = OpenPeruOrchestrator(engine=engine)
    assert orch._get_last_id_scraped(RawBill, id_suffix="S") == 6
    assert orch._get_last_id_scraped(RawBill, id_suffix="CD") == 102


def test_get_last_id_scraped_chamber_scoped_no_match_returns_zero(engine, session):
    session.add(
        RawBill(
            id="2021_100",
            timestamp=datetime(2026, 1, 1),
            last_update=True,
            changed=True,
            processed=False,
        )
    )
    session.commit()

    orch = OpenPeruOrchestrator(engine=engine)
    assert orch._get_last_id_scraped(RawBill, id_suffix="S") == 0


def test_scrape_chamber_range_dispatches_per_number_with_chamber(
    monkeypatch, engine, session
):
    calls = []
    scraper = SimpleNamespace(raw_bills=[])
    orch = OpenPeruOrchestrator(engine=engine)

    def scrape_chamber_bill(chamber, number):
        calls.append((chamber, number))
        scraper.raw_bills.append(object())

    def load_raw_bills():
        scraper.raw_bills.clear()

    monkeypatch.setattr(
        orchestrator_module,
        "get_last_id",
        lambda entity_name, per_par_id=None, cod_tipo_parl=None: 3,
    )
    sleep_calls = []
    monkeypatch.setattr(
        orchestrator_module.time, "sleep", lambda s: sleep_calls.append(s)
    )

    stats = orch._scrape_chamber_range(
        scraper=scraper,
        raw_model=RawBill,
        scrape_fn=scrape_chamber_bill,
        buffer_attr="raw_bills",
        load_fn=load_raw_bills,
        chamber="Senadores",
        flush_every=100,
        entity_name="Bills",
    )

    assert calls == [("Senadores", 1), ("Senadores", 2), ("Senadores", 3)]
    assert stats.scrapped == 3


def test_scrape_chamber_range_throttles_every_10_items(monkeypatch, engine, session):
    scraper = SimpleNamespace(raw_bills=[])
    orch = OpenPeruOrchestrator(engine=engine)

    def scrape_chamber_bill(chamber, number):
        scraper.raw_bills.append(object())

    def load_raw_bills():
        scraper.raw_bills.clear()

    monkeypatch.setattr(
        orchestrator_module,
        "get_last_id",
        lambda entity_name, per_par_id=None, cod_tipo_parl=None: 25,
    )
    sleep_calls = []
    monkeypatch.setattr(
        orchestrator_module.time, "sleep", lambda s: sleep_calls.append(s)
    )

    orch._scrape_chamber_range(
        scraper=scraper,
        raw_model=RawBill,
        scrape_fn=scrape_chamber_bill,
        buffer_attr="raw_bills",
        load_fn=load_raw_bills,
        chamber="Senadores",
        flush_every=100,
        entity_name="Bills",
    )

    # 25 items -> idx 10 and idx 20 cross the boundary -> 2 sleep calls.
    assert sleep_calls == [2, 2]


def test_scrape_pending_daily_legacy_id_unaffected_when_chamber_fn_omitted(
    monkeypatch, engine, session
):
    """Regression: legacy-format pending id, chamber_scrape_fn omitted ->
    byte-identical to pre-Phase-B2 dispatch."""
    calls = []
    scraper = SimpleNamespace(raw_bills=[])
    orch = OpenPeruOrchestrator(engine=engine)

    monkeypatch.setattr(
        orch, "_get_ids_to_update", lambda raw_model, model, max_age_days: ["2021_100"]
    )

    def scrape_bill(year, number):
        calls.append((year, number))
        scraper.raw_bills.append(object())

    def load_raw_bills():
        scraper.raw_bills.clear()

    stats = orch._scrape_pending_daily(
        raw_model=RawBill,
        model=orchestrator_module.Bill,
        scraper=scraper,
        scrape_fn=scrape_bill,
        buffer_attr="raw_bills",
        load_fn=load_raw_bills,
        entity_name="Bills",
    )

    assert calls == [("2021", "100")]
    assert stats.scrapped == 1


def test_scrape_pending_daily_dispatches_new_format_id_to_chamber_fn(
    monkeypatch, engine, session
):
    calls = []
    scraper = SimpleNamespace(raw_bills=[])
    orch = OpenPeruOrchestrator(engine=engine)

    monkeypatch.setattr(
        orch,
        "_get_ids_to_update",
        lambda raw_model, model, max_age_days: ["00006-2026-2031-S"],
    )

    def scrape_bill(year, number):
        calls.append(("legacy", year, number))

    def scrape_chamber_bill(chamber, number):
        calls.append(("chamber", chamber, number))
        scraper.raw_bills.append(object())

    def load_raw_bills():
        scraper.raw_bills.clear()

    orch._scrape_pending_daily(
        raw_model=RawBill,
        model=orchestrator_module.Bill,
        scraper=scraper,
        scrape_fn=scrape_bill,
        buffer_attr="raw_bills",
        load_fn=load_raw_bills,
        entity_name="Bills",
        chamber_scrape_fn=scrape_chamber_bill,
    )

    assert calls == [("chamber", "Senadores", 6)]


def test_scrape_pending_daily_new_format_id_no_chamber_fn_skips_without_crash(
    monkeypatch, engine, session
):
    """Defensive branch found in eng review's test-diagram trace."""
    scraper = SimpleNamespace(raw_bills=[])
    orch = OpenPeruOrchestrator(engine=engine)

    monkeypatch.setattr(
        orch,
        "_get_ids_to_update",
        lambda raw_model, model, max_age_days: ["00006-2026-2031-S"],
    )

    def scrape_bill(year, number):
        raise AssertionError(
            "legacy scrape_fn should not be called for a new-format id"
        )

    def load_raw_bills():
        scraper.raw_bills.clear()

    stats = orch._scrape_pending_daily(
        raw_model=RawBill,
        model=orchestrator_module.Bill,
        scraper=scraper,
        scrape_fn=scrape_bill,
        buffer_attr="raw_bills",
        load_fn=load_raw_bills,
        entity_name="Bills",
        chamber_scrape_fn=None,
    )

    assert stats.scrapped == 0


def test_run_scrapers_default_leg_period_invokes_bills_motions_chamber_blocks(
    monkeypatch,
):
    calls = []
    orch = OpenPeruOrchestrator.__new__(OpenPeruOrchestrator)

    monkeypatch.setattr(orchestrator_module, "log_manager", DummyLogManager())
    monkeypatch.setattr("backend.scrapers.bills.RawBillScraper", DummyBillScraper)
    monkeypatch.setattr("backend.scrapers.motions.RawMotionScraper", DummyMotionScraper)
    monkeypatch.setattr(orch, "_scrape_range", lambda **kwargs: _stats(1, 2, 0))
    monkeypatch.setattr(orch, "_scrape_pending_daily", lambda **kwargs: _stats(1, 2, 0))
    monkeypatch.setattr(
        orch,
        "_scrape_chamber_range",
        lambda **kwargs: (
            calls.append((kwargs["entity_name"], kwargs["chamber"])) or _stats(1, 2, 0)
        ),
    )
    monkeypatch.setattr(orch, "_load_scraper_results", lambda name: None)

    orch.run_scrapers(
        scrape_bills=True,
        scrape_motions=True,
        scrape_leyes=False,
        scrape_others=False,
        leg_period=None,
    )

    assert set(calls) == {
        ("Bills", "Senadores"),
        ("Bills", "Diputados"),
        ("Motions", "Senadores"),
        ("Motions", "Diputados"),
    }
    assert "bills_chamber_senadores.py" in orch.scraper_results
    assert "bills_chamber_diputados.py" in orch.scraper_results
    assert "motions_chamber_senadores.py" in orch.scraper_results
    assert "motions_chamber_diputados.py" in orch.scraper_results
    # Per-chamber stats stay separate, not combined into one entry.
    assert "bills_chamber.py" not in orch.scraper_results


def test_run_scrapers_legacy_leg_period_skips_bills_motions_chamber_blocks(
    monkeypatch,
):
    calls = []
    orch = OpenPeruOrchestrator.__new__(OpenPeruOrchestrator)

    monkeypatch.setattr(orchestrator_module, "log_manager", DummyLogManager())
    monkeypatch.setattr("backend.scrapers.bills.RawBillScraper", DummyBillScraper)
    monkeypatch.setattr("backend.scrapers.motions.RawMotionScraper", DummyMotionScraper)
    monkeypatch.setattr(orch, "_scrape_range", lambda **kwargs: _stats(1, 2, 0))
    monkeypatch.setattr(orch, "_scrape_pending_daily", lambda **kwargs: _stats(1, 2, 0))
    monkeypatch.setattr(
        orch,
        "_scrape_chamber_range",
        lambda **kwargs: calls.append(kwargs) or _stats(1, 2, 0),
    )
    monkeypatch.setattr(orch, "_load_scraper_results", lambda name: None)

    orch.run_scrapers(
        scrape_bills=True,
        scrape_motions=True,
        scrape_leyes=False,
        scrape_others=False,
        leg_period="2021-2026",
    )

    assert calls == []
    assert "bills_chamber_senadores.py" not in orch.scraper_results
    assert "motions_chamber_senadores.py" not in orch.scraper_results


def test_run_scrapers_default_leg_period_invokes_joint_committees(monkeypatch):
    """The committees_chamber stage must also scrape joint/bicameral
    committees (chamber="Congreso"), gated independently from the two
    per-chamber calls -- mirrors organizations_chamber's
    get_joint_comision_permanente wiring."""
    calls = []

    class DummyCommitteeScraper:
        committee_list = [object()]

        def get_chamber_committees(self, chamber):
            calls.append(("get_chamber_committees", chamber))
            return self.committee_list

        def get_joint_committees(self):
            calls.append(("get_joint_committees",))
            return self.committee_list

        def add_committees_to_db(self):
            pass

    orch = OpenPeruOrchestrator.__new__(OpenPeruOrchestrator)
    monkeypatch.setattr(orchestrator_module, "log_manager", DummyLogManager())
    monkeypatch.setattr(
        "backend.scrapers.committees.RawCommitteeScraper", DummyCommitteeScraper
    )
    for mod, name in [
        ("backend.scrapers.congresistas", "RawCongresistasScraper"),
        ("backend.scrapers.bancadas", "RawBancadaScraper"),
        ("backend.scrapers.organizations", "RawOrganizationScraper"),
    ]:
        monkeypatch.setattr(f"{mod}.{name}", DummyChamberScraper)
    # Only the committees stage should actually run its calls -- everything
    # else reports "recently scraped" so DummyChamberScraper's lack of real
    # methods (get_chamber_roster etc.) never gets exercised.
    monkeypatch.setattr(
        orch,
        "_recent_raw_exists",
        lambda raw_model, *a, **k: raw_model is not orchestrator_module.RawCommittee,
    )
    monkeypatch.setattr(orch, "_load_scraper_results", lambda name: None)

    orch.run_scrapers(
        scrape_bills=False,
        scrape_motions=False,
        scrape_leyes=False,
        scrape_others=True,
        leg_period=None,
    )

    assert ("get_chamber_committees", "Senadores") in calls
    assert ("get_chamber_committees", "Diputados") in calls
    assert ("get_joint_committees",) in calls


def test_run_scrapers_skips_joint_committees_when_recent(monkeypatch):
    calls = []

    class DummyCommitteeScraper:
        committee_list = [object()]

        def get_chamber_committees(self, chamber):
            return self.committee_list

        def get_joint_committees(self):
            calls.append("get_joint_committees")
            return self.committee_list

        def add_committees_to_db(self):
            pass

    orch = OpenPeruOrchestrator.__new__(OpenPeruOrchestrator)
    monkeypatch.setattr(orchestrator_module, "log_manager", DummyLogManager())
    monkeypatch.setattr(
        "backend.scrapers.committees.RawCommitteeScraper", DummyCommitteeScraper
    )
    for mod, name in [
        ("backend.scrapers.congresistas", "RawCongresistasScraper"),
        ("backend.scrapers.bancadas", "RawBancadaScraper"),
        ("backend.scrapers.organizations", "RawOrganizationScraper"),
    ]:
        monkeypatch.setattr(f"{mod}.{name}", DummyChamberScraper)
    monkeypatch.setattr(orch, "_recent_raw_exists", lambda *a, **k: True)
    monkeypatch.setattr(orch, "_load_scraper_results", lambda name: None)

    orch.run_scrapers(
        scrape_bills=False,
        scrape_motions=False,
        scrape_leyes=False,
        scrape_others=True,
        leg_period=None,
    )

    assert calls == []
