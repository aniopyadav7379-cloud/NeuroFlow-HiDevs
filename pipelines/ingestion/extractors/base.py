"""
Shared output type for every extractor in pipelines/ingestion/extractors/.

Every extractor — regardless of source format — normalizes to a flat list
of ExtractedPage. This is the boundary the Chunker (chunker.py) and the
rest of the ingestion pipeline (pipeline.py) depend on; nothing downstream
of extraction knows or cares whether a page came from a PDF, a DOCX
paragraph group, or a CSV row block.
"""
from dataclasses import dataclass, field


@dataclass
class ExtractedPage:
    page_number: int
    content: str
    content_type: str  # "text" | "table" | "image_description"
    metadata: dict = field(default_factory=dict)
