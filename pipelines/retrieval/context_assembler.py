from typing import Any

import tiktoken
from opentelemetry import trace

from .models import RetrievalResult

tracer = trace.get_tracer(__name__)


class ContextAssembler:
    def __init__(self, token_budget: int = 4000, model_name: str = "gpt-3.5-turbo") -> None:
        self.token_budget = token_budget
        try:
            self.encoding = tiktoken.encoding_for_model(model_name)
        except Exception:
            # Fallback
            self.encoding = tiktoken.get_encoding("cl100k_base")

    def assemble(
        self,
        results: list[RetrievalResult],
        pipeline_id: str | None = None,
        run_id: str | None = None,
    ) -> dict[str, Any]:
        with tracer.start_as_current_span("retrieval.assemble") as span:
            if pipeline_id:
                span.set_attribute("pipeline_id", pipeline_id)
            if run_id:
                span.set_attribute("run_id", run_id)
            context_str = ""
            current_tokens = 0
            chunks_used = []
            sources = []  # type: ignore

            for i, result in enumerate(results):
                # Try to get filename from metadata, fallback to document_id
                doc_name = result.metadata.get("filename", f"doc_{result.document_id}")

                # Get page or section if available
                page = result.metadata.get("page_number")
                if page:
                    source_header = f"[Source {len(sources) + 1} — {doc_name}, page {page}]\n"
                else:
                    source_header = f"[Source {len(sources) + 1} — {doc_name}]\n"

                chunk_text = f"{source_header}{result.content}\n\n"

                # Count tokens
                chunk_tokens = len(self.encoding.encode(chunk_text))

                # If it fits, add it. Never truncate mid-sentence.
                if current_tokens + chunk_tokens <= self.token_budget:
                    context_str += chunk_text
                    current_tokens += chunk_tokens
                    chunks_used.append(result.chunk_id)
                    sources.append(
                        {"document_id": result.document_id, "filename": doc_name, "page": page}
                    )
                else:
                    # If a chunk doesn't fit, skip it entirely to avoid mid-sentence truncation
                    continue

            span.set_attribute("chunk_count", len(chunks_used))
            span.set_attribute("token_count", current_tokens)

            return {
                "context": context_str.strip(),
                "chunks_used": chunks_used,
                "total_tokens": current_tokens,
                "sources": sources,
            }
