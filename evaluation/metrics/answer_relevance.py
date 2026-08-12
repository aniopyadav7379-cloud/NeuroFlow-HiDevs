"""
Answer relevance: does the answer actually address what was asked? Scored
indirectly — generate plausible questions the answer could be responding
to, then measure how close those are to the real query in embedding
space. An answer that wandered off-topic generates dissimilar questions.
"""
import logging

from backend.providers.client import NeuroFlowClient
from backend.providers.router import RoutingCriteria
from opentelemetry import trace

from evaluation.metrics._common import ask, cosine_similarity, parse_json_array

_tracer = trace.get_tracer("neuroflow.evaluation")
logger = logging.getLogger("neuroflow.evaluation.answer_relevance")

QUESTION_GENERATION_PROMPT = (
    "Given the following answer, generate 3 to 5 questions that this answer "
    "could plausibly be a response to — the questions an oracle would ask "
    "if they only saw this answer. Return ONLY a JSON array of question "
    "strings, nothing else.\n\nAnswer: {answer}"
)


async def _generate_questions(answer: str, client: NeuroFlowClient) -> list[str]:
    raw = await ask(client, QUESTION_GENERATION_PROMPT.format(answer=answer))
    questions = parse_json_array(raw)
    return [q for q in questions if isinstance(q, str) and q.strip()]


async def _evaluate_answer_relevance_inner(query: str, answer: str, client: NeuroFlowClient) -> float:
    if not answer.strip():
        return 0.0

    questions = await _generate_questions(answer, client)
    if not questions:
        logger.warning("no questions generated for answer relevance scoring, defaulting to 0.0")
        return 0.0

    vectors = await client.embed([query] + questions, RoutingCriteria(task_type="embedding"))
    query_vector, question_vectors = vectors[0], vectors[1:]

    similarities = [cosine_similarity(query_vector, v) for v in question_vectors]
    mean_similarity = sum(similarities) / len(similarities)

    # Cosine similarity can be negative in principle; clamp to the 0-1
    # range this metric (and the overall_score weighting) expects.
    return max(0.0, min(1.0, mean_similarity))


async def evaluate_answer_relevance(query: str, answer: str, client: NeuroFlowClient) -> float:
    with _tracer.start_as_current_span("evaluation.answer_relevance") as span:
        span.set_attribute("query_length", len(query))
        score = await _evaluate_answer_relevance_inner(query, answer, client)
        span.set_attribute("score", score)
        return score
