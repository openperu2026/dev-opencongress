from datetime import datetime, UTC

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from backend import OcrModel
from backend.database.crud.pipeline_bills import find_raw_bill_pages
from backend.database.raw_models import Base, RawBillDocument, RawBillPage


@pytest.fixture
def session():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        yield session
    Base.metadata.drop_all(engine)


def _seed_document(session, *, bill_id="PL-1", step_id="10", file_id="100"):
    now = datetime.now(UTC)
    session.add(
        RawBillDocument(
            timestamp=now,
            bill_id=bill_id,
            step_id=step_id,
            file_id=file_id,
            step_date=now,
            url="https://example.com/doc.pdf",
            last_update=True,
        )
    )


def _page(*, page_num, ocr_model, text, last_update=True, **ids):
    return RawBillPage(
        timestamp=datetime.now(UTC),
        bill_id=ids.get("bill_id", "PL-1"),
        step_id=ids.get("step_id", "10"),
        file_id=ids.get("file_id", "100"),
        page_num=page_num,
        text=text,
        ocr_model=ocr_model,
        last_update=last_update,
    )


def test_returns_only_requested_ocr_model(session):
    """A document with pages from two OCR models yields only the requested one."""
    _seed_document(session)
    session.add_all(
        [
            _page(page_num=1, ocr_model=OcrModel.CHANDRA.value, text="chandra p1"),
            _page(page_num=2, ocr_model=OcrModel.CHANDRA.value, text="chandra p2"),
            _page(page_num=1, ocr_model=OcrModel.TESSERACT.value, text="tess p1"),
        ]
    )
    session.commit()

    pages = find_raw_bill_pages(session, "PL-1", "10", "100")

    assert [p.ocr_model for p in pages] == [OcrModel.CHANDRA.value] * 2
    assert [p.text for p in pages] == ["chandra p1", "chandra p2"]


def test_defaults_to_chandra(session):
    """Bills default to the chandra2 pages without an explicit argument."""
    _seed_document(session)
    session.add_all(
        [
            _page(page_num=1, ocr_model=OcrModel.CHANDRA.value, text="chandra"),
            _page(page_num=1, ocr_model=OcrModel.TESSERACT.value, text="tesseract"),
        ]
    )
    session.commit()

    pages = find_raw_bill_pages(session, "PL-1", "10", "100")

    assert len(pages) == 1
    assert pages[0].text == "chandra"


def test_explicit_ocr_model_override(session):
    """An explicit ocr_model argument selects that model's pages instead."""
    _seed_document(session)
    session.add_all(
        [
            _page(page_num=1, ocr_model=OcrModel.CHANDRA.value, text="chandra"),
            _page(page_num=1, ocr_model=OcrModel.TESSERACT.value, text="tesseract"),
        ]
    )
    session.commit()

    pages = find_raw_bill_pages(
        session, "PL-1", "10", "100", ocr_model=OcrModel.TESSERACT.value
    )

    assert len(pages) == 1
    assert pages[0].text == "tesseract"


def test_pages_ordered_by_page_num(session):
    """Pages come back ordered by page_num regardless of insert order."""
    _seed_document(session)
    session.add_all(
        [
            _page(page_num=3, ocr_model=OcrModel.CHANDRA.value, text="p3"),
            _page(page_num=1, ocr_model=OcrModel.CHANDRA.value, text="p1"),
            _page(page_num=2, ocr_model=OcrModel.CHANDRA.value, text="p2"),
        ]
    )
    session.commit()

    pages = find_raw_bill_pages(session, "PL-1", "10", "100")

    assert [p.page_num for p in pages] == [1, 2, 3]


def test_excludes_stale_pages(session):
    """Pages not flagged last_update are excluded."""
    _seed_document(session)
    session.add_all(
        [
            _page(page_num=1, ocr_model=OcrModel.CHANDRA.value, text="current"),
            _page(
                page_num=2,
                ocr_model=OcrModel.CHANDRA.value,
                text="stale",
                last_update=False,
            ),
        ]
    )
    session.commit()

    pages = find_raw_bill_pages(session, "PL-1", "10", "100")

    assert [p.text for p in pages] == ["current"]
