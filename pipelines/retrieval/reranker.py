import asyncio
import time

from opentelemetry import trace

from backend.monitoring.metrics import retrieval_latency
from backend.providers.base import ChatMessage
from backend.providers.client import NeuroFlowClient
from backend.providers.router import RoutingCriteria

from .models import RetrievalResult

tracer = trace.get_tracer(__name__)


class CrossEncoderReranker:
    def __init__(self, client: NeuroFlowClient) -> None:
        self.client = client

    async def rerank(
        self,
        query: str,
        results: list[RetrievalResult],
        top_n: int = 40,
        pipeline_id: str | None = None,
        run_id: str | None = None,
    ) -> list[RetrievalResult]:
        start_time = time.time()
        with tracer.start_as_current_span("retrieval.rerank") as span:
            if pipeline_id:
                span.set_attribute("pipeline_id", pipeline_id)
            if run_id:
                span.set_attribute("run_id", run_id)
            # Take top_n candidates
            candidates = results[:top_n]

            # We need to rate each candidate
            tasks = []
            for candidate in candidates:
                tasks.append(self._score_candidate(query, candidate))

            scored_candidates = await asyncio.gather(*tasks)

            # Sort descending by new score
            scored_candidates.sort(key=lambda x: x.score, reverse=True)

            span.set_attribute("chunk_count", len(scored_candidates))

            duration = time.time() - start_time
            retrieval_latency.labels(strategy="rerank").observe(duration)

            return scored_candidates

    async def _score_candidate(self, query: str, result: RetrievalResult) -> RetrievalResult:
        prompt = f"Rate the relevance of this passage to the query on a scale of 0-10. Query: {query}. Passage: {result.content}. Return only the number."  # noqa: E501

        messages = [ChatMessage(role="user", content=prompt)]

        criteria = RoutingCriteria(task_type="evaluation")

        try:
            llm_result = await self.client.chat(messages, criteria)
            # Try to parse the number
            content = llm_result.content.strip()
            # Clean up potential extra text around the number
            score_str = "".join(c for c in content if c.isdigit() or c == ".")
            score = float(score_str) if score_str else 0.0

            result.score = score
        except Exception:
            # Fallback if LLM fails or parsing fails
            result.score = 0.0

        return result
