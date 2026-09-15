from dataclasses import dataclass
from typing import Any


@dataclass
class ExtractedPage:
    page_number: int
    content: str
    content_type: str  # "text" | "table" | "image_description"
    metadata: dict[str, Any]
