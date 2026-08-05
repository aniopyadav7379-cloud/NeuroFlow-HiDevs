"""
Citation post-processing: find every [Source N] reference in a generated
response and resolve it against the actual context window that was sent
to the model (AssembledContext.sources from Task 35's context_assembler).

Any [Source N] where N doesn't correspond to a real source in that window
is a hallucinated citation — the model referencing a source number that
was never provided — and gets flagged rather than silently dropped or
silently trusted.
"""
import re
from dataclasses import dataclass

_CITATION_RE = re.compile(r"\[Source (\d+)\]")


@dataclass
class Citation:
    reference: str  # "Source 1"
    chunk_id: str | None
    document_name: str | None
    page_number: int | None
    content_preview: str  # first 100 chars of the cited chunk
    invalid_citation: bool = False


def parse_citations(response_text: str, sources: list[dict]) -> list[Citation]:
    """`sources` is AssembledContext.sources — 1-indexed by construction
    (source i in the list is "[Source i+1]" in the context headers), so
    resolving a citation is just an index lookup, and anything outside
    that range is definitionally a source number the model made up.
    Dedupes by source number, keeping first-appearance order — a response
    that cites [Source 1] three times produces one Citation, matching the
    `done` event's citations list shape in the task spec.
    """
    seen: list[int] = []
    seen_set: set[int] = set()
    for match in _CITATION_RE.finditer(response_text):
        n = int(match.group(1))
        if n not in seen_set:
            seen_set.add(n)
            seen.append(n)

    citations: list[Citation] = []
    for n in seen:
        idx = n - 1
        if 0 <= idx < len(sources):
            s = sources[idx]
            citations.append(
                Citation(
                    reference=f"Source {n}",
                    chunk_id=s.get("chunk_id"),
                    document_name=s.get("document_name"),
                    page_number=s.get("page"),
                    content_preview=s.get("content_preview", ""),
                    invalid_citation=False,
                )
            )
        else:
            citations.append(
                Citation(
                    reference=f"Source {n}",
                    chunk_id=None,
                    document_name=None,
                    page_number=None,
                    content_preview="",
                    invalid_citation=True,
                )
            )

    return citations
