import sys
from pathlib import Path
from backend.config import settings
from backend.database import models, raw_models
from sqlalchemy.orm import sessionmaker
from sqlalchemy import create_engine, inspect, select

# When run from anywhere, anchor to this file and hop to repo root.
repo_root = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(repo_root))


db_engine = create_engine(settings.DB_URL, pool_pre_ping=True)
db_session = sessionmaker(
    bind=db_engine,
    autocommit=False,
    autoflush=False,
)


# QUERIES
def get_approved_ids(model: type) -> list[str]:
    with db_session() as db:
        return list(db.scalars(select(model.id).where(model.bill_approved.is_(True))))


def print_available_tables() -> None:
    inspector = inspect(db_engine)
    tables = inspector.get_table_names()
    print(f"Found {len(tables)} tables:")
    for table in tables:
        print(f"- {table}")


def get_raw_bill_documents(limit: int = 10):
    inspector = inspect(db_engine)
    tables = set(inspector.get_table_names())
    if "raw_bill_documents" in tables:
        with db_session() as db:
            return list(db.scalars(select(raw_models.RawBillDocument).limit(limit)))
    if "bill_documents" in tables:
        print("raw_bill_documents table not found; using bill_documents.")
        with db_session() as db:
            return list(db.scalars(select(models.BillDocument).limit(limit)))
    print("No bill documents table found.")
    return []


if __name__ == "__main__":
    print_available_tables()
    # raw_docs = get_raw_bill_documents()
    # print(f"First {len(raw_docs)} bill documents:")
    # for doc in raw_docs:
    #     file_id = getattr(doc, "file_id", getattr(doc, "archivo_id", None))
    #     print(f"- {doc.bill_id} | {doc.step_id} | {file_id} | {doc.url}")

    # ids = get_approved_ids(models.Bill)
    # print(ids)
