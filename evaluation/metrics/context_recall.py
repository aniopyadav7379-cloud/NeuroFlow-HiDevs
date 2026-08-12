"""
Context recall: was the retrieved context sufficient to support the whole
answer, sentence by sentence?
"""
import asyncio
import logging

from backend.providers.client import NeuroFlowClient
from opentelemetry import trace

from evaluation.metrics._common import ask, parse_yes_no, split_sentences

_tracer = trace.get_tracer("neuroflow.evaluation")
logger = logging.getLogger("neuroflow.evaluation.context_recall")

SENTENCE_ATTRIBUTION_PROMPT = (
    "Context:\n{context}\n\n"
    "Sentence: {sentence}\n\n"
    "Can this sentence be attributed to (i.e. is it supported by) the context above? "
    "Answer exactly one of: yes, no."
)


async def _check_sentence_attributable(sentence: str, context: str, client: NeuroFlowClient) -> float:
    raw = await ask(client, SENTENCE_ATTRIBUTION_PROMPT.format(context=context, sentence=sentence))
    return parse_yes_no(raw)


async def _evaluate_context_recall_inner(query: str, chunks: list[str], answer: str, client: NeuroFlowClient) -> float:
    sentences = split_sentences(answer)
    if not sentences:
        return 0.0

    context = "\n\n".join(chunks)
    if not context.strip():
        return 0.0

    scores = await asyncio.gather(*(_check_sentence_attributable(s, context, client) for s in sentences))
    return sum(scores) / len(sentences)


async def evaluate_context_recall(query: str, chunks: list[str], answer: str, client: NeuroFlowClient) -> float:
    with _tracer.start_as_current_span("evaluation.context_recall") as span:
        span.set_attribute("query_length", len(query))
        score = await _evaluate_context_recall_inner(query, chunks, answer, client)
        span.set_attribute("score", score)
        return score
