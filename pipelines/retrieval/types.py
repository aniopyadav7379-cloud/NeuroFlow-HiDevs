"""Shared types for the retrieval pipeline — kept in their own module so
retriever.py, fusion.py, reranker.py, and context_assembler.py can all
import RetrievalResult without a circular import between retriever.py
(which calls fusion.reciprocal_rank_fusion) and fusion.py."""
from dataclasses import dataclass, field


@dataclass
class RetrievalResult:
    chunk_id: str
    content: str
    score: float
    metadata: dict = field(default_factory=dict)
    document_id: str | None = None
    retrieval_method: str | None = None  # "dense" | "sparse" | "metadata" | "rrf(...)"
