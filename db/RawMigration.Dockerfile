FROM python:3.13-slim

WORKDIR /app

RUN pip install --no-cache-dir \
    pgvector==0.4.2 \
    "psycopg[binary]>=3.3.4,<4" \
    "sqlalchemy>=2.0.41,<3"

COPY backend /app/backend
COPY db /app/db
COPY data/raw/OpenPeruRaw.db /app/data/raw/OpenPeruRaw.db

ENV SQLITE_PATH=/app/data/raw/OpenPeruRaw.db

CMD ["python", "-m", "db.raw_migration"]
