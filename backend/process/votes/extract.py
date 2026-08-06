from __future__ import annotations

import json
import time
from dataclasses import asdict
from datetime import datetime
from pathlib import Path
from typing import Literal
from zoneinfo import ZoneInfo

from loguru import logger
from sqlalchemy.orm import Session
from tqdm import tqdm

from backend.database import models as db_models
from backend.database.crud import pipeline_votes as crud_votes
from backend.database.crud.pipeline_core import ProcessStats
from backend.database.raw_models import (
    RawBillDocument,
    RawBillPage,
    RawMotionDocument,
    RawMotionPage,
)
from backend.process.votes import client as client_mod
from backend.process.votes import fetch
from backend.process.votes.client import ExtractionResult
from backend.process.votes.config import (
    BATCH_JOBS_DIR,
    DEFAULT_COST_ESTIMATE_PER_DOC,
    DEFAULT_MODEL,
)

TERMINAL_BATCH_STATUSES = {"completed", "failed", "expired", "cancelled"}


def _target_id(doc, kind: Literal["bill", "motion"]) -> str:
    return doc.bill_id if kind == "bill" else doc.motion_id


def build_doc_context(
    db: Session, doc, kind: Literal["bill", "motion"]
) -> tuple[str, str]:
    """Returns (custom_id, context_text) for one raw document."""
    target_id = _target_id(doc, kind)
    custom_id = f"{kind}::{target_id}::{doc.step_id}::{doc.file_id}"

    if kind == "bill":
        bill = db.get(db_models.Bill, target_id)
        ref_value = bill.pley_id if bill else target_id
        summary = bill.summary_congreso if bill else ""
        context_text = (
            f"Context for this extraction:\npley_id: {ref_value}\nsumilla: {summary}"
        )
    else:
        motion = db.get(db_models.Motion, target_id)
        summary = motion.summary_congreso if motion else ""
        context_text = (
            f"Context for this extraction:\nmotion_id: {target_id}\nresumen: {summary}"
        )

    return custom_id, context_text


def store_extraction_result(
    db: Session,
    doc: RawBillDocument | RawMotionDocument,
    kind: Literal["bill", "motion"],
    model: str,
    result: ExtractionResult,
) -> None:
    """
    Write the extraction result as a page_num=0 sentinel row on
    RawBillPage/RawMotionPage, and always mark the raw document processed
    (success, API error, or match_found=False) -- extraction is never
    retried automatically, so OpenAI is never billed twice for one document.
    """
    page_model = RawBillPage if kind == "bill" else RawMotionPage
    id_field = "bill_id" if kind == "bill" else "motion_id"
    target_id = _target_id(doc, kind)
    now = datetime.now(ZoneInfo("America/Lima"))

    payload = {
        id_field: target_id,
        "step_id": doc.step_id,
        "file_id": doc.file_id,
        "page_num": 0,
        "ocr_model": model,
        "text": json.dumps(asdict(result), ensure_ascii=False),
        "timestamp": now,
        "last_update": True,
        "changed": False,
        "processed": False,
    }

    existing = db.get(page_model, (target_id, doc.step_id, doc.file_id, 0, model))
    if existing is None:
        db.add(page_model(**payload))
    else:
        for key, value in payload.items():
            setattr(existing, key, value)

    crud_votes.increment_usage_ledger(
        db, model=model, cost_usd=result.cost_usd, provider="openai"
    )

    doc.processed = True
    db.commit()


