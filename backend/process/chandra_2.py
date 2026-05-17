import warnings
import time
from transformers import AutoModelForImageTextToText, AutoProcessor
from chandra.model.hf import generate_hf
from chandra.model.schema import BatchInputItem
from chandra.output import parse_markdown
from PIL import Image
import torch
import fitz
import os
import sys
import concurrent.futures
import gc
from functools import partial

warnings.filterwarnings("ignore", category=UserWarning)

# Lazy-loaded model
_model = None
# Parallelize processing using ThreadPoolExecutor
# max_workers is set to prevent GPU Out Of Memory (OOM) errors
max_workers = 5


def _load_model():
    """Lazy load the model only when needed"""
    global _model
    if _model is None:
        print("Loading Chandra OCR 2 model...")
        _model = AutoModelForImageTextToText.from_pretrained(
            "datalab-to/chandra-ocr-2",
            dtype=torch.bfloat16,
            device_map="auto",
        )
        _model.eval()
        _model.processor = AutoProcessor.from_pretrained("datalab-to/chandra-ocr-2")
        _model.processor.tokenizer.padding_side = "left"
        print("Model loaded successfully.")
    return _model


def get_images(pdf_file: str):
    """
    Converting a PDF page to an image and processing it. The Chandra model
    expects image input
    """
    input_images = []
    try:
        pdf_document = fitz.open(pdf_file)
        for page_num in range(len(pdf_document)):
            page = pdf_document.load_page(page_num)
            pix = page.get_pixmap(dpi=300)
            img_data = pix.samples
            img_width = pix.width
            img_height = pix.height
            pil_image = Image.frombytes("RGB", [img_width, img_height], img_data)
            input_images.append(pil_image)
        pdf_document.close()
        print(f"Converted {len(input_images)} page(s) from {pdf_file} to images.")
    except Exception as e:
        print(
            f"Error processing PDF: {e}. Please ensure '{pdf_file}' exists "
            "and is a valid PDF, or provide an image file."
        )
        # Fallback if PDF conversion fails
        if not input_images:
            print(
                "No valid input image or PDF found. Please provide an image "
                "file or a PDF."
            )

    # Get the path for the raw ocr output
    base_filename = os.path.splitext(os.path.abspath(pdf_file))[0]
    raw_filename = f"{base_filename}_raw.txt"

    return input_images, raw_filename


def run_ocr(input_images, raw_filename, model):
    """
    OCR Generation & Raw Output Saving
    """
    if input_images:
        batch = [
            BatchInputItem(image=img, prompt_type="ocr_layout") for img in input_images
        ]
        results = generate_hf(batch, model)

        # Collect raw markdown from all pages
        all_raw_markdown = []
        for result in results:
            markdown = parse_markdown(
                result.raw, include_headers_footers=False, include_images=False
            )
            all_raw_markdown.append(markdown)

        raw_output_text = "\n\n--- PAGE BREAK ---\n\n".join(all_raw_markdown)

        with open(raw_filename, "w") as f:
            f.write(raw_output_text)

        print(f"Saved raw OCR results to {raw_filename}")
    else:
        print("No images to process")


def process_pdf(pdf_file, model):
    print(f"Starting: {pdf_file}")
    input_images, raw_filename = get_images(pdf_file)
    run_ocr(input_images, raw_filename, model)
    print(f"Finished: {pdf_file}\n")


def get_pdf_folder(folder):
    pdf_lst = []
    for file in os.listdir(folder):
        if file.endswith(".pdf"):
            pdf_lst.append(os.path.join(folder, file))
    return pdf_lst


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: uv run chandra_2.py <folder_path>")
        sys.exit(1)

    folder = sys.argv[1]
    pdf_lst = get_pdf_folder(folder)
    model = _load_model()

    total_start = time.time()
    with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers) as executor:
        # Map runs the function for each item in the list concurrently
        worker = partial(process_pdf, model=model)
        list(executor.map(worker, pdf_lst))
    total_elapsed_minutes = (time.time() - total_start) / 60
    print(f"All PDFs completed. Total elapsed: {total_elapsed_minutes:.2f}m")

    # delete model after running
    try:
        del _model
        del model
    except NameError:
        pass

    # del results, batch, sample_images
    gc.collect()
    torch.cuda.empty_cache()
