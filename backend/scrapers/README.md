# Scrapers Module

This module extracts raw data from Congress endpoints/web pages and stores it in raw tables.

## Files

- `base.py`: `SharedRawScraperBase` — shared session/engine ownership, `update_tracking`, and bulk-save plumbing used by all 7 raw scrapers below. See [Shared base class](#shared-base-class).
- `bills.py`, `motions.py`, `leyes.py`: scrape bill/motion/leyes JSON/XML payloads into `RawBill`/`RawMotion`/`RawLeyes`.
- `bills_documents.py`, `motions_documents.py`: extract and OCR documents into raw document tables.
- `congresistas.py`, `bancadas.py`, `committees.py`, `organizations.py`: scrape reference entities.
- `utils.py`: HTTP helpers, parsing helpers, OCR/PDF support.

## Shared base class

All 7 raw scrapers (`bills.py`, `motions.py`, `leyes.py`, `congresistas.py`, `bancadas.py`, `committees.py`, `organizations.py`) subclass `SharedRawScraperBase` (`base.py`), which owns:

- **Session/engine ownership**: `__init__(session=None, engine=None)` — reuses a caller-supplied session, or opens its own.
- **Change-tracking**: `_update_tracking(obj, lookup_query)` compares a freshly-scraped object against the current `last_update=True` row via `RawBase.__eq__` and returns `[]` (nothing changed — don't write a duplicate row), `[obj]` (first-ever row), or `[obj, last]` (changed — flips `last.last_update = False`). Every scraper's `.extend()` calls the returned list, so an unchanged scrape correctly writes nothing.
- **Bulk save**: `_add_to_db(buffer, entity_name)` bulk-saves a buffer and returns `False` gracefully on an empty buffer (routine whenever nothing changed) instead of asserting.
- **Failure compensation**: if a bulk-save fails after a `last_update` flip, `_restore_tracking_updates()` restores the flipped row so a failed load never leaves zero "current" rows for an entity.

Each subclass keeps only its entity-specific scrape/create methods and its own buffer attribute (`self.raw_bills`, `self.raw_leyes`, etc.).

## Browser automation

Dynamic Congress pages should be scraped with Playwright. This is the project
standard for pages that require JavaScript rendering, hidden select controls, or
browser network behavior before HTML can be captured. Static HTML, XML, and JSON
endpoints should continue to use `httpx`/`lxml` helpers from `utils.py` instead
of launching a browser.

Playwright requires a browser binary in addition to the Python package. After
`uv sync`, install Chromium with:

```bash
uv run playwright install chromium
```

The reference scrapers use browser-rendered selections where needed:

- `bancadas.py`: captures parliamentary group pages for active `en Ejercicio`
  memberships.
- `committees.py`: renders the committee page, selects legislative years and
  committee types, then stores the resulting HTML snapshot.

## Output

Scrapers write to raw SQLAlchemy models in `backend/database/raw_models.py`.

Tracking fields on raw records:

- `last_update`: marks latest snapshot for an entity/version key.
- `changed`: whether latest snapshot differs from previous one.
- `processed`: whether latest snapshot still needs processing into clean tables.

## Typical use

You can run individual scraper scripts directly, but recommended usage is through the orchestrator:

```bash
uv run python -m backend --scrape
```

Useful options (from orchestrator):

- `--only-bills`, `--only-motions`, `--only-leyes`, `--only-others`.
- `--only-current`: scrape only the current period/year where supported by the
  reference scraper.
- `--scrape-documents`.

## Refresh behavior

The orchestrator handles incremental scraping:

- Bills and motions scrape new IDs first.
- Bills and motions then refresh pending daily rows whose latest raw snapshot is older than one day and not approved.
- Leyes scrape new IDs.
- Reference scrapers skip work when their latest raw scrape is already recent.

## Logging

The orchestrator writes tqdm-safe console summaries and per-stage files under `logs/`.

## Troubleshooting

- If a Playwright scraper fails because Chromium is missing, run
  `uv run playwright install chromium`.
- If a scraper times out waiting for a selector, inspect the current Congress
  page because the source markup may have changed.
- Use per-stage logs under `logs/scrapers/` to diagnose selector failures,
  skipped stages, and empty snapshots.
