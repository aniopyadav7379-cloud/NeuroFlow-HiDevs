"""
PPTX extraction (stretch goal): slide text, speaker notes, and vision-LLM
description of embedded images/diagrams — one ExtractedPage per slide.

Honest limitation: python-pptx reads the PPTX XML; it does not render
slides to pixels. True full-slide rasterization (matching exactly what a
viewer sees, including native shapes/SmartArt/theme rendering) needs an
actual rendering engine — e.g. `soffice --headless --convert-to png`
(LibreOffice) — which isn't part of this pipeline's dependency set. What
this module does instead: extract every embedded picture shape on a slide
via python-pptx + Pillow, and if a slide has one or more such images (the
common case for "this slide has a diagram"), send those images to the
vision LLM for description. A slide built entirely from native PowerPoint
shapes (SmartArt, charts, freeform shapes) with no embedded picture will
not get a visual description under this approach — flagged in that slide's
metadata (`rasterized: false`) so it's visible in the data rather than
silently missing.
"""
import io
import logging

from PIL import Image
from pptx import Presentation
from pptx.enum.shapes import MSO_SHAPE_TYPE

from backend.providers.client import NeuroFlowClient
from pipelines.ingestion.extractors.base import ExtractedPage
from pipelines.ingestion.extractors.vision import describe_image

logger = logging.getLogger("neuroflow.ingestion.pptx")


def _slide_text(slide) -> str:
    parts = []
    for shape in slide.shapes:
        if shape.has_text_frame and shape.text_frame.text.strip():
            parts.append(shape.text_frame.text.strip())
    return "\n".join(parts)


def _slide_notes(slide) -> str:
    if slide.has_notes_slide and slide.notes_slide.notes_text_frame:
        return slide.notes_slide.notes_text_frame.text.strip()
    return ""


def _embedded_images(slide) -> list[Image.Image]:
    images = []
    for shape in slide.shapes:
        if shape.shape_type == MSO_SHAPE_TYPE.PICTURE:
            try:
                images.append(Image.open(io.BytesIO(shape.image.blob)))
            except Exception:
                logger.exception("failed to decode embedded picture shape, skipping")
    return images


async def extract_pptx(pptx_bytes: bytes, client: NeuroFlowClient) -> list[ExtractedPage]:
    prs = Presentation(io.BytesIO(pptx_bytes))
    pages: list[ExtractedPage] = []

    for slide_index, slide in enumerate(prs.slides, start=1):
        text = _slide_text(slide)
        notes = _slide_notes(slide)
        images = _embedded_images(slide)

        visual_description = ""
        if images:
            descriptions = []
            for img in images:
                try:
                    descriptions.append(await describe_image(client, img))
                except Exception:
                    logger.exception("vision description failed for slide %d image, skipping", slide_index)
            visual_description = "\n".join(descriptions)

        content_parts = []
        if text:
            content_parts.append(text)
        if visual_description:
            content_parts.append(f"Slide visuals: {visual_description}")
        if notes:
            content_parts.append(f"Speaker notes: {notes}")

        pages.append(
            ExtractedPage(
                page_number=slide_index,
                content="\n\n".join(content_parts),
                content_type="text",
                metadata={
                    "source": "pptx",
                    "slide_number": slide_index,
                    "has_notes": bool(notes),
                    "embedded_image_count": len(images),
                    "rasterized": False,  # see module docstring
                },
            )
        )

    return pages
