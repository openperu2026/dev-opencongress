from sqlalchemy import create_engine, text, inspect
from sqlalchemy.exc import SQLAlchemyError
from ..config import settings

# Import all models from the models.py file
from .models import Base


def _enable_extensions(engine) -> None:
    """
    Enable pgvector extension for PostgreSQL.

    Required because SemanticBill uses pgvector.sqlalchemy.Vector.
    """
    if engine.dialect.name != "postgresql":
        return

    with engine.begin() as conn:
        conn.execute(text("CREATE EXTENSION IF NOT EXISTS vector;"))
        conn.execute(text("CREATE EXTENSION IF NOT EXISTS pg_similarity;"))
        conn.execute(text("CREATE EXTENSION IF NOT EXISTS unaccent;"))


def drop_step_vote_event_fks(engine) -> None:
    if engine.dialect.name != "postgresql":
        return

    with engine.begin() as conn:
        conn.execute(
            text(
                "ALTER TABLE bill_steps "
                "DROP CONSTRAINT IF EXISTS bill_steps_vote_event_id_fkey;"
            )
        )
        conn.execute(
            text(
                "ALTER TABLE motion_steps "
                "DROP CONSTRAINT IF EXISTS motion_steps_vote_event_id_fkey;"
            )
        )


def create_database(db_url: str = settings.DB_URL) -> bool:
    """
    Create all database tables in PostgreSQL using SQLAlchemy metadata.

    This is for initial database creation only.
    For real schema changes, use Alembic migrations.
    """
    engine = create_engine(db_url)

    try:
        _enable_extensions(engine)

        Base.metadata.create_all(bind=engine)
        drop_step_vote_event_fks(engine)

        inspector = inspect(engine)
        tables = inspector.get_table_names()

        print(f"Database initialized successfully with {len(tables)} tables.")
        return True

    except SQLAlchemyError as e:
        print(f"Error creating database schema: {e}")
        return False


if __name__ == "__main__":
    create_database()