def run_sync_extraction(
    db: Session,
    *,
    kind: Literal["bill", "motion"],
    model: str = DEFAULT_MODEL,
    max_pages: int | None = None,
    limit: int | None = None,
    max_cost_usd: float | None = None,
) -> ProcessStats:
    """
    max_cost_usd is a persistent, cumulative budget checked against real
    spend already recorded for `model` (across ALL prior runs, not just this
    one) -- a hard ceiling checked before each document, so a run never
    knowingly calls OpenAI for a document it can't afford.
    """
    stats = ProcessStats()
    client = client_mod.get_client()
    docs = crud_votes.find_pending_vote_documents(
        db, kind=kind, max_pages=max_pages, limit=limit
    )

    for doc in tqdm(docs, desc=f"Vote extraction ({kind}, sync)"):
        if max_cost_usd is not None:
            spent = crud_votes.get_total_cost_usd(db, model)
            if spent >= max_cost_usd:
                logger.warning(
                    f"Budget cap reached (${spent:.4f} >= ${max_cost_usd:.2f}) for "
                    f"model={model!r}; stopping after {stats.processed} documents"
                )
                break

        target_id = _target_id(doc, kind)
        try:
            pdf_bytes = fetch.download_pdf_bytes(doc.url)
            file_id = fetch.upload_pdf(
                client,
                pdf_bytes,
                filename=f"{target_id}_{doc.step_id}_{doc.file_id}.pdf",
            )
            custom_id, context_text = build_doc_context(db, doc, kind)
            body = client_mod.build_request_body(model, file_id, kind, context_text)
            resp = client.responses.create(**body)
            result = client_mod.normalize_sync_response(resp, model, custom_id)
        except Exception as exc:
            logger.exception(
                f"Vote extraction failed for {kind} id={target_id} "
                f"step_id={doc.step_id} file_id={doc.file_id}: {exc}"
            )
            doc.processed = True
            db.commit()
            stats.errors += 1
            continue

        store_extraction_result(db, doc, kind, model, result)

        if result.error is not None:
            logger.warning(
                f"Extraction API error for {kind} id={target_id} "
                f"step_id={doc.step_id} file_id={doc.file_id}: {result.error}"
            )
            stats.errors += 1
        elif result.parsed is None or not result.parsed.get("match_found", False):
            logger.warning(
                f"No match_found for {kind} id={target_id} "
                f"step_id={doc.step_id} file_id={doc.file_id}"
            )
            stats.skipped += 1
        else:
            stats.processed += 1

    return stats


