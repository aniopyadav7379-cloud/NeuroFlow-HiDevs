"""
Shared "describe this image with a vision LLM" helper, used by
image_extractor.py and (for embedded slide images) pptx_extractor.py.

Routes through NeuroFlowClient / ModelRouter with require_vision=True —
extractors never import a provider module directly, same rule as
everywhere else in NeuroFlow (backend/providers/base.py).
"""
import base64
import io

from PIL import Image

from backend.providers.base import ChatMessage
from backend.providers.client import NeuroFlowClient
from backend.providers.router import RoutingCriteria

MAX_DIMENSION = 1024

DEFAULT_VISION_PROMPT = (
    "Describe this image in detail for someone who cannot see it. Cover "
    "any diagrams, charts, layouts, and the substance of any visible text "
    "or data, not just the general subject."
)


def resize_max_dimension(image: Image.Image, max_dim: int = MAX_DIMENSION) -> Image.Image:
    """Resize so the longest side is at most `max_dim`, preserving aspect
    ratio. No-op if the image is already small enough."""
    width, height = image.size
    longest = max(width, height)
    if longest <= max_dim:
        return image
    scale = max_dim / longest
    new_size = (max(1, round(width * scale)), max(1, round(height * scale)))
    return image.resize(new_size, Image.LANCZOS)


def image_to_data_url(image: Image.Image, fmt: str = "PNG") -> str:
    buf = io.BytesIO()
    image.save(buf, format=fmt)
    b64 = base64.b64encode(buf.getvalue()).decode("ascii")
    mime = f"image/{fmt.lower()}"
    return f"data:{mime};base64,{b64}"


async def describe_image(
    client: NeuroFlowClient,
    image: Image.Image,
    prompt: str = DEFAULT_VISION_PROMPT,
) -> str:
    """Resize, encode, and ask a vision-capable model to describe the
    image. Returns just the description text."""
    resized = resize_max_dimension(image)
    data_url = image_to_data_url(resized)

    messages = [
        ChatMessage(
            role="user",
            content=[
                {"type": "text", "text": prompt},
                {"type": "image_url", "image_url": {"url": data_url}},
            ],
        )
    ]
    criteria = RoutingCriteria(task_type="image_description", require_vision=True)
    result = await client.chat(messages, criteria)
    return result.content
