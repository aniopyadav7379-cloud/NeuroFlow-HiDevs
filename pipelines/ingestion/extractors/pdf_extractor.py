import pdfplumber
import pypdfium2 as pdfium
import pytesseract

from .base import ExtractedPage


def extract_pdf(file_path: str) -> list[ExtractedPage]:
    pages: list[ExtractedPage] = []

    # 1. Extract tables using pdfplumber
    try:
        with pdfplumber.open(file_path) as pdf:
            for i, page in enumerate(pdf.pages):
                tables = page.extract_tables()
                for t_idx, table in enumerate(tables):
                    if not table:
                        continue
                    # Convert to markdown
                    md_table = []
                    for row_idx, row in enumerate(table):
                        clean_row = [
                            str(cell).replace("\n", " ").strip() if cell else "" for cell in row
                        ]
                        md_table.append("| " + " | ".join(clean_row) + " |")
                        if row_idx == 0:
                            md_table.append("|" + "|".join(["---" for _ in row]) + "|")

                    if md_table:
                        pages.append(
                            ExtractedPage(
                                page_number=i + 1,
                                content="\n".join(md_table),
                                content_type="table",
                                metadata={"table_index": t_idx},
                            )
                        )
    except Exception as e:
        print(f"Error extracting tables from PDF: {e}")

    # 2. Extract text with pypdfium2
    try:
        pdf = pdfium.PdfDocument(file_path)

        # Extract bookmarks/TOC for chapters
        page_to_chapter = {}
        try:
            for item in pdf.get_toc():
                page_to_chapter[item.page_index + 1] = item.title
        except Exception:
            pass

        current_chapter = "Document Start"

        for i in range(len(pdf)):
            page_num = i + 1
            if page_num in page_to_chapter:
                current_chapter = page_to_chapter[page_num]

            page = pdf[i]
            text_page = page.get_textpage()
            text = text_page.get_text_bounded()

            content = text.strip() if text else ""
            ocr_used = False

            # Detect scanned page
            if len(content) < 50:
                ocr_used = True
                try:
                    bitmap = page.render(scale=2.0)
                    pil_image = bitmap.to_pil()
                    # Use pytesseract with psm 6
                    ocr_text = pytesseract.image_to_string(pil_image, config="--psm 6")
                    content = ocr_text.strip()
                except Exception as ocr_err:
                    print(f"OCR failed for page {page_num}: {ocr_err}")

            if content:
                pages.append(
                    ExtractedPage(
                        page_number=page_num,
                        content=content,
                        content_type="text",
                        metadata={"ocr_used": ocr_used, "level": "h1", "section": current_chapter},
                    )
                )
    except Exception as e:
        print(f"Error reading PDF with pypdfium2: {e}")

    # Sort pages by page_number, then text over table
    pages.sort(key=lambda p: (p.page_number, p.content_type == "table"))
    return pages
