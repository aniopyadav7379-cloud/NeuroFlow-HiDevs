"""
Image extraction: a vision-LLM description combined with any OCR'd text
found in the image itself. JPEG/PNG/WEBP in; one ExtractedPage out.
"""
import io
import logging

import pytesseract
from PIL import Image

from backend.providers.client import NeuroFlowClient
from pipelines.ingestion.extractors.base import ExtractedPage
from pipelines.ingestion.extractors.vision import describe_image

logger = logging.getLogger("neuroflow.ingestion.image")

SUPPORTED_FORMATS = {"JPEG", "PNG", "WEBP"}


async def extract_image(image_bytes: bytes, client: NeuroFlowClient, filename: str = "") -> list[ExtractedPage]:
    image = Image.open(io.BytesIO(image_bytes))
    image.load()

    fmt = (image.format or "").upper()
    if fmt not in SUPPORTED_FORMATS:
        raise ValueError(f"unsupported image format '{fmt}' (expected one of {sorted(SUPPORTED_FORMATS)})")

    # Vision description runs on the (later-resized) image via the shared
    # helper; OCR runs on the original resolution since downscaling to
    # 1024px can hurt text recognition on dense screenshots/scans.
    description = await describe_image(client, image)

    ocr_image = image.convert("RGB") if image.mode not in ("RGB", "L") else image
    ocr_text = pytesseract.image_to_string(ocr_image).strip()

    combined = description
    if ocr_text:
        combined = f"{description}\n\nText found in image: {ocr_text}"

    return [
        ExtractedPage(
            page_number=1,
            content=combined,
            content_type="image_description",
            metadata={
                "source": "image",
                "filename": filename,
                "format": fmt,
                "original_size": image.size,
                "has_ocr_text": bool(ocr_text),
            },
        )
    ]
