"""
Batch + prompt-caching runner for the Congreso del Peru attendance/voting
extraction test.

What this does:
  1. Downloads each source PDF once and uploads it to OpenAI's Files API
     (purpose="user_data") to get a stable file_id -- reused across every
     model you test, instead of re-fetching/re-embedding the PDF per line.
  2. Writes one .jsonl batch file PER MODEL (the Batch API requires a single
     model per input file).
  3. Submits each .jsonl as its own batch job against /v1/responses.
  4. Polls until all jobs finish, downloads the output files, and parses
     results back into {model, doc_label, parsed_json, cached_tokens, ...}
     using custom_id (output line order is not guaranteed by the API).

Requirements: pip install openai requests
Env: OPENAI_API_KEY must be set.
"""

import io
import json
import time
from pathlib import Path
from backend.config import directories, settings

import requests
from openai import OpenAI

# ---------------------------------------------------------------------------
# Configuration -- edit this section
# ---------------------------------------------------------------------------

# Models under test. Must be vision-capable to get page images from the PDF,
# not just extracted text (see earlier discussion on the 3-column layout).
MODELS = [
    "gpt-5.6-luna",
]

# label -> source URL. Labels become part of custom_id, so keep them short
# and unique (e.g. the bill/document code) rather than the opaque congreso
# archive URL.
PDF_SOURCES = {
    "2021_5665": {
        "url": "https://api.congreso.gob.pe/spley-portal-service//archivo/Mzk0MTc3/pdf",
        "pley_id": "05665/2023-CR",
        "sumilla": "PROPONE MODIFICAR LA LEY 29944, LEY DE REFORMA MAGISTERIAL, PARA INCORPORAR EN SUS ALCANCES A LOS PROFESORES DE LAS INSTITUCIONES EDUCATIVAS DE EDUCACIÓN BÁSICA Y TÉCNICO-PRODUCTIVA DE LOS ESTABLECIMIENTOS PENITENCIARIOS ADSCRITOS AL MINISTERIO DE JUSTICIA Y DERECHOS HUMANOS.",
    },
    "2021_491": {
        "url": "https://wb2server.congreso.gob.pe/spley-portal-service//archivo/MTM4MDM=/pdf",
        "pley_id": "00491/2021-CR",
        "sumilla": "PROPONE MODIFICAR LA LEY 29158, LEY ORGÁNICA DEL PODER EJECUTIVO RESPECTO DE LA DESIGNACIÓN DE LOS MINISTROS DEL INTERIOR Y DE DEFENSA.",
    },
    "2021_2437": {
        "url": "https://wb2server.congreso.gob.pe/spley-portal-service//archivo/MTU5MzI5/pdf",
        "pley_id": "02437/2021-CR",
        "sumilla": "PROPONE AUTORIZAR DE MANERA EXCEPCIONAL Y POR ÚNICA VEZ EL NOMBRAMIENTO DEL PERSONAL DE SALUD ASISTENCIAL SUJETOS AL RÉGIMEN LABORAL CAS EN EL MINISTERIO DE SALUD",
    },
    "2021_7822": {
        "url": "https://wb2server.congreso.gob.pe/spley-portal-service//archivo/MjcwMDM4/pdf",
        "pley_id": "07822/2023-CR",
        "sumilla": "PROPONE CREAR E IMPLEMENTA LA UNIVERSIDAD NACIONAL TECNOLÓGICA DEL ALTO MAYO - SORITOR, COMO PERSONA JURÍDICA DE DERECHO PÚBLICO INTERNO, CON SEDE PRINCIPAL EN LA CIUDAD DE SORITOR, PROVINCIA DE MOYOBAMBA, DEPARTAMENTO DE SAN MARTÍN.",
    },
    "2021_4428": {
        "url": "https://wb2server.congreso.gob.pe/spley-portal-service//archivo/MTQzOTcz/pdf",
        "pley_id": "04428/2022-CR",
        "sumilla": "PROPONE AGREGAR EL ARTÍCULO 77-A AL REGLAMENTO DEL CONGRESO DE LA REPÚBLICA,",
    },
    "2021_2907": {
        "url": "https://wb2server.congreso.gob.pe/spley-portal-service//archivo/NjE3ODk=/pdf",
        "pley_id": "02907/2022-PE",
        "sumilla": "PRESUPUESTO DEL SECTOR PÚBLICO PARA EL AÑO FISCAL 2023.",
    },
    "2021_6015": {
        "url": "https://wb2server.congreso.gob.pe/spley-portal-service//archivo/MzM0NDY1/pdf",
        "pley_id": "06015/2023-CR",
        "sumilla": "PROPONE INCORPORAR A LOS TRABAJADORES DE LA SUPERINTENDENCIA NACIONAL DE REGISTROS PÚBLICOS (SUNARP) QUE SE ENCUENTRE BAJO EL RÉGIMEN DEL CONTRATO ADMINISTRATIVO DE SERVICIOS (CAS), AL RÉGIMEN LABORAL DEL DECRETO LEGISLATIVO 728, CON LA FINALIDAD DE UNIFORMIZAR LAS NORMAS DE APLICACIÓN PARA LAS RELACIONES LABORALES, EN APLICACIÓN DEL DERECHO CONSTITUCIONAL DE IGUALDAD.",
    },
    "2021_7174": {
        "url": "https://wb2server.congreso.gob.pe/spley-portal-service//archivo/MjQ2OTM1/pdf",
        "pley_id": "07174/2023-CR",
        "sumilla": "PROPONE INCORPORAR DEL INCISO V) AL ARTÍCULO 130° AL DECRETO LEGISLATIVO N° 1049, DECRETO LEGISLATIVO DEL NOTARIADO.",
    },
    "2021_4378": {
        "url": "https://wb2server.congreso.gob.pe/spley-portal-service//archivo/MjgxNTA0/pdf",
        "pley_id": "04378/2022-CR",
        "sumilla": "PROPONE AUTORIZAR A LOS AFILIADOS EL RETIRO DE HASTA EL 70% DE SUS FONDOS DEL SISTEMA PRIVADO DE ADMINISTRACIÓN DE FONDOS DE PENSIONES.",
    },
    "2021_1040": {
        "url": "https://wb2server.congreso.gob.pe/spley-portal-service//archivo/NDMzNTg=/pdf",
        "pley_id": "01040/2021-CR",
        "sumilla": "PROPONE MODIFICAR EL ARTICULO 10 DE LA LEY 28359, LEY DE SITUACIÓN MILITAR DE LOS OFICIALES DE LAS FUERZAS ARMADAS, MODIFICA EL DECRETO LEGISLATIVO 1143.",
    },
}

