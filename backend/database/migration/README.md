# Database Setup

This directory contains the Docker setup for the shared OpenCongress PostgreSQL
database and the raw data migration image.

## Run PostgreSQL

Start the database:

```bash
docker compose up -d db
```

The `db` service runs PostgreSQL 16 with `pgvector` and `pg_similarity`.

Connection settings:

```text
POSTGRES_USER=opencongress
POSTGRES_PASSWORD=opencongress
POSTGRES_DB=opencongress
```

Use this URL from the host machine:

```bash
DB_URL=postgresql+psycopg://opencongress:opencongress@localhost:5432/opencongress
```

## Raw Migration

The raw migration image contains the old SQLite `OpenPeruRaw.db` seed data. The raw
SQLite file is not committed to Git, so any contributor should use the published
DockerHub image instead of building it locally.

Set the image tag:

```bash
export OPENPERU_RAW_MIGRATION_IMAGE=cesarnunezh/opencongress-raw-migration:latest
```

Run the migration:

```bash
docker compose run --rm migrate-raw
```

The migration creates the current application schema, creates the current raw
schema, imports latest raw SQLite data, and validates the result. Raw tables are
filtered to rows where `last_update = True`; `scraper_runs` is imported as-is
because it has no `last_update` column.

Imported with data:

```text
raw_bancadas
raw_bills
raw_bill_documents
raw_committees
raw_congresistas
raw_leyes
raw_motion_documents
raw_motions
raw_organizations
scraper_runs
```

Created but intentionally left empty:

```text
raw_bill_pages
raw_motion_pages
```

For document tables, the legacy SQLite `text` column is intentionally not
imported. `s3_key` and `local_path` are generated from the document filename and
S3 key rules used by the scrapers. Legacy document IDs are mapped as follows:

```text
seguimiento_id -> step_id
archivo_id     -> file_id
```

Duplicate bill document keys are resolved by keeping the newest `timestamp`.

Expected row counts for the current raw seed:

```text
raw_bancadas=121
raw_bills=13989
raw_bill_documents=24838
raw_committees=272
raw_congresistas=140
raw_leyes=32492
raw_motion_documents=225
raw_motions=21709
raw_organizations=0
raw_bill_pages=0
raw_motion_pages=0
scraper_runs=0
```

## Troubleshooting

If Docker reports `pull access denied`, confirm the image tag is set and that
you are logged into DockerHub if the repository is private:

```bash
echo "$OPENPERU_RAW_MIGRATION_IMAGE"
docker login
docker compose run --rm migrate-raw
```

If the migration fails because raw tables are not empty, reset the volume using
the commands in the reset section.

## Maintainer Notes

Only the person publishing the shared seed image needs the local
`data/raw/OpenPeruRaw.db` file.

Build and push the image:

```bash
docker build \
  -f db/RawMigration.Dockerfile \
  -t cesarnunezh/opencongress-raw-migration:latest \
  .

docker push cesarnunezh/opencongress-raw-migration:latest
```

After pushing a new seed image, teammates can reset their local volume and rerun
the migration.
