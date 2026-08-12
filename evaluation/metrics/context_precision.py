"""
Context precision: were the retrieved chunks actually useful, weighted so
usefulness earlier in the ranking counts for more (a useful chunk at rank
1 says more about retrieval quality than a useful one buried at rank 20).
"""
import asyncio
import logging

from backend.providers.client import NeuroFlowClient
from opentelemetry import trace

from evaluation.metrics._common import ask, parse_yes_no

_tracer = trace.get_tracer("neuroflow.evaluation")
logger = logging.getLogger("neuroflow.evaluation.context_precision")

CHUNK_USEFULNESS_PROMPT = (
    "Query: {query}\n\n"
    "Passage: {chunk}\n\n"
    "Answer given to the user: {answer}\n\n"
    "Was this passage useful in generating the answer above? Answer exactly one of: yes, no."
)


async def _check_chunk_useful(query: str, chunk: str, answer: str, client: NeuroFlowClient) -> float:
    raw = await ask(client, CHUNK_USEFULNESS_PROMPT.format(query=query, chunk=chunk, answer=answer))
    return parse_yes_no(raw)


async def _evaluate_context_precision_inner(query: str, chunks: list[str], answer: str, client: NeuroFlowClient) -> float:
    if not chunks:
        return 0.0

    usefulness = await asyncio.gather(*(_check_chunk_useful(query, c, answer, client) for c in chunks))

    # rank is 1-indexed (task spec: sum(useful[i] * (1/i)) for i in ranks —
    # 1-indexed avoids a division by zero at rank 0).
    weights = [1.0 / rank for rank in range(1, len(chunks) + 1)]
    numerator = sum(u * w for u, w in zip(usefulness, weights))
    denominator = sum(weights)

    return numerator / denominator if denominator else 0.0


async def evaluate_context_precision(query: str, chunks: list[str], answer: str, client: NeuroFlowClient) -> float:
    with _tracer.start_as_current_span("evaluation.context_precision") as span:
        span.set_attribute("query_length", len(query))
        score = await _evaluate_context_precision_inner(query, chunks, answer, client)
        span.set_attribute("score", score)
        return score
