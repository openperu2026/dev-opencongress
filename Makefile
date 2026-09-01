# Optionally restrict congresistas/bancadas/organizations processing to a
# single legislative period, e.g. LEG_PERIOD=2026-2031 make process
LEG_PERIOD_FLAG = $(if $(LEG_PERIOD),--leg-period $(LEG_PERIOD),)

scrape-others:
	uv run -m backend --scrape --skip-processing --only-others --only-current $(LEG_PERIOD_FLAG)

scrape-bills:
	uv run -m backend --scrape --skip-processing --only-bills

scrape-motions:
	uv run -m backend --scrape --skip-processing --only-motions

scrape-leyes:
	uv run -m backend --scrape --skip-processing --only-leyes

scrape-documents:
	uv run -m backend --scrape --skip-processing --scrape-documents --upload-s3

process-first-summary:
	uv run -m backend --only-bills --first-summary

process:
	uv run -m backend $(LEG_PERIOD_FLAG)

process-bill-documents:
	uv run -m backend --only-bills --process-documents	

process-votes-sync:
	uv run -m backend --only-votes --votes-limit 10 --votes-max-cost-usd 5.0

backfill-bancadas-bills:
	uv run python scripts/backfill_bancada_snapshots.py --only bills

backfill-bancadas-motions:
	uv run python scripts/backfill_bancada_snapshots.py --only motions

process-votes-from-raw:
	uv run -m backend --only-votes --skip-vote-extraction