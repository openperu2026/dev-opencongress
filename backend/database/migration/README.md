# Database Setup

This directory contains the Docker setup for the shared OpenCongress PostgreSQL
database and the raw data migration image.

## Installing requirements

- Install Docker. Follow the instructions to install Docker Desktop [here](https://docs.docker.com/desktop/). If using WSL, follow [these instructions](https://docs.docker.com/desktop/features/wsl/). Then verify with:
  ```bash
  docker --version 
  ```

- Clone this repository and checkout `dev` or `feature/data_migration` branch.
  ```bash
  git clone git@github.com:openperu2026/dev-opencongress.git
  git switch feature/data_migration
  ```

## Run PostgreSQL

Start the database:

```bash
docker compose up -d db
```

The `db` service runs PostgreSQL 16 with `pgvector` and `pg_similarity`extensions.

Connection settings:

```text
POSTGRES_USER=opencongress
POSTGRES_PASSWORD=opencongress
POSTGRES_DB=opencongress
```

Use this URL from the host machine:

```bash
export DB_URL=postgresql+psycopg://opencongress:opencongress@localhost:5432/opencongress
```

## Run Migration

The migration image contains the old SQLite `OpenPeruRaw.db` seed data. The SQLite file is not committed to Git, so any contributor should use the published DockerHub image instead of building it locally.

Set the image tag:

```bash
export OPENPERU_RAW_MIGRATION_IMAGE=cesarnunezh/opencongress-raw-migration:latest
```

Run the migration:

```bash
docker compose run --rm migrate-raw
```

## Maintainer Notes

Only the person publishing the shared seed image needs the local
`data/raw/OpenPeruRaw.db` file.

Build and push the image:

```bash
docker buildx build \
  --platform linux/amd64,linux/arm64 \
  --push \
  -f backend/database/migration/migration.Dockerfile \
  -t cesarnunezh/opencongress-raw-migration:latest \
  .

docker push cesarnunezh/opencongress-raw-migration:latest
```

After pushing a new seed image, other contributors can reset their local volume and rerun the migration.
