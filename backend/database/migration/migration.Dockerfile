FROM python:3.13-slim

WORKDIR /app

RUN pip install --no-cache-dir \
    "loguru>=0.7.3,<1" \
    "lxml>=5.3.1,<6" \
    "pgvector>=0.4.2,<1" \
    "polars>=1.30.0,<2" \
    "psycopg[binary]>=3.3.4,<4" \
    "pydantic>=2.11.7,<3" \
    "pydantic-settings>=2.10.1,<3" \
    "sqlalchemy>=2.0.41,<3" \
    "tqdm>=4.67.3,<5" \
    "typing-extensions>=4.14.0,<5"

COPY backend /app/backend
COPY data/raw/OpenPeruRaw.db /app/data/raw/OpenPeruRaw.db

ENV SQLITE_PATH=/app/data/raw/OpenPeruRaw.db

CMD ["python", "-m", "backend.database.migration"]
