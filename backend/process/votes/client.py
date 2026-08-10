from dataclasses import dataclass
from functools import lru_cache
from typing import Literal

from openai import OpenAI

from backend.config import settings
from backend.process.votes.config import (
    EXPLICIT_BREAKPOINT_MODELS,
    EXTRACTION_SCHEMA,
    PRICING_PER_MILLION,
    PROMPT_CACHE_KEY,
    SYSTEM_PROMPTS,
    USER_PROMPTS,
)


@lru_cache(maxsize=1)
def get_client() -> OpenAI:
    return OpenAI(api_key=settings.OPENAI_API_KEY)


def build_request_body(
    model: str,
    file_id: str,
    kind: Literal["bill", "motion"],
    context_text: str,
) -> dict:
    """
    Build the request body for one extraction call (used both by the sync
    client.responses.create(**body) path and, wrapped in a jsonl line, by the
    Batch API path).
    """
    text_block: dict[str, str | dict[str, str]] = {
        "type": "input_text",
        "text": USER_PROMPTS[kind],
    }

    # Deliberately its own content block, AFTER the static text (and its
    # cache breakpoint, for models that get one) and BEFORE the file. This
    # is the per-document context -- it changes on every request, so it must
    # sit outside the cached prefix, or every request would get a different
    # prefix and caching would never hit.
    context_block: dict[str, str] = {"type": "input_text", "text": context_text}

    body = {
        "model": model,
        "instructions": SYSTEM_PROMPTS[kind],
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
        # per request, so the cached prefix would never match. Disabling
        # implicit mode and marking an explicit breakpoint right after the
        # static text (before context and file) makes the shared
        # instructions+prompt prefix reusable across every document and
        # every batch.
        body["prompt_cache_options"] = {"mode": "explicit"}
        text_block["prompt_cache_breakpoint"] = {"mode": "explicit"}

    return body


@dataclass
class ExtractionResult:
    custom_id: str
    model: str
    parsed: dict | None
    raw: str | None
    input_tokens: int | None
    output_tokens: int | None
    cached_tokens: int
    cache_write_tokens: int
    cost_usd: float | None
    error: dict | None


def compute_cost_usd(model: str, usage: dict, is_batch: bool) -> float | None:
    """Cost in USD for one request, from its `usage` block. None if the
    model isn't in PRICING_PER_MILLION or usage is missing."""
    rates = PRICING_PER_MILLION.get(model)
    if not rates or not usage:
        return None

    input_tokens = usage.get("input_tokens") or 0
    details = usage.get("input_tokens_details") or {}
    cached_tokens = details.get("cached_tokens", 0) or 0
    cache_write_tokens = details.get("cache_write_tokens", 0) or 0
    output_tokens = usage.get("output_tokens") or 0
    plain_input = max(input_tokens - cached_tokens - cache_write_tokens, 0)

    cost = (
        plain_input * rates["input"]
        + cached_tokens * rates["cached_input"]
        + cache_write_tokens * rates.get("cache_write", 0.0)
        + output_tokens * rates["output"]
    ) / 1_000_000

    if is_batch:
        from backend.process.votes.config import BATCH_DISCOUNT

        cost *= BATCH_DISCOUNT
    return round(cost, 6)


def _extract_output_text(body: dict) -> str:
    chunks = []
    for item in body.get("output", []):
        if item.get("type") == "message":
            for part in item.get("content", []):
                if part.get("type") == "output_text":
                    chunks.append(part.get("text", ""))
    return "".join(chunks)


def normalize_sync_response(resp, model: str, custom_id: str) -> ExtractionResult:
    """Normalize a client.responses.create() SDK response into an ExtractionResult."""
    usage = resp.usage.model_dump() if resp.usage is not None else {}
    details = usage.get("input_tokens_details") or {}
    output_text = resp.output_text

    try:
        import json

        parsed = json.loads(output_text) if output_text else None
    except (ValueError, TypeError):
        parsed = None

    return ExtractionResult(
        custom_id=custom_id,
        model=model,
        parsed=parsed,
        raw=output_text,
        input_tokens=usage.get("input_tokens"),
        output_tokens=usage.get("output_tokens"),
        cached_tokens=details.get("cached_tokens", 0) or 0,
        cache_write_tokens=details.get("cache_write_tokens", 0) or 0,
        cost_usd=compute_cost_usd(model, usage, is_batch=False),
        error=None,
    )


def normalize_batch_output_line(line: str, model: str) -> ExtractionResult:
    """Normalize one raw line from a completed Batch API output file."""
    import json

    record = json.loads(line)
    custom_id = record["custom_id"]

    if record.get("error"):
        return ExtractionResult(
            custom_id=custom_id,
            model=model,
            parsed=None,
            raw=None,
            input_tokens=None,
            output_tokens=None,
            cached_tokens=0,
            cache_write_tokens=0,
            cost_usd=None,
            error=record["error"],
        )

    body = record["response"]["body"]
    output_text = _extract_output_text(body)
    usage = body.get("usage", {}) or {}
    details = usage.get("input_tokens_details") or {}

    try:
        parsed = json.loads(output_text)
    except (ValueError, TypeError):
        parsed = None

    return ExtractionResult(
        custom_id=custom_id,
        model=model,
        parsed=parsed,
        raw=output_text,
        input_tokens=usage.get("input_tokens"),
        output_tokens=usage.get("output_tokens"),
        cached_tokens=details.get("cached_tokens", 0) or 0,
        cache_write_tokens=details.get("cache_write_tokens", 0) or 0,
        cost_usd=compute_cost_usd(model, usage, is_batch=True),
        error=None,
    )