# A fixed prompt_cache_key shared by every request in this test. Because
# system_prompt.md + user_prompt.md are byte-identical on every call (no
# per-file interpolation), this string identifies one reusable prefix that
# OpenAI's cache router can key on across models and across batches.
PROMPT_CACHE_KEY = "congress-extraction-v3"

# Models that support explicit prompt_cache_breakpoint / prompt_cache_options.
# Per OpenAI's docs, models BEFORE this family actively REJECT these fields
# with a 400 error -- it's not a harmless no-op -- so this must stay an
# explicit allow-list, not a blanket default-on. Add future GPT-5.6+ models
# here as you test them.
EXPLICIT_BREAKPOINT_MODELS = {"gpt-5.6-sol", "gpt-5.6-terra", "gpt-5.6-luna"}

PROMPTS_DIR = directories.ROOT_DIR / "backend" / "process" / "votes"
SYSTEM_PROMPT = Path(PROMPTS_DIR / "system_prompt.md").read_text(encoding="utf-8")
USER_PROMPT = Path(PROMPTS_DIR / "user_prompt.md").read_text(encoding="utf-8")
EXTRACTION_SCHEMA = json.loads(
    Path(PROMPTS_DIR / "extraction_schema.json").read_text(encoding="utf-8")
)

OUT_DIR = Path(PROMPTS_DIR / "batch_jobs")
OUT_DIR.mkdir(exist_ok=True)


# ---------------------------------------------------------------------------
# Step 1: upload each PDF once, get a reusable file_id
# ---------------------------------------------------------------------------


