FROM pgvector/pgvector:pg16

RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    ca-certificates \
    git \
    postgresql-server-dev-16 \
    && git clone --depth 1 https://github.com/eulerto/pg_similarity.git /tmp/pg_similarity \
    && make -C /tmp/pg_similarity USE_PGXS=1 \
    && make -C /tmp/pg_similarity USE_PGXS=1 install \
    && rm -rf /tmp/pg_similarity \
    && apt-get purge -y --auto-remove build-essential git postgresql-server-dev-16 \
    && rm -rf /var/lib/apt/lists/*