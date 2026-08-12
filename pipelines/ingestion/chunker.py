"""
Chunking: three strategies, auto-selected per ExtractedPage based on
content type and document shape (docs/adr/002-chunking-strategy.md covers
the design rationale at the architecture level; this module is the
concrete implementation).

Selection rules (checked in order):
  1. content_type == "table"        -> fixed_size (tables are already a
                                        natural unit; splitting fixed-size
                                        just caps pathologically huge ones)
  2. docx source with headings      -> hierarchical
  3. PDF source with > 50 pages     -> semantic
  4. default                        -> fixed_size
"""
import logging
import re
from dataclasses import dataclass, field

import tiktoken

from pipelines.ingestion.extractors.base import ExtractedPage

logger = logging.getLogger("neuroflow.ingestion.chunker")

TOKEN_ENCODING = "cl100k_base"

FIXED_CHUNK_TOKENS = 512
FIXED_CHUNK_OVERLAP_TOKENS = 64
BOUNDARY_SEARCH_WINDOW_FRACTION = 0.10  # search +/-10% of target size for a sentence boundary

SEMANTIC_SIMILARITY_THRESHOLD = 0.7

_SENTENCE_END_RE = re.compile(r"(?<=[.!?])\s+")

_encoding = None


def _get_encoding():
    """Lazy singleton — avoids a network call to fetch tiktoken's BPE
    vocab file at import time for any code that merely imports this
    module. First real call pays the cost once; see Dockerfile for the
    build-time pre-cache that avoids paying it at request time in prod."""
    global _encoding
    if _encoding is None:
        _encoding = tiktoken.get_encoding(TOKEN_ENCODING)
    return _encoding


@dataclass
class Chunk:
    text: str
    token_count: int
    metadata: dict = field(default_factory=dict)


# ── strategy selection ──────────────────────────────────────────────────

def select_strategy(page: ExtractedPage, *, source_type: str, page_count: int, doc_has_headings: bool) -> str:
    if page.content_type == "table":
        return "fixed_size"
    if source_type == "docx" and doc_has_headings:
        return "hierarchical"
    if source_type == "pdf" and page_count > 50:
        return "semantic"
    return "fixed_size"


# ── fixed_size ───────────────────────────────────────────────────────────

def _sentence_boundaries(text: str) -> list[int]:
    """Character offsets right after each sentence-ending punctuation run."""
    return [m.start() for m in _SENTENCE_END_RE.finditer(text)]


def _snap_to_sentence_boundary(text: str, target_char: int, window: int) -> int:
    """Find the sentence boundary nearest to target_char within +/-window
    chars. Falls back to target_char itself (a hard token-count cut) if no
    boundary exists in range, so a doc with no punctuation still chunks."""
    boundaries = _sentence_boundaries(text)
    candidates = [b for b in boundaries if target_char - window <= b <= target_char + window]
    if not candidates:
        return target_char
    return min(candidates, key=lambda b: abs(b - target_char))


def chunk_fixed_size(
    text: str,
    metadata: dict,
    chunk_tokens: int = FIXED_CHUNK_TOKENS,
    overlap_tokens: int = FIXED_CHUNK_OVERLAP_TOKENS,
) -> list[Chunk]:
    if not text.strip():
        return []

    encoding = _get_encoding()
    token_ids = encoding.encode(text)
    if len(token_ids) <= chunk_tokens:
        return [Chunk(text=text, token_count=len(token_ids), metadata=dict(metadata))]

    chunks: list[Chunk] = []
    start_tok = 0
    window_chars = max(1, int(len(text) * BOUNDARY_SEARCH_WINDOW_FRACTION))

    while start_tok < len(token_ids):
        end_tok = min(start_tok + chunk_tokens, len(token_ids))

        # Decode the candidate token window back to text, then snap the
        # *end* to the nearest sentence boundary so we never split
        # mid-sentence — per spec, within 10% of the target size.
        candidate_text = encoding.decode(token_ids[start_tok:end_tok])
        target_char = len(candidate_text)
        snapped_char = _snap_to_sentence_boundary(candidate_text, target_char, window_chars)
        final_text = candidate_text[:snapped_char].strip() if snapped_char > 0 else candidate_text.strip()
        if not final_text:
            final_text = candidate_text.strip()

        final_tokens = encoding.encode(final_text)
        chunks.append(Chunk(text=final_text, token_count=len(final_tokens), metadata=dict(metadata)))

        if end_tok >= len(token_ids):
            break

        # Advance by (this chunk's real token length - overlap), so the
        # next chunk starts overlap_tokens back from where this one ended.
        advance = max(1, len(final_tokens) - overlap_tokens)
        start_tok += advance

    return chunks


# ── semantic ─────────────────────────────────────────────────────────────

def _split_sentences(text: str) -> list[str]:
    sentences = _SENTENCE_END_RE.split(text.strip())
    return [s.strip() for s in sentences if s.strip()]


def _cosine_similarity(a: list[float], b: list[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b))
    norm_a = sum(x * x for x in a) ** 0.5
    norm_b = sum(y * y for y in b) ** 0.5
    if norm_a == 0 or norm_b == 0:
        return 0.0
    return dot / (norm_a * norm_b)


async def chunk_semantic(
    text: str,
    metadata: dict,
    embed_fn,
    similarity_threshold: float = SEMANTIC_SIMILARITY_THRESHOLD,
) -> list[Chunk]:
    """embed_fn: async callable, list[str] -> list[list[float]] (typically
    NeuroFlowClient.embed). Splits where adjacent-sentence similarity drops
    below `similarity_threshold`, i.e. at natural topic shifts."""
    sentences = _split_sentences(text)
    if len(sentences) <= 1:
        return chunk_fixed_size(text, metadata) if text.strip() else []

    embeddings = await embed_fn(sentences)

    boundaries = [0]  # sentence indices where a new chunk starts
    for i in range(1, len(sentences)):
        sim = _cosine_similarity(embeddings[i - 1], embeddings[i])
        if sim < similarity_threshold:
            boundaries.append(i)
    boundaries.append(len(sentences))

    chunks: list[Chunk] = []
    for start, end in zip(boundaries[:-1], boundaries[1:]):
        chunk_text = " ".join(sentences[start:end]).strip()
        if not chunk_text:
            continue
        token_count = len(_get_encoding().encode(chunk_text))
        chunks.append(Chunk(text=chunk_text, token_count=token_count, metadata=dict(metadata)))

    return chunks


# ── hierarchical ─────────────────────────────────────────────────────────

def chunk_hierarchical(pages: list[ExtractedPage]) -> list[Chunk]:
    """For heading-structured documents (docx with Heading N styles — see
    docx_extractor.has_headings): each top-level (h1) section becomes a
    parent chunk; everything under it (h2+ and body text) up to the next
    h1 becomes child chunks referencing the parent via metadata."""
    chunks: list[Chunk] = []
    parent_index: int | None = None
    parent_id_counter = 0

    for page in pages:
        level = page.metadata.get("level")
        if level == "h1":
            parent_id_counter += 1
            parent_index = parent_id_counter
            chunks.append(
                Chunk(
                    text=page.content,
                    token_count=len(_get_encoding().encode(page.content)),
                    metadata={**page.metadata, "hierarchy_role": "parent", "parent_id": parent_index},
                )
            )
        else:
            for sub_chunk in chunk_fixed_size(page.content, page.metadata):
                sub_chunk.metadata.update(
                    {"hierarchy_role": "child", "parent_id": parent_index}
                )
                chunks.append(sub_chunk)

    return chunks
