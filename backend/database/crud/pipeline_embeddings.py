from __future__ import annotations

import re
from sqlalchemy import select, desc
from sqlalchemy.orm import Session

from backend.database import models as db_models
from sentence_transformers import SentenceTransformer


def create_bill_full_text(db: Session, bill_id: str) -> str:
    """
    Creates the text that will be embedded

    Args:
        db (Session): database session
        bill_id (str): unique identifier of the bill

    Returns:
        str: Text related to the bill with a format as follows:
        '''
            Título: {bill.title}

            Sumilla: {bill.summary}

            Autores: {bill.authors}

            Resumen OC: {bill.steps}

            Comisiones: {bill.committees}

            Texto: {bill.bill_text}
        '''
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
    Generate text chunks for embedding generation.

    Args:
        text (str): Text related to the bill.
        chunk_size (int): Size of each chunk in number of words.
        overlap (int): Number of words shared between consecutive chunks.

    Returns:
        list[str]: List of text chunks.
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


if __name__ == "__main__":
    model = SentenceTransformer("intfloat/multilingual-e5-base")
    input_texts = [
        "query: how much protein should a female eat",
        "passage: As a general guideline, the CDC's average requirement of protein for women ages 19 to 70 is 46 grams per day. But, as you can see from this chart, you'll need to increase that if you're expecting or training for a marathon. Check out the chart below to see how much protein you should be eating each day.",
    ]
    embeddings = model.encode(input_texts, normalize_embeddings=True)

    print(embeddings)
