"""
Faithfulness: are the answer's claims grounded in the retrieved context?
"""
import asyncio
import logging

from backend.providers.client import NeuroFlowClient
from evaluation.metrics._common import ask, parse_json_array, parse_yes_no_partial

logger = logging.getLogger("neuroflow.evaluation.faithfulness")

CLAIM_EXTRACTION_PROMPT = (
    "List every distinct factual statement (claim) made in the following answer, "
    "as a JSON array of strings. Each element should be one self-contained claim. "
    "Return ONLY the JSON array, nothing else.\n\nAnswer: {answer}"
)

CLAIM_SUPPORT_PROMPT = (
    "Context:\n{context}\n\n"
    "Claim: {claim}\n\n"
    "Is this claim supported by the context above? Answer exactly one of: yes, no, partial."
)


async def _extract_claims(answer: str, client: NeuroFlowClient) -> list[str]:
    raw = await ask(client, CLAIM_EXTRACTION_PROMPT.format(answer=answer))
    claims = parse_json_array(raw)
    return [c for c in claims if isinstance(c, str) and c.strip()]


async def _check_claim_supported(claim: str, context: str, client: NeuroFlowClient) -> float:
    raw = await ask(client, CLAIM_SUPPORT_PROMPT.format(context=context, claim=claim))
    return parse_yes_no_partial(raw)


async def evaluate_faithfulness(query: str, answer: str, context: str, client: NeuroFlowClient) -> float:
    if not context.strip():
        # No context to ground anything in — an answer that makes claims
        # against empty context is definitionally unfaithful. (An empty
        # answer against empty context is a degenerate case we also score
        # 0.0 here rather than special-casing it as "vacuously faithful";
        # there's nothing to evaluate favorably either way.)
        return 0.0

    claims = await _extract_claims(answer, client)
    if not claims:
        # No factual claims made at all (e.g. "I don't know based on the
        # provided context") — nothing to hallucinate, so this is
        # faithful by default rather than penalized.
        return 1.0

    scores = await asyncio.gather(*(_check_claim_supported(c, context, client) for c in claims))
    return sum(scores) / len(claims)
