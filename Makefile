migration:
	docker compose run --rm initial-migration

scrape-others:
	uv run -m backend --scrape --skip-processing --only-others --only-current

scrape-bills:
	uv run -m backend --scrape --skip-processing --only-bills

scrape-motions:
	uv run -m backend --scrape --skip-processing --only-motions

scrape-leyes:
	uv run -m backend --scrape --skip-processing --only-leyes

process:
	uv run -m backend