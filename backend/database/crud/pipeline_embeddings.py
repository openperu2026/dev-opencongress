from __future__ import annotations

import re
from sqlalchemy import select, desc, insert
from sqlalchemy.orm import Session

from backend.database import models as db_models
from sentence_transformers import SentenceTransformer


def create_bill_full_text(db: Session, bill_id: str) -> str:
    """
    Build the full searchable text representation of a bill.

    The returned text combines the most relevant bill fields into a single
    structured string that can later be split into chunks and embedded for
    semantic search.

    Args:
        db (Session): Active SQLAlchemy database session.
        bill_id (str): Unique identifier of the bill.

    Returns:
        str: Structured text representation of the bill, including title,
            congressional summary, authors, committees, and the latest available
            bill text.
    """

    # Title of the bill
    title = db.scalar(select(db_models.Bill.title).where(db_models.Bill.id == bill_id))

    # Summary provided by the Congress
    summary_congreso = db.scalar(
        select(db_models.Bill.summary_congreso).where(db_models.Bill.id == bill_id)
    )

    # Looking for all the authors
    authors = db.scalars(
        select(db_models.Congresista.full_name)
        .join(
            db_models.BillCongresistas,
            db_models.BillCongresistas.person_id == db_models.Congresista.id,
        )
        .where(
            db_models.BillCongresistas.bill_id == bill_id,
            db_models.BillCongresistas.role_type == "Autor",
        )
    ).all()

    # Looking for all the committees
    committees = db.scalars(
        select(db_models.Organization.org_name)
        .join(
            db_models.BillOrganization,
            db_models.BillOrganization.org_id == db_models.Organization.org_id,
        )
        .where(
            db_models.BillOrganization.bill_id == bill_id,
            db_models.Organization.org_type == "Comisión",
        )
    ).all()

    # Looking for the last bill text
    bill_text = db.scalar(
        select(db_models.BillText.text)
        .where(
            db_models.BillText.bill_id == bill_id,
        )
        .order_by(desc(db_models.BillText.step_id), desc(db_models.BillText.version_id))
        .limit(1)
    )

    return f"""
Título: {title or ""}

Sumilla: {summary_congreso or ""}

Autores: {", ".join(authors)}

Comisiones: {", ".join(committees)}

Texto:
{bill_text or ""}
""".strip()


def _get_text_chunks(text: str, chunk_size: int = 500, overlap: int = 100) -> list[str]:
    """
    Split text into overlapping chunks for embedding generation.

    The function splits text by words, not characters, to avoid cutting words in
    the middle. Consecutive chunks can share a configurable number of words so
    that important context is not lost at chunk boundaries.

    Args:
        text (str): Full text to split into chunks.
        chunk_size (int): Maximum number of words per chunk.
        overlap (int): Number of words shared between consecutive chunks.

    Returns:
        list[str]: List of text chunks ready for embedding generation.
    """

    if not text or not text.strip():
        return []

    if chunk_size <= 0:
        raise ValueError("chunk_size must be greater than 0")

    if overlap < 0:
        raise ValueError("overlap cannot be negative")

    if overlap >= chunk_size:
        raise ValueError("overlap must be smaller than chunk_size")

    # Normalize whitespace
    text = re.sub(r"\s+", " ", text).strip()

    words = text.split()

    if len(words) <= chunk_size:
        return [text]

    chunks = []
    start = 0

    while start < len(words):
        end = start + chunk_size
        chunk_words = words[start:end]
        chunks.append(" ".join(chunk_words))

        if end >= len(words):
            break

        start = end - overlap

    return chunks


def build_semantic_bill_rows(
    db: Session,
    bill_ids: list[str],
    model_name: str,
    embedding_model: SentenceTransformer,
) -> list[dict]:
    """
    Build semantic-search rows for multiple bills.

    The function creates bill text chunks for all provided bills, embeds all
    chunks in batches, and returns dictionaries ready for bulk upsert.

    Args:
        db (Session): Active SQLAlchemy database session.
        bill_ids (list[str]): Bill IDs to process.
        model_name (str): Name of the SentenceTransformer model used to generate
            embeddings.
        embedding_model (SentenceTransformer): Loaded embedding model.

    Returns:
        list[dict]: Rows ready to be inserted or updated in the
            semantic_bills table.
    """

    texts: list[str] = []
    metadata: list[dict] = []

    for bill_id in bill_ids:
        full_text = create_bill_full_text(db, bill_id)
        chunks = _get_text_chunks(full_text)

        for chunk_index, chunk in enumerate(chunks):
            texts.append(chunk)
            metadata.append(
                {
                    "bill_id": bill_id,
                    "chunk_index": chunk_index,
                    "text": chunk,
                    "embedding_model": model_name,
                }
            )

    if not texts:
        return []

    embeddings = embedding_model.encode(
        texts,
        normalize_embeddings=True,
        batch_size=32,
    )

    return [
        {
            **meta,
            "embedding": embedding.tolist(),
        }
        for meta, embedding in zip(metadata, embeddings)
    ]


def bulk_upsert_semantic_bills(
    db: Session,
    bill_ids: list[str],
    model_name: str = "intfloat/multilingual-e5-base",
) -> int:
    """
    Generate and upsert semantic-search chunks for multiple bills.

    Args:
        db (Session): Active SQLAlchemy database session.
        bill_ids (list[str]): Bill IDs to process.
        model_name (str): SentenceTransformer model used to generate embeddings.

    Returns:
        int: Number of semantic chunk rows inserted or updated.
    """

    if not bill_ids:
        return 0

    embedding_model = SentenceTransformer(model_name)

    rows = build_semantic_bill_rows(
        db=db,
        bill_ids=bill_ids,
        model_name=model_name,
        embedding_model=embedding_model,
    )

    if not rows:
        return 0

    stmt = insert(db_models.SemanticBill).values(rows)

    stmt = stmt.on_conflict_do_update(
        constraint="uq_semantic_bills_bill_chunk_model",
        set_={
            "text": stmt.excluded.text,
            "embedding": stmt.excluded.embedding,
        },
    )

    db.execute(stmt)
    db.commit()

    return len(rows)