def upload_pdfs_once(client: OpenAI, sources: dict[str, dict]) -> dict[str, dict]:
    """Download each PDF and upload with purpose=user_data.

    Returns label -> {"file_id": ..., "pley_id": ..., "sumilla": ...} so the
    per-document context travels alongside the uploaded file through to
    build_request_body.
    """
    uploaded_docs = {}
    headers = {
        # Some government APIs block/redirect requests with no browser-like
        # User-Agent (bot checks, consent walls) -- without this you can get
        # back an HTML page instead of the PDF, which uploads "successfully"
        # but fails at the model with "badly formatted or corrupted".
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
            "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
        ),
        "Accept": "application/pdf,*/*",
    }
    for label, source in sources.items():
        print(f"Downloading {label} ...")
        resp = requests.get(source["url"], headers=headers, timeout=60)
        content_type = resp.headers.get("Content-Type", "")
        pdf_bytes = resp.content

        if resp.status_code != 200 or not pdf_bytes.startswith(b"%PDF"):
            print(f"  !! {label}: NOT a valid PDF -- skipping upload.")
            print(
                f"     status={resp.status_code} content-type={content_type!r} "
                f"bytes={len(pdf_bytes)}"
            )
            print(f"     first 200 bytes: {pdf_bytes[:200]!r}")
            continue

        print(f"  uploading {label} ({len(pdf_bytes)} bytes) ...")
        buf = io.BytesIO(pdf_bytes)
        buf.name = f"{label}.pdf"  # openai-python uses this for the filename
        uploaded = client.files.create(file=buf, purpose="user_data")
        uploaded_docs[label] = {
            "file_id": uploaded.id,
            "pley_id": source["pley_id"],
            "sumilla": source["sumilla"],
        }
    return uploaded_docs


# ---------------------------------------------------------------------------
# Step 2: build one request body per (model, doc), same shape as the
# synchronous responses.create() call -- Batch just wraps it in a JSONL line.
# ---------------------------------------------------------------------------


def build_request_body(model: str, file_id: str, pley_id: str, sumilla: str) -> dict:
    text_block = {"type": "input_text", "text": USER_PROMPT}

    # Deliberately its own content block, AFTER the static text (and its
    # cache breakpoint, for models that get one) and BEFORE the file. This
    # is the per-document context (which bill to look for) -- it changes on
    # every request, so it must sit outside the cached prefix, or every
    # request would get a different prefix and caching would never hit.
    context_block = {
        "type": "input_text",
        "text": f"Context for this extraction:\npley_id: {pley_id}\nsumilla: {sumilla}",
    }

    body = {
        "model": model,
        "instructions": SYSTEM_PROMPT,
        "prompt_cache_key": PROMPT_CACHE_KEY,
        "input": [
            {
                "role": "user",
                "content": [
                    text_block,
                    context_block,
                    {"type": "input_file", "file_id": file_id},
                ],
            }
        ],
        "text": {
            "format": {
                "type": "json_schema",
                "name": "congress_session_extraction",
                "schema": EXTRACTION_SCHEMA,
                "strict": True,
            }
        },
    }

    if model in EXPLICIT_BREAKPOINT_MODELS:
        # GPT-5.6-family models place an implicit breakpoint at the latest
        # message by default, which here would span the static text, the
        # per-document context, AND the file -- all three vary or are new
        # per request in that combination, so the cached prefix would never
        # match. Disabling implicit mode and marking an explicit breakpoint
        # right after the static text (before context and file) is what
        # makes the shared instructions+prompt prefix reusable across every
        # document, every pley_id, and every batch.
        body["prompt_cache_options"] = {"mode": "explicit"}
        text_block["prompt_cache_breakpoint"] = {"mode": "explicit"}

    return body


def write_batch_files(uploaded_docs: dict[str, dict]) -> dict[str, Path]:
    """One .jsonl per model, containing one line per document."""
    paths = {}
    for model in MODELS:
        path = OUT_DIR / f"batch_{model.replace('.', '_')}.jsonl"
        with path.open("w", encoding="utf-8") as f:
            for label, doc in uploaded_docs.items():
                line = {
                    "custom_id": f"{model}::{label}",
                    "method": "POST",
                    "url": "/v1/responses",
                    "body": build_request_body(
                        model, doc["file_id"], doc["pley_id"], doc["sumilla"]
                    ),
                }
                f.write(json.dumps(line) + "\n")
        paths[model] = path
    return paths


# ---------------------------------------------------------------------------
# Step 3: submit one batch job per model (Batch API allows only one model
# per input file), and poll until every job reaches a terminal state.
# ---------------------------------------------------------------------------


def submit_batches(client: OpenAI, batch_paths: dict[str, Path]) -> dict[str, str]:
    batch_ids = {}
    for model, path in batch_paths.items():
        uploaded = client.files.create(file=open(path, "rb"), purpose="batch")
        batch = client.batches.create(
            input_file_id=uploaded.id,
            endpoint="/v1/responses",
            completion_window="24h",
            metadata={"description": f"congress-extraction-{model}"},
        )
        batch_ids[model] = batch.id
        print(f"Submitted batch for {model}: {batch.id} (status={batch.status})")
    return batch_ids


