"""
PDF extraction: digital text via pypdfium2, OCR fallback for scanned pages,
and table extraction via pdfplumber.

Two libraries are deliberately used together here rather than picking one:
pypdfium2 is fast and accurate for text/rasterization but doesn't do table
structure detection; pdfplumber is slower but is what actually finds table
grids. Running both means a table-heavy digital PDF gets clean prose pages
*and* separate structured table pages, rather than tables mangled into
running text.
"""
import io
import logging

import pdfplumber
import pypdfium2 as pdfium
import pytesseract
from PIL import Image

from pipelines.ingestion.extractors.base import ExtractedPage
from pipelines.ingestion.extractors.markdown import rows_to_markdown_table

logger = logging.getLogger("neuroflow.ingestion.pdf")

# Below this many characters of extracted digital text, a page is treated
# as scanned (image-only) and routed to OCR instead.
SCANNED_PAGE_CHAR_THRESHOLD = 50

# Render scale used when rasterizing a scanned page for Tesseract — 2x
# roughly matches ~144 DPI, a reasonable OCR/quality-vs-speed default.
OCR_RENDER_SCALE = 2.0

TESSERACT_CONFIG = "--psm 6"  # assume a single uniform block of text


def _extract_tables_for_page(pdf_bytes: bytes, page_index: int) -> list[ExtractedPage]:
    """pdfplumber table extraction for a single page, returned as separate
    ExtractedPage entries (content_type="table") so they aren't interleaved
    with prose in the chunker."""
    pages: list[ExtractedPage] = []
    with pdfplumber.open(io.BytesIO(pdf_bytes)) as pl_pdf:
        if page_index >= len(pl_pdf.pages):
            return pages
        pl_page = pl_pdf.pages[page_index]
        tables = pl_page.extract_tables()
        for t_idx, table in enumerate(tables):
            if not table or len(table) < 2:
                continue
            md = rows_to_markdown_table(table)
            pages.append(
                ExtractedPage(
                    page_number=page_index + 1,
                    content=md,
                    content_type="table",
                    metadata={"page_number": page_index + 1, "table_index": t_idx, "source": "pdf"},
                )
            )
    return pages


def extract_pdf(pdf_bytes: bytes) -> list[ExtractedPage]:
    pages: list[ExtractedPage] = []
    pdf = pdfium.PdfDocument(pdf_bytes)

    try:
        for page_index in range(len(pdf)):
            page = pdf[page_index]
            textpage = page.get_textpage()
            text = textpage.get_text_range().strip()

            is_scanned = len(text) < SCANNED_PAGE_CHAR_THRESHOLD
            if is_scanned:
                logger.info("page %d flagged as scanned (%d chars), running OCR", page_index + 1, len(text))
                bitmap = page.render(scale=OCR_RENDER_SCALE)
                pil_image: Image.Image = bitmap.to_pil()
                text = pytesseract.image_to_string(pil_image, config=TESSERACT_CONFIG).strip()

            pages.append(
                ExtractedPage(
                    page_number=page_index + 1,
                    content=text,
                    content_type="text",
                    metadata={
                        "page_number": page_index + 1,
                        "source": "pdf",
                        "ocr": is_scanned,
                    },
                )
            )
            textpage.close()
            page.close()
    finally:
        pdf.close()

    # Table extraction runs as a second pass over the same bytes (pdfplumber
    # opens its own document handle) — kept separate from the pdfium loop
    # above so a pdfplumber failure on one page can't take down text
    # extraction for the rest of the document.
    for page_index in range(len(pages)):
        try:
            pages.extend(_extract_tables_for_page(pdf_bytes, page_index))
        except Exception:
            logger.exception("table extraction failed for page %d, continuing without tables", page_index + 1)

    return pages
