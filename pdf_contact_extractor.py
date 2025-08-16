"""Extract contact data from scanned PDFs using multiple libraries.

This script demonstrates how to parse contact information from
quotation and invoice PDFs using a variety of PDF and OCR libraries.
For each PDF provided it runs every extraction method and writes the
results to a single CSV file with method-specific column prefixes so
the outputs can be compared.

The script focuses on the contact data fields requested for the
project.  Each extraction method returns a block of raw text; simple
regular-expression patterns then attempt to capture billing and
shipping details as well as document metadata.

This tool is intentionally modular so additional parsing rules or
extraction backends can be added later.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import re
import uuid
from pathlib import Path
from typing import Callable, Dict, Iterable, List


# ---------------------------------------------------------------------------
# Text extraction helpers for each library
# ---------------------------------------------------------------------------

def extract_text_layoutparser(pdf_path: Path) -> str:
    """Extract text using layout-parser with Tesseract OCR.

    Returns an empty string if the library or OCR engine is unavailable.
    """
    try:
        import layoutparser as lp  # type: ignore
        from pdf2image import convert_from_path  # type: ignore
    except Exception:
        return ""

    pages = convert_from_path(str(pdf_path))
    ocr_agent = lp.TesseractAgent(languages="eng")
    texts: List[str] = []
    for page in pages:
        layout = ocr_agent.detect(page)
        texts.append("\n".join(block.text for block in layout))
    return "\n".join(texts)


def extract_text_pymupdf4llm(pdf_path: Path) -> str:
    """Extract text using pymupdf4llm's markdown helper."""
    try:
        import pymupdf4llm  # type: ignore
    except Exception:
        return ""

    try:
        return pymupdf4llm.to_markdown(str(pdf_path))
    except Exception:
        return ""


def extract_text_llamaindex(pdf_path: Path) -> str:
    """Extract text using LlamaIndex's built-in PDF reader."""
    try:
        from llama_index.core import SimpleDirectoryReader  # type: ignore
    except Exception:
        return ""

    try:
        docs = SimpleDirectoryReader(input_files=[str(pdf_path)]).load_data()
        return "\n".join(doc.text for doc in docs)
    except Exception:
        return ""


def extract_text_unstructured(pdf_path: Path) -> str:
    """Extract text using the unstructured library."""
    try:
        from unstructured.partition.pdf import partition_pdf  # type: ignore
    except Exception:
        return ""

    try:
        elements = partition_pdf(filename=str(pdf_path))
        return "\n".join(el.text for el in elements if getattr(el, "text", ""))
    except Exception:
        return ""


def extract_text_pypdf(pdf_path: Path) -> str:
    """Extract text using PyPDF."""
    try:
        from pypdf import PdfReader  # type: ignore
    except Exception:
        return ""

    try:
        reader = PdfReader(str(pdf_path))
        return "\n".join(page.extract_text() or "" for page in reader.pages)
    except Exception:
        return ""


def extract_text_pdfplumber(pdf_path: Path) -> str:
    """Extract text using pdfplumber."""
    try:
        import pdfplumber  # type: ignore
    except Exception:
        return ""

    try:
        with pdfplumber.open(str(pdf_path)) as pdf:
            return "\n".join(page.extract_text() or "" for page in pdf.pages)
    except Exception:
        return ""


def extract_text_ocrmypdf(pdf_path: Path) -> str:
    """Extract text using OCRmyPDF followed by PyPDF."""
    try:
        import tempfile
        import ocrmypdf  # type: ignore
        from pypdf import PdfReader  # type: ignore
    except Exception:
        return ""
    try:
        with tempfile.NamedTemporaryFile(suffix=".pdf") as tmp:
            ocrmypdf.ocr(str(pdf_path), tmp.name, force_ocr=True, skip_text=True)
            reader = PdfReader(tmp.name)
            return "\n".join(page.extract_text() or "" for page in reader.pages)
    except Exception:
        return ""


def extract_text_easyocr(pdf_path: Path) -> str:
    """Extract text using EasyOCR on PDF images."""
    try:
        from pdf2image import convert_from_path  # type: ignore
        import easyocr  # type: ignore
        import numpy as np  # type: ignore
    except Exception:
        return ""
    try:
        reader = easyocr.Reader(["en"])
        images = convert_from_path(str(pdf_path))
        texts: List[str] = []
        for img in images:
            results = reader.readtext(np.array(img), detail=0)
            texts.append("\n".join(results))
        return "\n".join(texts)
    except Exception:
        return ""


def extract_text_paddleocr(pdf_path: Path) -> str:
    """Extract text using PaddleOCR."""
    try:
        from pdf2image import convert_from_path  # type: ignore
        from paddleocr import PaddleOCR  # type: ignore
        import numpy as np  # type: ignore
    except Exception:
        return ""
    try:
        ocr = PaddleOCR(use_angle_cls=True, lang="en")
        images = convert_from_path(str(pdf_path))
        texts: List[str] = []
        for img in images:
            result = ocr.ocr(np.array(img), cls=True)
            page_text: List[str] = []
            for line in result:
                if line and isinstance(line, list):
                    page_text.append(line[1][0])
            texts.append("\n".join(page_text))
        return "\n".join(texts)
    except Exception:
        return ""


