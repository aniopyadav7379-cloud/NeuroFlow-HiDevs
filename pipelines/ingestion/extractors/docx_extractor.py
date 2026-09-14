from typing import Any

from docx import Document
from docx.document import Document as _Document
from docx.oxml.table import CT_Tbl
from docx.oxml.text.paragraph import CT_P
from docx.table import Table, _Cell
from docx.text.paragraph import Paragraph

from .base import ExtractedPage


def iter_block_items(parent: Any) -> Any:  # noqa: ANN401
    """
    Yield each paragraph and table child within *parent*, in document order.
    Each returned value is an instance of either Table or Paragraph.
    """
    if isinstance(parent, _Document):
        parent_elm = parent.element.body
    elif isinstance(parent, _Cell):
        parent_elm = parent._tc
    else:
        raise ValueError("Expected _Document or _Cell")

    for child in parent_elm.iterchildren():
        if isinstance(child, CT_P):
            yield Paragraph(child, parent)
        elif isinstance(child, CT_Tbl):
            yield Table(child, parent)


def extract_docx(file_path: str) -> list[ExtractedPage]:
    doc = Document(file_path)
    pages: list[ExtractedPage] = []

    current_heading = "Document Start"
    current_level = "h1"
    current_content = []  # type: ignore
    page_counter = 1

    def flush() -> Any:  # noqa: ANN401
        nonlocal current_content, page_counter
        if current_content:
            text = "\n".join(current_content).strip()
            if text:
                pages.append(
                    ExtractedPage(
                        page_number=page_counter,
                        content=text,
                        content_type="text",
                        metadata={"level": current_level, "section": current_heading},
                    )
                )
            current_content = []
            page_counter += 1

    # Extract headers
    for section in doc.sections:
        if section.header and not section.header.is_linked_to_previous:
            for p in section.header.paragraphs:
                if p.text.strip():
                    current_content.append(p.text.strip())

    flush()  # Flush headers as a separate block

    # Reset for body
    current_heading = "Document Start"
    current_level = "h1"

    for block in iter_block_items(doc):
        if isinstance(block, Paragraph):
            style_name = block.style.name if block.style else ""
            if style_name.startswith("Heading"):
                flush()
                level_num = style_name.split()[-1]
                current_level = f"h{level_num}" if level_num.isdigit() else "h1"
                current_heading = block.text.strip()
                current_content.append(block.text.strip())
            else:
                if block.text.strip():
                    current_content.append(block.text.strip())

        elif isinstance(block, Table):
            flush()  # flush text before table

            md_table = []
            for row_idx, row in enumerate(block.rows):
                clean_row = [cell.text.replace("\n", " ").strip() for cell in row.cells]
                md_table.append("| " + " | ".join(clean_row) + " |")
                if row_idx == 0:
                    md_table.append("|" + "|".join(["---" for _ in row.cells]) + "|")

            if md_table:
                pages.append(
                    ExtractedPage(
                        page_number=page_counter,
                        content="\n".join(md_table),
                        content_type="table",
                        metadata={"level": current_level, "section": current_heading},
                    )
                )
                page_counter += 1

    flush()  # flush any remaining
    return pages