TERMINAL_STATUSES = {"completed", "failed", "expired", "cancelled"}


# ---------------------------------------------------------------------------
# Cost estimation.
#
# The model cannot report its own cost -- it has no reliable access to your
# billing rates or even a guaranteed count of its own output tokens as it
# generates. Cost is computed here from the real `usage` numbers the API
# returns, using a rate table you should verify yourself.
#
# $ per 1,000,000 tokens, STANDARD (non-batch), SHORT-CONTEXT (<270K tokens)
# rates -- these PDFs + prompt are nowhere near that, so short-context
# applies. gpt-5.6-luna rates below are confirmed directly from OpenAI's own
# pricing page (developers.openai.com/api/docs/pricing) at write time.
# gpt-4.1 / gpt-4o input+output rates were consistent across sources; their
# cached_input figure is a traditional-convention default, not independently
# confirmed -- verify against your dashboard.
#
# cache_write only applies to GPT-5.6+ models (pre-5.6 cache writes are
# free, so those rows simply omit the key and default to $0 via .get()).
# ---------------------------------------------------------------------------

PRICING_PER_MILLION = {
    "gpt-4.1": {"input": 2.00, "cached_input": 1.00, "output": 8.00},
    "gpt-4o": {"input": 2.50, "cached_input": 1.25, "output": 10.00},
    "gpt-5.6-luna": {
        "input": 0.20,
        "cached_input": 0.02,
        "cache_write": 0.25,
        "output": 1.20,
    },
}

# The Batch API discounts every token category (input, cached input, output)
# by 50% relative to the synchronous rate above.
BATCH_DISCOUNT = 0.5


def compute_cost_usd(model: str, usage: dict, is_batch: bool = True):
    """Cost in USD for one request, from its `usage` block. None if the
    model isn't in PRICING_PER_MILLION or usage is missing."""
    rates = PRICING_PER_MILLION.get(model)
    if not rates or not usage:
        return None

    input_tokens = usage.get("input_tokens") or 0
    details = usage.get("input_tokens_details") or {}
    cached_tokens = details.get("cached_tokens", 0) or 0
    # Only reported on GPT-5.6+; absent/zero on gpt-4.1 and gpt-4o.
    cache_write_tokens = details.get("cache_write_tokens", 0) or 0
    output_tokens = usage.get("output_tokens") or 0
    # cached_tokens and cache_write_tokens are each billed at their own rate;
    # whatever's left of input_tokens is billed at the plain input rate.
    plain_input = max(input_tokens - cached_tokens - cache_write_tokens, 0)

    cost = (
        plain_input * rates["input"]
        + cached_tokens * rates["cached_input"]
        + cache_write_tokens * rates.get("cache_write", 0.0)
        + output_tokens * rates["output"]
    ) / 1_000_000

    if is_batch:
        cost *= BATCH_DISCOUNT
    return round(cost, 6)


def poll_until_done(
    client: OpenAI, batch_ids: dict[str, str], interval: int = 60
) -> dict[str, object]:
    pending = dict(batch_ids)
    done = {}
    while pending:
        for model, batch_id in list(pending.items()):
            batch = client.batches.retrieve(batch_id)
            if batch.status in TERMINAL_STATUSES:
                counts = batch.request_counts
                print(
                    f"{model}: {batch.status} "
                    f"({counts.completed} completed, {counts.failed} failed, {counts.total} total)"
                )
                done[model] = batch
                del pending[model]
            else:
                print(f"{model}: {batch.status} ...")
        if pending:
            time.sleep(interval)
    return done


# ---------------------------------------------------------------------------
# Step 4: parse results. Batch output lines are RAW response JSON (not the
# Python SDK object), so `output_text` is not a literal field -- it's a
# client-side convenience the SDK computes. We walk body["output"] ourselves.
# ---------------------------------------------------------------------------


def extract_output_text(body: dict) -> str:
    chunks = []
    for item in body.get("output", []):
        if item.get("type") == "message":
            for part in item.get("content", []):
                if part.get("type") == "output_text":
                    chunks.append(part.get("text", ""))
    return "".join(chunks)


