"""Database container and migration helpers."""

import os
import argparse
import sqlite3
from pathlib import Path
from sqlalchemy import create_engine
from sqlalchemy.engine import Engine

from .migration import (
    DEFAULT_DB_URL,
    DEFAULT_SQLITE_PATH,
    enable_extensions,
    assert_raw_tables_empty,
    import_direct_tables,
    import_document_tables,
    validate_import,
    reset_sequences,
)
from backend.database.models import Base
from backend.database import raw_models as raw_models


def main() -> None:
    args = parse_args()
    sqlite_path = Path(args.sqlite_path)
    if not sqlite_path.exists():
        raise FileNotFoundError(f"SQLite source not found: {sqlite_path}")

    sqlite_conn = sqlite3.connect(sqlite_path)
    sqlite_conn.row_factory = sqlite3.Row
    engine = create_engine(args.db_url, pool_pre_ping=True)

    try:
        migrate(sqlite_conn, engine, validate_checksums=not args.skip_checksums)
    finally:
        sqlite_conn.close()
        engine.dispose()


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Import the baked OpenPeru raw SQLite database into PostgreSQL."
    )
    parser.add_argument(
        "--db-url",
        default=os.getenv("DB_URL", DEFAULT_DB_URL),
        help="SQLAlchemy PostgreSQL URL. Defaults to DB_URL.",
    )
    parser.add_argument(
        "--sqlite-path",
        default=os.getenv("SQLITE_PATH", DEFAULT_SQLITE_PATH),
        help="Path to OpenPeruRaw.db inside the migration container.",
    )
    parser.add_argument(
        "--skip-checksums",
        action="store_true",
        help="Only validate row counts after import.",
    )
    return parser.parse_args()


def migrate(
    sqlite_conn: sqlite3.Connection,
    engine: Engine,
    *,
    validate_checksums: bool = True,
) -> None:
    enable_extensions(engine)
    Base.metadata.create_all(engine)

    with engine.begin() as pg_conn:
        assert_raw_tables_empty(pg_conn)
        import_direct_tables(sqlite_conn, pg_conn)
        import_document_tables(sqlite_conn, pg_conn)
        reset_sequences(pg_conn)
        validate_import(sqlite_conn, pg_conn, validate_checksums=validate_checksums)


if __name__ == "__main__":
    main()