def extract_text_pdfminer(pdf_path: Path) -> str:
    """Extract text using pdfminer.six."""
    try:
        from pdfminer.high_level import extract_text  # type: ignore
    except Exception:
        return ""
    try:
        return extract_text(str(pdf_path))
    except Exception:
        return ""


def extract_text_pypdfium2(pdf_path: Path) -> str:
    """Extract text using pypdfium2."""
    try:
        import pypdfium2 as pdfium  # type: ignore
    except Exception:
        return ""
    try:
        pdf = pdfium.PdfDocument(str(pdf_path))
        texts: List[str] = []
        for page in pdf:
            textpage = page.get_textpage()
            texts.append(textpage.get_text_range())
        return "\n".join(texts)
    except Exception:
        return ""


def extract_text_camelot(pdf_path: Path) -> str:
    """Extract text from tables using Camelot."""
    try:
        import camelot  # type: ignore
    except Exception:
        return ""
    try:
        tables = camelot.read_pdf(str(pdf_path), pages="1-end")
        texts: List[str] = []
        for table in tables:
            texts.append("\n".join(" ".join(row) for row in table.data))
        return "\n".join(texts)
    except Exception:
        return ""


def extract_text_tabula(pdf_path: Path) -> str:
    """Extract text from tables using tabula-py."""
    try:
        import tabula  # type: ignore
    except Exception:
        return ""
    try:
        dfs = tabula.read_pdf(str(pdf_path), pages="all")
        texts: List[str] = []
        for df in dfs:
            texts.append("\n".join(" ".join(map(str, row)) for row in df.values))
        return "\n".join(texts)
    except Exception:
        return ""


def extract_text_deepdoctection(pdf_path: Path) -> str:
    """Placeholder for deepdoctection-based extraction."""
    try:
        import deepdoctection  # type: ignore
    except Exception:
        return ""
    return ""


def extract_text_doctr(pdf_path: Path) -> str:
    """Extract text using DocTR."""
    try:
        from doctr.io import DocumentFile  # type: ignore
        from doctr.models import ocr_predictor  # type: ignore
    except Exception:
        return ""
    try:
        doc = DocumentFile.from_pdf(str(pdf_path))
        predictor = ocr_predictor(pretrained=True)
        result = predictor(doc)
        return result.export_text()  # type: ignore[no-any-return]
    except Exception:
        return ""


def extract_text_invoice2data(pdf_path: Path) -> str:
    """Extract text using invoice2data."""
    try:
        from invoice2data import extract_data  # type: ignore
    except Exception:
        return ""
    try:
        data = extract_data(str(pdf_path))
        if not data:
            return ""
        return "\n".join(f"{k}: {v}" for k, v in data.items())
    except Exception:
        return ""


def extract_text_aws_textract(pdf_path: Path) -> str:
    """Extract text using AWS Textract."""
    try:
        import boto3  # type: ignore
    except Exception:
        return ""
    try:
        client = boto3.client("textract")
        with open(pdf_path, "rb") as f:
            response = client.detect_document_text(Document={"Bytes": f.read()})
        return "\n".join(
            block["Text"]
            for block in response.get("Blocks", [])
            if block.get("BlockType") == "LINE"
        )
    except Exception:
        return ""


def extract_text_google_docai(pdf_path: Path) -> str:
    """Extract text using Google Document AI."""
    try:
        from google.cloud import documentai  # type: ignore
    except Exception:
        return ""
    try:
        client = documentai.DocumentProcessorServiceClient()
        name = "projects/PROJECT_ID/locations/LOCATION/processors/PROCESSOR_ID"
        with open(pdf_path, "rb") as f:
            raw_document = documentai.RawDocument(content=f.read(), mime_type="application/pdf")
        request = documentai.ProcessRequest(name=name, raw_document=raw_document)
        result = client.process_document(request=request)
        return result.document.text or ""
    except Exception:
        return ""


EXTRACTION_METHODS: Dict[str, Callable[[Path], str]] = {
    "layoutparser": extract_text_layoutparser,
    "pymupdf4llm": extract_text_pymupdf4llm,
    "llamaindex": extract_text_llamaindex,
    "unstructured": extract_text_unstructured,
    "pypdf": extract_text_pypdf,
    "pdfplumber": extract_text_pdfplumber,
    "ocrmypdf": extract_text_ocrmypdf,
    "easyocr": extract_text_easyocr,
    "paddleocr": extract_text_paddleocr,
    "pdfminer": extract_text_pdfminer,
    "pypdfium2": extract_text_pypdfium2,
    "camelot": extract_text_camelot,
    "tabula": extract_text_tabula,
    "deepdoctection": extract_text_deepdoctection,
    "doctr": extract_text_doctr,
    "invoice2data": extract_text_invoice2data,
    "aws_textract": extract_text_aws_textract,
    "google_docai": extract_text_google_docai,
}


