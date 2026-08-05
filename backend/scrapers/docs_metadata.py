"""
Download a RawBillDocument/RawMotionDocument's PDF from its `url` column and
populate the row's `file_size` (bytes) and `num_pages` columns. Does not touch
S3 - this is independent of `s3_key` upload status.
"""

from __future__ import annotations

from io import BytesIO

from loguru import logger
from pypdf import PdfReader
from pypdf.errors import PyPdfError
from sqlalchemy.orm import Session

from backend.database.raw_models import RawBillDocument, RawMotionDocument
from backend.scrapers.utils import get_url

_PDF_MAGIC = b"%PDF"


def _looks_like_pdf(data: bytes) -> bool:
    return data.startswith(_PDF_MAGIC)


def sync_document_metadata(
    db: Session, row: RawBillDocument | RawMotionDocument
) -> bool:
    """Download `row.url` and populate `file_size`/`num_pages` if missing."""
    if row.file_size is not None and row.num_pages is not None:
        return False

    response = get_url(row.url)
    if response is None:
        logger.warning(f"Failed to fetch document: {row.url}")
        return False

    data = response.content
    if not _looks_like_pdf(data):
        logger.warning(
            f"Response doesn't look like a PDF (first bytes: {data[:8]!r}): {row.url}"
        )
        return False

    pdf = BytesIO(data)
    try:
        num_pages = len(PdfReader(pdf).pages)
    except PyPdfError as exc:
        logger.warning(f"Failed to parse PDF {row.url}: {exc}")
        return False

    row.file_size = pdf.getbuffer().nbytes
    row.num_pages = num_pages
    db.flush()
    return True
