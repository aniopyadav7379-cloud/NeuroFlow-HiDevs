from typing import Any

from pydantic import BaseModel


class RetrievalResult(BaseModel):
    chunk_id: str
    document_id: str
    content: str
    metadata: dict[str, Any]
    score: float

    class Config:
        # Allow extra fields if needed, but primarily use the defined ones
        extra = "allow"
