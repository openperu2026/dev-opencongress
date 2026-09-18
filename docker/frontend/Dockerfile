FROM python:3.13-slim

ENV PYTHONUNBUFFERED=1 \
    UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    TZ=America/Lima

WORKDIR /app

COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /usr/local/bin/

COPY pyproject.toml uv.lock /app/
RUN uv sync --locked --no-dev --no-install-project --extra web

COPY app /app/app

COPY backend/__init__.py /app/backend/__init__.py
COPY backend/config.py /app/backend/config.py
COPY backend/core /app/backend/core
COPY backend/database /app/backend/database
COPY backend/services /app/backend/services
COPY backend/process/__init__.py /app/backend/process/__init__.py
COPY backend/process/utils.py /app/backend/process/utils.py
COPY backend/process/schema.py /app/backend/process/schema.py

EXPOSE 8040

CMD ["uv", "run", "gunicorn", "--preload", "--timeout", "30", "--workers", "4", "--bind", "0.0.0.0:8040", "app.app:create_app()"]