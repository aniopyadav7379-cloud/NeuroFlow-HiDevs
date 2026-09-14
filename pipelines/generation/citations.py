import re
from dataclasses import dataclass
from typing import Any
from uuid import UUID

from opentelemetry import trace

tracer = trace.get_tracer(__name__)


@dataclass
class Citation:
    reference: str
    chunk_id: UUID
    document_name: str
    page_number: int | None
    content_preview: str


def parse_citations(
    generation: str,
    assembled_context_info: dict[str, Any],
    pipeline_id: str | None = None,
    run_id: str | None = None,
) -> list[dict[str, Any]]:
    """
    Parses [Source N] patterns from the generation and maps them back to the context.
    assembled_context_info is the output of ContextAssembler.assemble(), which includes:
    - 'sources': list of RetrievalResult
    """
    with tracer.start_as_current_span("generation.citation_parse") as span:
        if pipeline_id:
            span.set_attribute("pipeline_id", pipeline_id)
        if run_id:
            span.set_attribute("run_id", run_id)
        parsed_citations = []

        # Find all unique [Source N] occurrences
        pattern = r"\[Source\s+(\d+)\]"
        matches = set(re.findall(pattern, generation))

        sources_list = assembled_context_info.get("raw_results", [])

        for match in matches:
            n = int(match)
            reference = f"Source {n}"

            # Check if invalid
            if n < 1 or n > len(sources_list):
                parsed_citations.append({"reference": reference, "invalid_citation": True})
                continue

            # Map back to the chunk (N is 1-indexed)
            result = sources_list[n - 1]

            doc_name = result.metadata.get("filename", f"doc_{result.document_id}")
            page_num = result.metadata.get("page_number")

            preview = result.content[:100]

            citation = Citation(
                reference=reference,
                chunk_id=UUID(result.chunk_id)
                if isinstance(result.chunk_id, str)
                else result.chunk_id,
                document_name=doc_name,
                page_number=page_num,
                content_preview=preview,
            )

            # Convert dataclass to dict for JSON serialization
            citation_dict = {
                "reference": citation.reference,
                "chunk_id": str(citation.chunk_id),
                "document_name": citation.document_name,
                "page_number": citation.page_number,
                "content_preview": citation.content_preview,
            }
            parsed_citations.append(citation_dict)  # type: ignore

        span.set_attribute("citation_count", len(parsed_citations))

        # Sort for deterministic output
        return sorted(parsed_citations, key=lambda x: int(x["reference"].split(" ")[1]))
