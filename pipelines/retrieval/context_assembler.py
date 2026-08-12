"""
Context window assembly: takes the top-K reranked chunks and formats them
into a single context string, respecting a token budget and never cutting
a chunk mid-sentence (a chunk that doesn't fit whole is trimmed to the
largest whole-sentence prefix that does, rather than being sliced raw or
dropped outright, so a slightly-too-big top result still contributes).
"""
import re
from dataclasses import dataclass, field

import tiktoken

TOKEN_ENCODING = "cl100k_base"
DEFAULT_TOKEN_BUDGET = 4000

_SENTENCE_END_RE = re.compile(r"(?<=[.!?])\s+")

_encoding = None


def _get_encoding():
    """Lazy singleton — see pipelines/ingestion/chunker.py for the same
    pattern and the reasoning (avoid a network call at import time)."""
    global _encoding
    if _encoding is None:
        _encoding = tiktoken.get_encoding(TOKEN_ENCODING)
    return _encoding


def _count_tokens(text: str) -> int:
    return len(_get_encoding().encode(text))


def _truncate_to_sentence_boundary(text: str, max_tokens: int) -> str:
    """Returns the longest whole-sentence prefix of `text` that fits
    within max_tokens. May return "" if even the first sentence doesn't
    fit — callers should skip the chunk entirely in that case."""
    sentences = _SENTENCE_END_RE.split(text.strip())
    kept: list[str] = []
    for sentence in sentences:
        candidate = " ".join(kept + [sentence])
        if _count_tokens(candidate) > max_tokens:
            break
        kept.append(sentence)
    return " ".join(kept)


@dataclass
class AssembledContext:
    context: str
    chunks_used: list[str] = field(default_factory=list)  # chunk_ids, in the order assembled
    total_tokens: int = 0
    sources: list[dict] = field(default_factory=list)  # [{"chunk_id", "document_name", "page"}]


def _source_header(index: int, metadata: dict) -> str:
    document_name = (
        metadata.get("filename")
        or metadata.get("document_name")
        or metadata.get("source")
        or "unknown source"
    )
    page = metadata.get("page_number") or metadata.get("slide_number")
    if page is not None:
        return f"[Source {index} — {document_name}, page {page}]"
    return f"[Source {index} — {document_name}]"


def assemble_context(
    chunks,  # list[RetrievalResult], typed loosely to avoid an import cycle with retriever/reranker
    token_budget: int = DEFAULT_TOKEN_BUDGET,
) -> AssembledContext:
    """`chunks` should already be in the desired priority order (i.e. the
    reranked list) — this function fills the budget greedily in that
    order and stops, it doesn't re-rank."""
    parts: list[str] = []
    chunks_used: list[str] = []
    sources: list[dict] = []
    total_tokens = 0
    source_index = 0

    for chunk in chunks:
        source_index += 1
        header = _source_header(source_index, chunk.metadata)
        # header + blank line + content + trailing blank line between entries
        overhead_tokens = _count_tokens(header) + 2  # + newlines, counted loosely via 2 flat tokens
        remaining = token_budget - total_tokens - overhead_tokens

        if remaining <= 0:
            break

        content = chunk.content
        content_tokens = _count_tokens(content)

        if content_tokens > remaining:
            content = _truncate_to_sentence_boundary(content, remaining)
            if not content:
                # Not even one full sentence fits — skip this chunk rather
                # than emit a truncated fragment or a mid-sentence cut.
                source_index -= 1
                continue
            content_tokens = _count_tokens(content)

        entry = f"{header}\n{content}"
        parts.append(entry)
        chunks_used.append(chunk.chunk_id)
        sources.append(
            {
                "chunk_id": chunk.chunk_id,
                "document_name": chunk.metadata.get("filename") or chunk.metadata.get("source"),
                "page": chunk.metadata.get("page_number") or chunk.metadata.get("slide_number"),
                # first 100 chars of the (possibly truncated) content actually
                # included — used by pipelines/generation/citations.py so it
                # doesn't need the original RetrievalResult objects at all,
                # just this sources list.
                "content_preview": content[:100],
            }
        )
        total_tokens += content_tokens + overhead_tokens

        if total_tokens >= token_budget:
            break

    return AssembledContext(
        context="\n\n".join(parts),
        chunks_used=chunks_used,
        total_tokens=total_tokens,
        sources=sources,
    )
