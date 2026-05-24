from __future__ import annotations

import json
import re
import time
import unicodedata
from datetime import datetime, timezone

import fitz
import pandas as pd
import pytesseract
import requests
from PIL import Image
from pytesseract import Output
from sqlalchemy import create_engine, select, cast, Integer
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session, sessionmaker

from backend.config import settings
from backend.database import raw_models
from backend.database.models import BillStep
from backend.database.raw_models import RawBillDocument

# --- OCR config ---

DPI = 300
OCR_LANG = "spa+eng"

TESSERACT_CONFIG = "--psm 6 -c preserve_interword_spaces=1"

COLUMN_BANDS = ((0.04, 0.34), (0.34, 0.64), (0.64, 0.94))
HEADER_FRACTION = 0.20
TABLE_TOP_FRACTION = {"attendance": 0.10, "voting": 0.15}
TABLE_BOTTOM_FRACTION = 0.80

SCRAPE_HEADERS = {
    "User-Agent": "Mozilla/5.0",
    "Accept": "application/pdf,*/*",
    "Referer": "https://wb2server.congreso.gob.pe/",
    "Accept-Language": "en-US,en;q=0.9",
}

# --- Token constants ---

PARTY_CODES = {
    "APP",
    "PL",
    "FP",
    "AP",
    "SP",
    "SP-PM",
    "PP",
    "RP",
    "JP",
    "AP-PIS",
    "PB",
    "PD",
    "NA",
}

PARTY_CORRECTIONS = {
    "FE": "FP",
    "F2": "FP",
    "3P": "JP",
    "1P": "JP",
    "IP": "JP",
    "OP": "JP",
    "0P": "JP",
    "N4": "NA",
    "AP-P1S": "AP-PIS",
    "AP-P1": "AP-PIS",
}

ATTENDANCE_CODES = {
    "PRE",
    "AUS",
    "LO",
    "LE",
    "LP",
    "COM",
    "CEI",
    "JP",
    "BAN",
    "SUS",
    "F",
}
YES_TOKENS = {"SI", "S1", "ST", "SE", "SL"}
NO_TOKENS = {"NO", "N0", "MO", "YO"}
PRESIDING_TOKENS = {"***", "WEE", "HAD", "VEN", "VEM", "VON"}

# --- Text helpers ---


def normalize_text(value: object) -> str:
    text = str(value).strip()
    text = unicodedata.normalize("NFKD", text)
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    return text.upper()


def standardize_token(value: object) -> str:
    text = normalize_text(value)
    text = text.replace("—", "-").replace("–", "-").replace("~", "-")
    return re.sub(r"[^A-Z0-9+*\-=/-]+", "", text)


def reconstruct_names(tokens: list[str]) -> str:
    return " ".join(t for t in tokens if t.strip())


def standardize_party(token: object) -> str | None:
    value = standardize_token(token)
    value = PARTY_CORRECTIONS.get(value, value)
    return value if value in PARTY_CODES else None


def looks_like_party(token: object) -> bool:
    value = standardize_token(token)
    return standardize_party(value) is not None or ("-" in value and len(value) <= 8)


def standardize_attendance(token: object) -> str | None:
    value = standardize_token(token)
    if value in {"AUS", "AUSENTES"}:
        return "AUS"
    return value if value in ATTENDANCE_CODES else None


def has_plus(token: object) -> bool:
    value = standardize_token(token)
    return "+" in value or value in {"44", "444", "4++", "++4"}


def has_dash(token: object) -> bool:
    value = standardize_token(token)
    return "-" in value or "=" in value


# --- PDF / OCR ---


def render_pdf_pages(source: bytes, dpi: int = DPI) -> list[Image.Image]:
    pages = []
    with fitz.open(stream=source, filetype="pdf") as document:
        for page in document:
            pixmap = page.get_pixmap(dpi=dpi, alpha=False)
            pages.append(
                Image.frombytes("RGB", (pixmap.width, pixmap.height), pixmap.samples)
            )
    return pages


def ocr_df(image: Image.Image, *, min_conf: float = 0) -> pd.DataFrame:
    data = pytesseract.image_to_data(
        image,
        lang=OCR_LANG,
        config=TESSERACT_CONFIG,
        output_type=Output.DATAFRAME,
    )
    data = data.dropna(subset=["text"])
    data = data[data["text"].astype(str).str.strip() != ""]
    return data[data["conf"].fillna(-1) >= min_conf].copy()


def text_from_data(data: pd.DataFrame) -> str:
    if data.empty:
        return ""
    return " ".join(normalize_text(token) for token in data["text"].tolist())


def detect_page_type(page_img: Image.Image) -> str:
    w, h = page_img.size
    header = page_img.crop((0, 0, w, int(h * HEADER_FRACTION)))
    header_text = text_from_data(ocr_df(header, min_conf=0))

    if "ASISTENCIA" in header_text:
        return "attendance"
    if "VOTACION" in header_text:
        if "COMISION PERMANENTE" in header_text:
            return "permanent_commission"
        return "voting"
    return "other"


def tokens_with_positions(line: pd.DataFrame) -> list[dict]:
    rows = []
    for row in line.itertuples(index=False):
        text = str(row.text).strip()
        if text:
            rows.append(
                {
                    "text": text,
                    "left": int(row.left),
                    "top": int(row.top),
                    "width": int(row.width),
                }
            )
    return rows


# --- Parsing ---


