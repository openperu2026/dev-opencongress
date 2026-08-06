import json
from datetime import date, datetime

import pytest

from backend import Proponents, TypeBillStep
from backend.database import models as db_models
from backend.database.raw_models import RawBillDocument, RawBillPage
from backend.database.crud import pipeline_votes as crud_votes
from backend.process.votes import extract


MODEL = "gpt-5.6-luna"


def _add_bill_with_vote_document(session, *, bill_id: str, step_id: int, file_id: int):
    session.add(
        db_models.Bill(
            id=bill_id,
            title="t",
            summary_congreso="r",
            observations="",
            status="Aprobado",
            proponent=Proponents.CONGRESO,
            author_id=None,
            bill_approved=True,
            summary_oc="",
            pley_id=f"{bill_id}-pley",
        )
    )
    session.add(
        db_models.BillStep(
            bill_id=bill_id,
            step_id=step_id,
            step_type=TypeBillStep.VOTACION,
            vote_step=True,
            vote_event_id=f"{bill_id}_{step_id}",
            step_date=date(2023, 5, 11),
            step_detail="Votación",
        )
    )
    session.add(
        RawBillDocument(
            bill_id=bill_id,
            step_id=step_id,
            file_id=file_id,
            step_date=datetime(2023, 5, 11),
            url="https://x/doc.pdf",
            timestamp=datetime.now(),
            last_update=True,
            changed=False,
            processed=False,
        )
    )


def test_increment_usage_ledger_accumulates(session):
    assert crud_votes.get_total_cost_usd(session, MODEL) == 0.0

    crud_votes.increment_usage_ledger(session, model=MODEL, cost_usd=0.02)
    crud_votes.increment_usage_ledger(session, model=MODEL, cost_usd=0.03)

    assert crud_votes.get_total_cost_usd(session, MODEL) == pytest.approx(0.05)

    # None/zero cost is a no-op, doesn't error or change the total.
    crud_votes.increment_usage_ledger(session, model=MODEL, cost_usd=None)
    crud_votes.increment_usage_ledger(session, model=MODEL, cost_usd=0.0)
    assert crud_votes.get_total_cost_usd(session, MODEL) == pytest.approx(0.05)


def test_run_sync_extraction_stops_before_next_document_over_budget(
    session, monkeypatch
):
    _add_bill_with_vote_document(session, bill_id="B_budget_1", step_id=1, file_id=1)
    session.flush()

    # Budget already exhausted from prior runs.
    crud_votes.increment_usage_ledger(session, model=MODEL, cost_usd=10.0)
    session.commit()

    def _boom(*args, **kwargs):
        raise AssertionError("OpenAI client should never be called once over budget")

    monkeypatch.setattr(extract.client_mod, "get_client", lambda: _boom)
    monkeypatch.setattr(extract.fetch, "download_pdf_bytes", _boom)

    stats = extract.run_sync_extraction(
        session, kind="bill", model=MODEL, max_cost_usd=5.0
    )

    assert stats.processed == 0
    assert stats.errors == 0

    doc = session.get(RawBillDocument, ("B_budget_1", 1, 1))
    assert doc.processed is False  # never attempted, so never marked


def _seed_historical_cost(session, *, bill_id, step_id, file_id, cost_usd):
    session.add(
        RawBillPage(
            bill_id=bill_id,
            step_id=step_id,
            file_id=file_id,
            page_num=0,
            ocr_model=MODEL,
            text=json.dumps(
                {
                    "custom_id": f"bill::{bill_id}::{step_id}::{file_id}",
                    "model": MODEL,
                    "parsed": {"match_found": True},
                    "raw": "{}",
                    "input_tokens": 100,
                    "output_tokens": 50,
                    "cached_tokens": 0,
                    "cache_write_tokens": 0,
                    "cost_usd": cost_usd,
                    "error": None,
                }
            ),
            timestamp=datetime.now(),
            last_update=True,
            changed=False,
            processed=True,
        )
    )


def test_get_average_cost_per_document(session):
    assert crud_votes.get_average_cost_per_document(session, model=MODEL) is None

    _seed_historical_cost(
        session, bill_id="B_hist_1", step_id=1, file_id=1, cost_usd=0.01
    )
    _seed_historical_cost(
        session, bill_id="B_hist_2", step_id=1, file_id=1, cost_usd=0.03
    )
    session.flush()

    avg = crud_votes.get_average_cost_per_document(session, model=MODEL)
    assert avg == pytest.approx(0.02)


def test_submit_batch_extraction_stops_queuing_over_estimated_budget(
    session, monkeypatch, tmp_path
):
    # Historical average cost per document: (0.01 + 0.03) / 2 = 0.02
    _seed_historical_cost(
        session, bill_id="B_hist_1", step_id=1, file_id=1, cost_usd=0.01
    )
    _seed_historical_cost(
        session, bill_id="B_hist_2", step_id=1, file_id=1, cost_usd=0.03
    )

    # 5 candidate documents pending extraction.
    for i in range(5):
        _add_bill_with_vote_document(
            session, bill_id=f"B_batch_{i}", step_id=10, file_id=1
        )
    session.commit()

    monkeypatch.setattr(extract.fetch, "download_pdf_bytes", lambda url: b"%PDF-fake")
    monkeypatch.setattr(
        extract.fetch, "upload_pdf", lambda client, pdf_bytes, filename: "file-123"
    )

    class _FakeBatch:
        id = "batch-fake-1"

    class _FakeClient:
        class files:
            @staticmethod
            def create(*args, **kwargs):
                return type("F", (), {"id": "uploaded-file-1"})()

        class batches:
            @staticmethod
            def create(*args, **kwargs):
                return _FakeBatch()

    monkeypatch.setattr(extract.client_mod, "get_client", lambda: _FakeClient())

    # Budget of $0.05 with a $0.02/doc estimate should allow ~2 documents,
    # leaving the rest unqueued rather than silently dropped.
    manifest = extract.submit_batch_extraction(
        session,
        kind="bill",
        model=MODEL,
        max_cost_usd=0.05,
        batch_dir=tmp_path,
    )

    assert manifest["budget_capped"] is True
    assert manifest["skipped_for_budget"] > 0
    assert len(manifest["doc_ids"]) < 5
    assert len(manifest["doc_ids"]) >= 1
