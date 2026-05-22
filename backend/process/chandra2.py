from datetime import datetime, timezone
from backend.config import settings
from backend.core.enums import TypeBillStep
from backend.database import models, raw_models
from backend.scrapers.utils import get_url
from sqlalchemy.orm import sessionmaker
from sqlalchemy import String, cast, create_engine, select

_VLLM_MANAGER = None


db_engine = create_engine(settings.DB_URL, pool_pre_ping=True)
db_session = sessionmaker(
    bind=db_engine,
    autocommit=False,
    autoflush=False,
)


def get_approved_ids(model: type) -> list[str]:
    """
    Get all approved bill_id
    """
    with db_session() as db:
        return list(db.scalars(select(model.id).where(model.bill_approved.is_(True))))


def get_approved_bill_documents(limit: int = 25):
    """
    Get approved variables from raw_bill_documents
    """
    approved_ids = get_approved_ids(models.Bill)[:limit]
    print(approved_ids)
    if not approved_ids:
        return []

    step_types = [
        TypeBillStep.PRESENTADO,
        TypeBillStep.TEXTO_SUSTITUTORIO_O_REVISION,
        TypeBillStep.AUTOGRAFA,
    ]

    step_filter = (
        select(
            models.BillStep.bill_id,
            cast(models.BillStep.step_id, String).label("step_id"),
        )
        .where(
            models.BillStep.bill_id.in_(approved_ids),
            models.BillStep.step_type.in_(step_types),
            models.BillStep.vote_step.is_(False),
        )
        .subquery()
    )

    with db_session() as db:
        return list(
            db.scalars(
                select(raw_models.RawBillDocument)
                .join(
                    step_filter,
                    (raw_models.RawBillDocument.bill_id == step_filter.c.bill_id)
                    & (raw_models.RawBillDocument.step_id == step_filter.c.step_id),
                )
                .where(raw_models.RawBillDocument.processed.is_(False))
            )
        )


def _get_vllm_manager():
    global _VLLM_MANAGER
    if _VLLM_MANAGER is None:
        from chandra.model import InferenceManager

        print("Loading Chandra OCR 2 model...")
        _VLLM_MANAGER = InferenceManager(method="vllm")
        print("Model loaded successfully.")
    return _VLLM_MANAGER


def _normalize_congreso_url(url: str) -> str:
    if url.startswith("https://wb2server.congreso.gob.pe/"):
        return url.replace(
            "https://wb2server.congreso.gob.pe/",
            "https://api.congreso.gob.pe/",
            1,
        )
    return url


def _get_images_from_pdf(pdf_source: str | bytes):
    import fitz
    from PIL import Image

    input_images = []
    if isinstance(pdf_source, (bytes, bytearray)):
        source_label = "bytes"
        pdf_context = fitz.open(stream=pdf_source, filetype="pdf")
    else:
        source_label = pdf_source
        pdf_context = fitz.open(pdf_source)

    with pdf_context as pdf_document:
        for page_num in range(len(pdf_document)):
            page = pdf_document.load_page(page_num)
            pix = page.get_pixmap(dpi=300)
            img_data = pix.samples
            img_width = pix.width
            img_height = pix.height
            pil_image = Image.frombytes("RGB", [img_width, img_height], img_data)
            input_images.append(pil_image)

    print(f"Converted {len(input_images)} page(s) from {source_label} to images.")
    return input_images


def chandra2_vllm(url: str):
    """
    Generate OCR text per page using the Chandra vLLM model.
    """
    from chandra.model.schema import BatchInputItem

    if not url or not url.startswith(("http://", "https://")):
        raise ValueError(f"Expected an HTTP(S) URL, got {url!r}")

    url = _normalize_congreso_url(url)
    response = get_url(url)
    if response is None:
        raise RuntimeError(f"Failed to download PDF from {url}")
    pdf_source = response.content

    images = _get_images_from_pdf(pdf_source)
    if not images:
        raise RuntimeError("No images rendered from PDF source")

    batch = [BatchInputItem(image=img, prompt_type="ocr_layout") for img in images]
    manager = _get_vllm_manager()
    results = manager.generate(
        batch, include_headers_footers=False, include_images=False
    )
    return [
        {"page_num": idx + 1, "text": result.markdown}
        for idx, result in enumerate(results)
    ]


def write_raw_bill_pages(
    raw_docs: list[raw_models.RawBillDocument],
    ocr_model: str = "chandra2",
) -> int:
    if not raw_docs:
        print("No raw bill documents provided.")
        return 0

    now = datetime.now(timezone.utc)
    created = 0

    with db_session() as db:
        for doc in raw_docs:
            if ocr_model != "chandra2":
                raise RuntimeError(
                    f"Unsupported OCR model: {ocr_model}. Expected 'chandra2'."
                )
            pages = chandra2_vllm(doc.url)  # replace to mock when in local
            for page in pages:
                page_num = page["page_num"]
                text = page["text"]

                existing = db.scalar(
                    select(raw_models.RawBillPage).where(
                        raw_models.RawBillPage.bill_id == doc.bill_id,
                        raw_models.RawBillPage.step_id == doc.step_id,
                        raw_models.RawBillPage.file_id == doc.file_id,
                        raw_models.RawBillPage.page_num == page_num,
                        raw_models.RawBillPage.ocr_model == ocr_model,
                    )
                )

                if existing:
                    existing.text = text
                    existing.timestamp = now
                    existing.last_update = True
                    existing.changed = False
                    existing.processed = False
                    raw_doc = db.get(
                        raw_models.RawBillDocument,
                        (doc.bill_id, doc.step_id, doc.file_id),
                    )
                    if raw_doc:
                        raw_doc.processed = True
                    continue

                db.add(
                    raw_models.RawBillPage(
                        bill_id=doc.bill_id,
                        step_id=doc.step_id,
                        file_id=doc.file_id,
                        page_num=page_num,
                        text=text,
                        ocr_model=ocr_model,
                        timestamp=now,
                        last_update=True,
                        changed=False,
                        processed=False,
                    )
                )
                raw_doc = db.get(
                    raw_models.RawBillDocument,
                    (doc.bill_id, doc.step_id, doc.file_id),
                )
                if raw_doc:
                    raw_doc.processed = True
                created += 1

        db.commit()
    return created


if __name__ == "__main__":
    approved_docs = get_approved_bill_documents()
    print("len approved docs", len(approved_docs))
    write_raw_bill_pages(approved_docs, ocr_model="chandra2")