def extract_vote(tokens: list[str]) -> tuple[str | None, list[str]]:
    if not tokens:
        return None, []

    last = standardize_token(tokens[-1]).strip(".")

    if last in PRESIDING_TOKENS:
        return "PRESIDING", tokens[:-1]
    if last in {"ABST", "ABSTENCION", "ABSTEN"}:
        return "ABST", tokens[:-1]
    if last in {"SINRES", "SINRESP"}:
        return "SINRES", tokens[:-1]
    if last in {"AUS", "LO", "LE", "LP"}:
        return last, tokens[:-1]
    if last in NO_TOKENS:
        return "NO", tokens[:-1]
    if last in YES_TOKENS:
        return "SI", tokens[:-1]

    if len(tokens) >= 2:
        previous = standardize_token(tokens[-2]).strip(".")
        if previous in YES_TOKENS and has_plus(last):
            return "SI", tokens[:-2]
        if previous in NO_TOKENS and has_dash(last):
            return "NO", tokens[:-2]
        if previous in {"ABST", "ABSTENCION"}:
            return "ABST", tokens[:-1]

    return None, tokens


def parse_line(items: list[dict], page_type: str, column_width: int) -> dict | None:
    if len(items) < 2:
        return None

    first = items[0]
    if first["left"] < column_width * 0.20 and looks_like_party(first["text"]):
        party_raw = str(first["text"])
        party = standardize_party(party_raw) or standardize_token(party_raw)
        body_tokens = [str(item["text"]) for item in items[1:]]
    else:
        party_raw = None
        party = None
        body_tokens = [str(item["text"]) for item in items]

    if page_type == "attendance":
        value = standardize_attendance(body_tokens[-1]) if body_tokens else None
        if value is None:
            return None
        name_tokens = body_tokens[:-1]
        value_raw = body_tokens[-1]
    elif page_type == "voting":
        value, name_tokens = extract_vote(body_tokens)
        if value is None:
            return None
        value_raw = " ".join(body_tokens[len(name_tokens) :])
    else:
        return None

    name = reconstruct_names(name_tokens)
    if len(name.split()) < 2:
        return None

    return {
        "party": party,
        "party_raw": party_raw,
        "name": name,
        "value": value,
        "value_raw": value_raw,
    }


def extract_page(image: Image.Image, source_pdf: str, page_number: int) -> list[dict]:
    page_type = detect_page_type(image)
    if page_type not in {"attendance", "voting"}:
        return [{"page_type": page_type}]

    rows: list[dict] = []
    table_top = int(image.height * TABLE_TOP_FRACTION[page_type])
    table_bottom = int(image.height * TABLE_BOTTOM_FRACTION)

    for column_index, (start, end) in enumerate(COLUMN_BANDS, start=1):
        x0 = int(image.width * start)
        x1 = int(image.width * end)
        column_image = image.crop((x0, 0, x1, image.height))
        data = ocr_df(column_image, min_conf=0)

        for line_index, (_, line) in enumerate(
            data.groupby(["block_num", "par_num", "line_num"], sort=True), start=1
        ):
            line_top = int(line["top"].min())
            if line_top < table_top or line_top > table_bottom:
                continue

            line_text = text_from_data(line)
            if "RESULTADOS" in line_text or "GRUPO PARLAMENTARIO" in line_text:
                continue

            parsed = parse_line(tokens_with_positions(line), page_type, x1 - x0)
            if parsed is None:
                continue

            rows.append(
                {
                    "source_pdf": source_pdf,
                    "page": page_number,
                    "page_type": page_type,
                    "column": column_index,
                    "line_index": line_index,
                    "line_top": line_top,
                    **parsed,
                }
            )

    return rows


# --- Ingest ---


def ingest_document(doc, db: Session) -> None:
    resp = requests.get(
        doc.url, headers=SCRAPE_HEADERS, timeout=30, allow_redirects=True
    )
    resp.raise_for_status()

    now = datetime.now(timezone.utc)

    for page_num, image in enumerate(render_pdf_pages(resp.content), start=1):
        page_rows = extract_page(image, doc.file_id, page_num)
        page_type = page_rows[0].get("page_type") if page_rows else None
        if page_type not in ("attendance", "voting"):
            continue

        stmt = (
            insert(raw_models.RawBillPage)
            .values(
                bill_id=doc.bill_id,
                step_id=str(doc.step_id),
                file_id=str(doc.file_id),
                page_num=page_num,
                text=json.dumps(page_rows),
                ocr_model="tesseract-votes",
                timestamp=now,
                last_update=True,
                changed=False,
                processed=False,
            )
            .on_conflict_do_nothing()
        )
        db.execute(stmt)


def main() -> None:
    engine = create_engine(settings.DB_URL, pool_pre_ping=True)
    DBSession = sessionmaker(bind=engine, autocommit=False, autoflush=False)

    with DBSession() as session:
        results = session.execute(
            select(
                BillStep.step_id,
                BillStep.bill_id,
                BillStep.step_date,
                RawBillDocument.file_id,
                RawBillDocument.url,
            )
            .join(
                RawBillDocument,
                BillStep.step_id == cast(RawBillDocument.step_id, Integer),
            )
            .where(BillStep.vote_step.is_(True))
        ).all()

    total = len(results)
    print(f"Found {total} documents to scrape")

    with DBSession() as db:
        start_total = time.perf_counter()
        for i, doc in enumerate(results, start=1):
            start = time.perf_counter()
            ingest_document(doc, db)
            db.commit()
            elapsed = time.perf_counter() - start
            print(f"[{i}/{total}] {doc.file_id} — {elapsed:.1f}s")

        total_elapsed = time.perf_counter() - start_total
        print(
            f"\nDone: {total} docs in {total_elapsed:.1f}s ({total_elapsed / total:.1f}s avg)"
        )


if __name__ == "__main__":
    main()
