# Process Module

This module transforms raw SQLAlchemy rows into validated, normalized Pydantic schemas.

## Files

- `schema.py`: core Pydantic schemas used by processing.
- `bills.py`, `motions.py`: map raw records into clean bill/motion DTOs.
- `billtext.py`: cut the normative-body slice from a bill PDF's raw text using known headings and trailing markers.
- `congresistas.py`, `organizations.py`, `bancadas.py`: process reference entities and memberships.
- `votes.py`: vote-related parsing helpers.
- `utils.py`: shared processing utilities.
- `diff.py`: outer API `compute_bill_difference`; normalizes the two `BillText` bodies and composes the three diff layers into the JSON payload persisted in `BillDifference.difference_content`.
- `diff_structural.py`: Layer 1 — parses normalized text into section nodes (`TÍTULO`, `CAPÍTULO`, `Artículo N`, `DISPOSICIONES …`) and aligns the two versions (id → fingerprint → Jaccard ≥ 0.6 → leftover insert/delete).
- `diff_line.py`: Layer 2 — line-level `difflib.SequenceMatcher` diff inside each aligned node, emitting non-equal hunks only.
- `diff_word.py`: Layer 3 — token-level diff over `\w+|[^\w\s]` tokens, used to highlight intra-line word changes.

## Role in pipeline

- Input: raw models from `backend/database/raw_models.py`.
- Output: Pydantic models that are then persisted via DB CRUD helpers in the orchestrator flow.

This layer should stay:

- deterministic,
- side-effect free (no DB writes),
- strict about schema/normalization.

## How it is used

The orchestrator imports these functions and runs them in stage order:

1. load raw rows (`last_update=True`, `processed=False`)
2. process into schemas
3. upsert into clean DB models
