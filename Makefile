scrape-others:
	uv run -m backend --scrape --skip-processing --only-others --only-current

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
	uv run -m backend

process-bill-documents:
	uv run -m backend --only-bills --process-documents	

process-votes-sync:
	uv run -m backend --only-votes --votes-limit 10 --votes-max-cost-usd 5.0

backfill-bancadas-bills:
	uv run python scripts/backfill_bancada_snapshots.py --only bills

backfill-bancadas-motions:
	uv run python scripts/backfill_bancada_snapshots.py --only motions
