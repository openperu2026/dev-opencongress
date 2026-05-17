import os
import tempfile
from unittest.mock import patch, MagicMock

import pytest


@pytest.fixture
def temp_directory():
    """Create a temporary directory for testing"""
    with tempfile.TemporaryDirectory() as tmpdir:
        yield tmpdir


@pytest.mark.parametrize(
    "files, expected_count",
    [
        (["doc1.pdf", "doc2.pdf"], 2),
        (["readme.txt"], 0),
        ([], 0),
    ],
)
def test_get_pdf_folder(temp_directory, files, expected_count):
    """Test that get_pdf_folder filters PDF files correctly"""
    from backend.process.chandra_2 import get_pdf_folder

    for filename in files:
        with open(os.path.join(temp_directory, filename), "w") as f:
            f.write("test")

    result = get_pdf_folder(temp_directory)
    assert len(result) == expected_count
    assert all(f.endswith(".pdf") for f in result)


@patch("backend.process.chandra_2.fitz")
def test_get_images_error_handling(mock_fitz, temp_directory):
    """Test that get_images handles errors gracefully"""
    from backend.process.chandra_2 import get_images

    mock_fitz.open.side_effect = Exception("PDF Error")

    pdf_file = os.path.join(temp_directory, "bad.pdf")
    with open(pdf_file, "w") as f:
        f.write("test")

    images, raw_filename = get_images(pdf_file)

    assert images == []
    assert raw_filename.endswith("_raw.txt")


@patch("backend.process.chandra_2._load_model")
@patch("backend.process.chandra_2.generate_hf")
@patch("backend.process.chandra_2.parse_markdown")
def test_run_ocr(mock_parse, mock_generate, mock_load_model, temp_directory):
    """Test that run_ocr writes output file correctly"""
    from backend.process.chandra_2 import run_ocr
    from PIL import Image

    # Mock the model to avoid loading it
    mock_model = MagicMock()
    mock_load_model.return_value = mock_model

    test_image = Image.new("RGB", (100, 100), color="white")
    mock_result = MagicMock()
    mock_result.raw = "content"
    mock_generate.return_value = [mock_result]
    mock_parse.return_value = "parsed"

    raw_filename = os.path.join(temp_directory, "test_raw.txt")
    run_ocr([test_image], raw_filename)

    assert os.path.exists(raw_filename)
    with open(raw_filename, "r") as f:
        assert "parsed" in f.read()


def test_run_ocr_empty_list(temp_directory):
    """Test that run_ocr skips empty image list"""
    from backend.process.chandra_2 import run_ocr

    raw_filename = os.path.join(temp_directory, "output.txt")
    run_ocr([], raw_filename)
    assert not os.path.exists(raw_filename)
