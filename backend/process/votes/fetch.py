import io

from openai import OpenAI

from backend.scrapers.utils import get_url


def download_pdf_bytes(url: str) -> bytes:
    """Download a document PDF, following the repo-wide convention of
    fetching fresh from the source URL rather than reading local_path/s3_key
    (see chandra2.py / bills_documents.py)."""
    response = get_url(url)
    if response is None:
        raise RuntimeError(f"Failed to download PDF from {url}")
    if not response.content.startswith(b"%PDF"):
        raise RuntimeError(f"Response from {url} is not a valid PDF")
    return response.content


def upload_pdf(client: OpenAI, pdf_bytes: bytes, filename: str) -> str:
    """Upload PDF bytes to the OpenAI Files API, returning the file_id."""
    buf = io.BytesIO(pdf_bytes)
    buf.name = filename
    uploaded = client.files.create(file=buf, purpose="user_data")
    return uploaded.id
