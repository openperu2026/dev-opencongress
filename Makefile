migration:
	docker compose run --rm initial-migration

scrape-others:
	uv run -m backend --scrape --skip-processing --only-others --only-current --others-daily 

scrape-bills:
	uv run -m backend --scrape --skip-processing --only-bills --daily 

scrape-motions:
	uv run -m backend --scrape --skip-processing --only-motions --daily 

scrape-leyes:
	uv run -m backend --scrape --skip-processing --only-leyes --daily 

process:
	uv run -m backend