def collect_results(client: OpenAI, done_batches: dict[str, object]) -> list[dict]:
    results = []
    for model, batch in done_batches.items():
        # Check errors FIRST and unconditionally -- if every request in the
        # batch failed, output_file_id is empty and there is nothing else to
        # process, but the error file is exactly where the "why" lives.
        if batch.error_file_id:
            err_content = client.files.content(batch.error_file_id).text
            for line in err_content.splitlines():
                if line.strip():
                    print(f"[{model}] batch-level error line: {line}")

        if not batch.output_file_id:
            continue

        content = client.files.content(batch.output_file_id).text
        for line in content.splitlines():
            if not line.strip():
                continue
            record = json.loads(line)
            custom_id = record["custom_id"]
            _, label = custom_id.split("::", 1)

            if record.get("error"):
                results.append(
                    {
                        "custom_id": custom_id,
                        "model": model,
                        "doc_label": label,
                        "parsed": None,
                        "error": record["error"],
                    }
                )
                continue

            body = record["response"]["body"]
            output_text = extract_output_text(body)
            usage = body.get("usage", {}) or {}
            details = usage.get("input_tokens_details") or {}

            try:
                parsed = json.loads(output_text)
            except json.JSONDecodeError:
                parsed = None

            results.append(
                {
                    "custom_id": custom_id,
                    "model": model,
                    "doc_label": label,
                    "parsed": parsed,
                    "raw": output_text,
                    "input_tokens": usage.get("input_tokens"),
                    "output_tokens": usage.get("output_tokens"),
                    "cached_tokens": details.get("cached_tokens", 0),
                    "cache_write_tokens": details.get("cache_write_tokens", 0),
                    "cost_usd": compute_cost_usd(model, usage, is_batch=True),
                    "error": None,
                }
            )
    return results


def print_cache_summary(results: list[dict]) -> None:
    by_model: dict[str, list[float]] = {}
    for r in results:
        if r.get("input_tokens"):
            rate = (r.get("cached_tokens") or 0) / r["input_tokens"]
            by_model.setdefault(r["model"], []).append(rate)
    print("\nCache hit rate by model (cached_tokens / input_tokens, per request):")
    for model, rates in by_model.items():
        avg = sum(rates) / len(rates)
        print(f"  {model}: avg {avg:.1%} over {len(rates)} requests")


def print_cost_summary(results: list[dict]) -> None:
    totals: dict[str, float] = {}
    missing_rate_models = set()
    grand_total = 0.0
    for r in results:
        cost = r.get("cost_usd")
        if cost is None:
            if r.get("error") is None:
                missing_rate_models.add(r["model"])
            continue
        totals[r["model"]] = totals.get(r["model"], 0.0) + cost
        grand_total += cost

    print("\nEstimated batch cost (PRICING_PER_MILLION rates -- verify these):")
    for model, total in totals.items():
        n = sum(
            1 for r in results if r["model"] == model and r.get("cost_usd") is not None
        )
        print(
            f"  {model}: ${total:.4f} over {n} requests (${total / max(n, 1):.5f}/request avg)"
        )
    print(f"  TOTAL: ${grand_total:.4f}")
    if missing_rate_models:
        print(
            f"  (no rate configured for: {', '.join(sorted(missing_rate_models))} "
            f"-- add them to PRICING_PER_MILLION)"
        )


if __name__ == "__main__":
    client = OpenAI(api_key=settings.OPENAI_API_KEY)

    uploaded_docs = upload_pdfs_once(client, PDF_SOURCES)
    if len(uploaded_docs) < len(PDF_SOURCES):
        missing = set(PDF_SOURCES) - set(uploaded_docs)
        print(
            f"\n!! {len(missing)}/{len(PDF_SOURCES)} PDFs failed validation and were "
            f"skipped: {sorted(missing)}"
        )
        print(
            "   Fix the download for those before continuing, or proceed with the rest.\n"
        )
    if not uploaded_docs:
        raise SystemExit("No valid PDFs downloaded -- nothing to submit.")

    batch_paths = write_batch_files(uploaded_docs)
    batch_ids = submit_batches(client, batch_paths)
    done_batches = poll_until_done(client, batch_ids)
    results = collect_results(client, done_batches)

    Path("results.json").write_text(
        json.dumps(results, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    print(f"\nWrote {len(results)} results to results.json")
    print_cache_summary(results)
    print_cost_summary(results)