# ---------------------------------------------------------------------------
# Parsing helpers
# ---------------------------------------------------------------------------

CONTACT_FIELDS: Iterable[str] = [
    "document_type",
    "document_number",
    "document_quote_date",
    "document_est_ship_date",
    "document_invoice_date",
    "bill_to",
    "bill_company",
    "bill_street",
    "bill_street2",
    "bill_city",
    "bill_state",
    "bill_zip",
    "bill_attn",
    "ship_to",
    "ship_company",
    "ship_street",
    "ship_street2",
    "ship_city",
    "ship_state",
    "ship_zip",
    "ship_attn",
    "customer_phone",
    "customer_phone_raw",
    "customer_fax",
    "sales_order_number",
    "rfq_number",
    "purchase_order_number",
    "payment_terms",
    "notes",
]


def detect_document_type(text: str) -> str:
    if re.search(r"\bquotation\b", text, re.IGNORECASE):
        return "quotation"
    if re.search(r"\binvoice\b", text, re.IGNORECASE):
        return "invoice"
    return "unknown"


def extract_field(pattern: str, text: str) -> str:
    match = re.search(pattern, text, re.IGNORECASE)
    return match.group(1).strip() if match else ""


def parse_contact_data(text: str) -> Dict[str, str]:
    data: Dict[str, str] = {}
    data["document_type"] = detect_document_type(text)
    data["document_number"] = extract_field(r"(?:quote|invoice)\s+number\s*:?\s*(\S+)", text)
    data["document_quote_date"] = extract_field(r"quote\s+date\s*:?\s*(\S+)", text)
    data["document_invoice_date"] = extract_field(r"invoice\s+date\s*:?\s*(\S+)", text)
    data["document_est_ship_date"] = extract_field(r"est(?:imated)?\s+ship\s+date\s*:?\s*(\S+)", text)

    # Billing block
    bill_block = extract_field(r"bill\s+to\s*:?\s*(.*?)(?:ship\s+to|$)", text)
    data["bill_to"] = bill_block

    # Shipping block
    ship_block = extract_field(r"ship\s+to\s*:?\s*(.*)", text)
    data["ship_to"] = ship_block

    # Contact numbers
    data["customer_phone"] = extract_field(r"phone\s*:?\s*([\d\-\(\)\s]+)", text)
    data["customer_phone_raw"] = re.sub(r"[^0-9]", "", data["customer_phone"])
    data["customer_fax"] = extract_field(r"fax\s*:?\s*([\d\-\(\)\s]+)", text)

    # Placeholders for additional fields
    for field in CONTACT_FIELDS:
        data.setdefault(field, "")
    return data


def compute_page_image_sha256(pdf_path: Path) -> str:
    try:
        import fitz  # type: ignore
    except Exception:
        return ""
    try:
        doc = fitz.open(str(pdf_path))
        page = doc.load_page(0)
        pix = page.get_pixmap()
        return hashlib.sha256(pix.tobytes()).hexdigest()
    except Exception:
        return ""


# ---------------------------------------------------------------------------
# CSV generation
# ---------------------------------------------------------------------------

def build_headers() -> List[str]:
    headers = ["document_id", "source_file", "renamed_file", "page_image_sha256"]
    for method in EXTRACTION_METHODS:
        for field in CONTACT_FIELDS:
            headers.append(f"{method}_{field}")
    return headers


def process_pdf(pdf_path: Path, csv_path: Path, headers: List[str]) -> None:
    row: Dict[str, str] = {
        "document_id": str(uuid.uuid4()),
        "source_file": pdf_path.name,
        "renamed_file": "",
        "page_image_sha256": compute_page_image_sha256(pdf_path),
    }

    for method_name, extractor in EXTRACTION_METHODS.items():
        text = extractor(pdf_path)
        data = parse_contact_data(text)
        for field in CONTACT_FIELDS:
            row[f"{method_name}_{field}"] = data.get(field, "")

    file_exists = csv_path.exists()
    with csv_path.open("a", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=headers)
        if not file_exists:
            writer.writeheader()
        writer.writerow(row)


# ---------------------------------------------------------------------------
# Command-line interface
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(description="Extract contact data from PDFs")
    parser.add_argument("pdfs", nargs="+", help="Paths to PDF files")
    parser.add_argument(
        "--output", "-o", default="contact_data.csv", help="Destination CSV file"
    )
    args = parser.parse_args()

    headers = build_headers()
    csv_path = Path(args.output)
    for pdf in args.pdfs:
        process_pdf(Path(pdf), csv_path, headers)


if __name__ == "__main__":  # pragma: no cover
    main()