def submit_batch_extraction(
    db: Session,
    *,
    kind: Literal["bill", "motion"],
    model: str = DEFAULT_MODEL,
    max_pages: int | None = None,
    limit: int | None = None,
    batch_dir: Path | None = None,
    max_cost_usd: float | None = None,
) -> dict:
    """
    Submit a Batch API job for historical backfills. Does not mark any raw
    document processed -- nothing to mark until collect_batch_extraction
    downloads the results, possibly hours later. Operator note: don't submit
    overlapping doc sets concurrently, since pending docs stay
    processed=False until collected.

    max_cost_usd is enforced as an ESTIMATE at submission time, not a real
    measurement -- true cost isn't known until the batch completes. Real
    spend already recorded for `model` (persistent, from prior runs) plus a
    per-document average drawn from that same history (DEFAULT_COST_ESTIMATE_PER_DOC
    on a cold start) projects forward as documents are queued; queuing stops
    once the projection would exceed budget.
    """
    batch_dir = batch_dir or BATCH_JOBS_DIR
    batch_dir.mkdir(parents=True, exist_ok=True)
    client = client_mod.get_client()

    docs = crud_votes.find_pending_vote_documents(
        db, kind=kind, max_pages=max_pages, limit=limit
    )

    projected_spent = 0.0
    avg_cost = 0.0
    if max_cost_usd is not None:
        projected_spent = crud_votes.get_total_cost_usd(db, model)
        avg_cost = (
            crud_votes.get_average_cost_per_document(db, model=model)
            or DEFAULT_COST_ESTIMATE_PER_DOC
        )

    lines = []
    doc_ids = []
    skipped_for_budget = 0
    for doc in docs:
        if max_cost_usd is not None and projected_spent + avg_cost > max_cost_usd:
            skipped_for_budget += 1
            continue

        target_id = _target_id(doc, kind)
        try:
            pdf_bytes = fetch.download_pdf_bytes(doc.url)
            file_id = fetch.upload_pdf(
                client,
                pdf_bytes,
                filename=f"{target_id}_{doc.step_id}_{doc.file_id}.pdf",
            )
        except Exception as exc:
            logger.exception(
                f"Skipping {kind} id={target_id} step_id={doc.step_id} "
                f"file_id={doc.file_id} from batch: {exc}"
            )
            continue

        custom_id, context_text = build_doc_context(db, doc, kind)
        body = client_mod.build_request_body(model, file_id, kind, context_text)
        lines.append(
            json.dumps(
                {
                    "custom_id": custom_id,
                    "method": "POST",
                    "url": "/v1/responses",
                    "body": body,
                }
            )
        )
        doc_ids.append(custom_id)
        if max_cost_usd is not None:
            projected_spent += avg_cost

    if skipped_for_budget:
        logger.info(
            f"Budget cap (${max_cost_usd:.2f}, ~${avg_cost:.5f}/doc estimate) reached; "
            f"queued {len(doc_ids)}/{len(docs)} documents for this batch, "
            f"{skipped_for_budget} left unqueued"
        )

    if not lines:
        return {
            "batch_id": None,
            "kind": kind,
            "model": model,
            "doc_ids": [],
            "budget_capped": skipped_for_budget > 0,
            "skipped_for_budget": skipped_for_budget,
        }

    jsonl_path = batch_dir / f"batch_{kind}_{model.replace('.', '_')}.jsonl"
    jsonl_path.write_text("\n".join(lines) + "\n", encoding="utf-8")

    uploaded = client.files.create(file=open(jsonl_path, "rb"), purpose="batch")
    batch = client.batches.create(
        input_file_id=uploaded.id,
        endpoint="/v1/responses",
        completion_window="24h",
        metadata={"description": f"votes-{kind}-{model}"},
    )

    manifest = {
        "batch_id": batch.id,
        "kind": kind,
        "model": model,
        "doc_ids": doc_ids,
        "budget_capped": skipped_for_budget > 0,
        "skipped_for_budget": skipped_for_budget,
    }
    (batch_dir / f"{batch.id}_manifest.json").write_text(
        json.dumps(manifest, indent=2), encoding="utf-8"
    )
    logger.info(
        f"Submitted vote extraction batch {batch.id} ({len(doc_ids)} documents)"
    )
    return manifest


def collect_batch_extraction(
    db: Session,
    *,
    batch_id: str,
    kind: Literal["bill", "motion"],
    model: str = DEFAULT_MODEL,
    poll_interval: int = 60,
) -> ProcessStats:
    """
    Poll a submitted batch to a terminal status, download its results, and
    store + always-mark-processed each document (same rule as sync mode).
    """
    client = client_mod.get_client()
    batch = client.batches.retrieve(batch_id)
    while batch.status not in TERMINAL_BATCH_STATUSES:
        time.sleep(poll_interval)
        batch = client.batches.retrieve(batch_id)

    stats = ProcessStats()

    if batch.error_file_id:
        err_content = client.files.content(batch.error_file_id).text
        for line in err_content.splitlines():
            if line.strip():
                logger.warning(f"[{kind}/{model}] batch-level error line: {line}")

    if not batch.output_file_id:
        return stats

    doc_model = RawBillDocument if kind == "bill" else RawMotionDocument
    content = client.files.content(batch.output_file_id).text

    for line in content.splitlines():
        if not line.strip():
            continue
        result = client_mod.normalize_batch_output_line(line, model)
        _, target_id, step_id, file_id = result.custom_id.split("::")
        doc = db.get(doc_model, (target_id, int(step_id), int(file_id)))
        if doc is None:
            logger.warning(
                f"No matching {kind} document for custom_id={result.custom_id}"
            )
            continue

        store_extraction_result(db, doc, kind, model, result)

        if result.error is not None:
            stats.errors += 1
        elif result.parsed is None or not result.parsed.get("match_found", False):
            stats.skipped += 1
        else:
            stats.processed += 1

    return stats
