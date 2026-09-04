# Optionally restrict congresistas/bancadas/organizations PROCESSING to a
# single legislative period, e.g. LEG_PERIOD=2026-2031 make process. For
# SCRAPING bills/motions, this does NOT restrict the legacy scrape (it
# always runs) -- it only controls whether the additional current-period
# chamber-specific range scrapers also run: by default (LEG_PERIOD unset)
# or with LEG_PERIOD set to the current period (2026-2031, from .env), and
# skipped for any other value. SCRAPING congresistas/bancadas/committees/
# organizations is the OPPOSITE: that legacy reference data is now
# historical/stable, so it's skipped by default and only runs when
# LEG_PERIOD is set to something OTHER than the current period (e.g.
# 2021-2026) -- see scrape-others-legacy below. See backend/cli.py's
# --leg-period help text for the full explanation.
LEG_PERIOD_FLAG = $(if $(LEG_PERIOD),--leg-period $(LEG_PERIOD),)

# Scrape congresistas, bancadas, committees, and organizations (raw only,
# no processing) for the CURRENT period only (2026-2031, from .env) --
# this is the default composition now that the legacy roster is historical.
# Use scrape-others-legacy (or LEG_PERIOD=2021-2026 explicitly) to opt back
# into the full legacy reference scrape instead.
scrape-others:
	uv run -m backend --scrape --skip-processing --only-others --only-current $(LEG_PERIOD_FLAG)

# One-off opt-in: scrape the LEGACY (2021-2026) congresistas/bancadas/
# committees/organizations reference data. Skips the current-period
# chamber scrape for this run (see backend/cli.py's --leg-period help).
scrape-others-legacy:
	uv run -m backend --scrape --skip-processing --only-others --only-current --leg-period 2021-2026

# Scrape bills (raw only, no processing): new ids since the last scrape,
# then re-scrape any pending/stale rows. Also runs the 2026-2031
# per-chamber bill range scrapers (Phase B2) unless LEG_PERIOD excludes
# them -- see LEG_PERIOD_FLAG comment above.
scrape-bills:
	uv run -m backend --scrape --skip-processing --only-bills $(LEG_PERIOD_FLAG)

# Scrape motions (raw only, no processing): same shape as scrape-bills,
# including the 2026-2031 per-chamber motion range scrapers (Phase B2).
scrape-motions:
	uv run -m backend --scrape --skip-processing --only-motions $(LEG_PERIOD_FLAG)

# Scrape leyes (raw only, no processing). Not period-gated -- there is no
# bicameral concept for leyes, so LEG_PERIOD_FLAG is deliberately omitted.
scrape-leyes:
	uv run -m backend --scrape --skip-processing --only-leyes

# Retry bill/motion documents whose s3_key is still null, then scrape any
# newly-pending documents and upload everything to S3. Not period-gated
# (documents aren't scoped by legislative period).
scrape-documents:
	uv run -m backend --scrape --skip-processing --scrape-documents --upload-s3

# One-time backfill: compute bill summaries + semantic embeddings for
# EVERY eligible bill (not just changed ones), and seed the first-ever
# 2026-2031 chamber/party/bancada/admin-org membership per person with the
# confirmed real term-start date (2026-07-28) instead of the scrape
# timestamp -- see backend/database/orchestrator.py::_upsert_membership_schema.
# Scoped to --only-bills, so it does NOT touch congresistas/membership
# processing at all; use `process-first-load-2026-2031` for that.
process-first-summary:
	uv run -m backend --only-bills --first-summary

# One-time backfill of the 2026-2031 membership start-date seeding
# specifically (see process-first-summary's comment above for what
# --first-summary does to memberships). Runs full processing (not
# --only-bills), scoped to the 2026-2031 period so legacy memberships are
# never touched. Safe to re-run: only the FIRST-ever membership recorded
# per (person, org, leg_period, org_type) gets the term-start date: a
# later re-scrape of an already-recorded membership (e.g. a bancada
# switch) is unaffected.
process-first-load-2026-2031:
	uv run -m backend --leg-period 2026-2031 --first-summary

# Full raw -> clean processing for all entities. LEG_PERIOD_FLAG narrows
# congresistas/bancadas/organizations processing to one period; bills/
# motions/leyes processing is never period-gated (chamber for bills/
# motions is resolved per-row from the bill/motion's own id).
process:
	uv run -m backend $(LEG_PERIOD_FLAG)

# Process (OCR + text extraction) pending bill documents already scraped
# via scrape-documents.
process-bill-documents:
	uv run -m backend --only-bills --process-documents

# Sync vote extraction + load for a small batch (10 documents, $5 budget)
# -- the day-to-day incremental vote-processing run, as opposed to a full
# historical Batch API backfill (see backend/cli.py's --submit-vote-batches).
process-votes-sync:
	uv run -m backend --only-votes --votes-limit 10 --votes-max-cost-usd 5.0

# One-off backfill scripts: recompute bancada snapshots (which bancada a
# congresista belonged to at the time) for existing bills/motions,
# independent of the main scrape/process pipeline.
backfill-bancadas-bills:
	uv run python scripts/backfill_bancada_snapshots.py --only bills

backfill-bancadas-motions:
	uv run python scripts/backfill_bancada_snapshots.py --only motions

# Load votes/attendance from already-extracted raw data (--skip-vote-extraction),
# without re-running extraction against the LLM -- use after a Batch API
# job has been collected, or to reprocess existing extractions.
process-votes-from-raw:
	uv run -m backend --only-votes --skip-vote-extraction

# Regenerate cong_info_2026_2031.json: mines dni/gender/congresista_id for
# 2026-2031 congresistas from bill/motion "firmantes" (signatory) sections
# already scraped -- same technique cong_info_2021_2026.json was built
# with, adapted for the new term's id format and lack of a website field.
# Safe to rerun anytime (dedups by congresistaId): coverage only grows as
# more 2026-2031 bills/motions get scraped and signed, so re-running this
# periodically is expected, not a one-time setup step. See
# backend/process/utils.py::gen_congresistas_df's leg_period docstring.
gen-congresistas-2026-2031:
	uv run python -c "from backend.database.session import get_db; from backend.process.utils import gen_congresistas_df; gen_congresistas_df(next(get_db()), save=True, leg_period='2026-2031')"
