import base64
import io

import pytesseract
from PIL import Image

from backend.providers.base import ChatMessage
from backend.providers.client import NeuroFlowClient
from backend.providers.router import RoutingCriteria

from .base import ExtractedPage


async def extract_image(file_path: str, client: NeuroFlowClient) -> list[ExtractedPage]:
    with Image.open(file_path) as img:
        processed_img = img
        # Resize to max 1024px on longest side
        max_size = 1024
        if max(processed_img.size) > max_size:
            ratio = max_size / max(processed_img.size)
            new_size = (int(processed_img.width * ratio), int(processed_img.height * ratio))
            processed_img = processed_img.resize(new_size, Image.Resampling.LANCZOS)  # type: ignore

        # Prepare for base64 encoding
        buffered = io.BytesIO()
        img_format = processed_img.format if processed_img.format else "JPEG"

        # Convert formats if necessary for LLM compatibility
        if processed_img.mode != "RGB":
            processed_img = processed_img.convert("RGB")  # type: ignore
            img_format = "JPEG"

        processed_img.save(buffered, format=img_format)
        img_base64 = base64.b64encode(buffered.getvalue()).decode("utf-8")
        mime_type = f"image/{img_format.lower()}"

        # 1. OCR text
        ocr_text = pytesseract.image_to_string(processed_img).strip()

        # 2. Vision LLM description
        criteria = RoutingCriteria(task_type="classification", require_vision=True)
        messages = [
            ChatMessage(
                role="user",
                content=[
                    {
                        "type": "text",
                        "text": "Provide a highly detailed description of this image.",
                    },
                    {
                        "type": "image_url",
                        "image_url": {"url": f"data:{mime_type};base64,{img_base64}"},
                    },
                ],
            )
        ]

        try:
            generation = await client.chat(messages, criteria)
            description = generation.content.strip()
            model_used = generation.model
        except Exception as e:
            description = f"Failed to generate description: {e}"
            model_used = "none"

        combined_content = description
        if ocr_text:
            combined_content += f"\n\nText found in image:\n{ocr_text}"

        return [
            ExtractedPage(
                page_number=1,
                content=combined_content,
                content_type="image_description",
                metadata={"original_format": img_format, "llm_used": model_used},
            )
        ]
