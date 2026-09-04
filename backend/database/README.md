# Database Module

This module defines raw/clean DB schemas and orchestrates persistence.

## Files

- `raw_models.py`: raw ingestion tables (`Raw*`), including tracking fields (`last_update`, `processed` and `changed`).
- `models.py`: clean SQLAlchemy models for normalized entities and relations.
- `build_db.py`: create/update SQLite DBs and ensure all columns exist.
- `orchestrator.py`: end-to-end ETL runner (scrape + process + load).
- `crud/`: DB helper functions for upserts and lookups used by the orchestrator.
  - `pipeline_core.py`
  - `pipeline_bills.py` (bills, steps, documents, and `billtext` rows)
  - `pipeline_motions.py`

## Databases

Configured in `backend/config.py`:

- Raw DB: `settings.RAW_DB_URL` (default `data/raw/OpenPeruRaw.db`)
- Clean DB: `settings.DB_URL` (default `data/processed/OpenPeru.db`)

## Create DBs

```bash
uv run python -m backend.database.build_db
```

## Run orchestrator

```bash
uv run python -m backend --help
```

Examples:

```bash
# Process only (no scrape)
uv run python -m backend

# Scrape + process only bills
uv run python -m backend --scrape --only-bills

# Daily refresh window = 10 days
uv run python -m backend --scrape --daily 10
```

## Raw tracking semantics

For each latest raw record:

- first version: `last_update = True`, `changed=True`, `processed=False`
- unchanged new version: `last_update = True`, `changed=False`, `processed=True`
- changed new version: `last_update = True`, `changed=True`, `processed=False`

This allows process stages to focus on records that still need clean-table updates.

## Transaction boundaries in batch processing

Orchestrator batch methods (e.g. `_process_congresistas`, `_process_bills`, `_process_motions`, `_process_bancada_definitions`) commit once per row, inside the same `try` block as that row's write, not once after the whole loop. This keeps each row's success/failure atomic: one row raising an exception rolls back only that row, and every earlier row in the same run stays committed.

## Gap detection and retry in range scraping

`_scrape_range`/`_scrape_chamber_range` track the max scraped id per raw table as a watermark, but a watermark alone can't detect an id that failed mid-range and was never retried. `_find_id_gaps` reports missing ids between the observed min and max; failed gap ids are retried on subsequent runs, throttled the same way forward scraping is, up to `MAX_GAP_RETRY_ATTEMPTS` attempts, tracked in the `scrape_gap_retries` table (`ScrapeGapRetry` in `raw_models.py`, see `docs/data_model.md`). Past the cap, a gap id is marked `skipped` and excluded from future retries — this covers legitimately nonexistent ids (withdrawn/renumbered legislative items), which are indistinguishable from a transient failure by id alone.

## Bill PDF text

When bills are processed **with documents** (default; skip with `--no-documents`), each PDF's raw text is stored in `bill_documents` and a heading-based slice is stored in `billtext`. See `docs/data-model.md` (`BillText`).
