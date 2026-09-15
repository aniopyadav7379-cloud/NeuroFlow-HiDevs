import logging
from typing import Any

from backend.providers.base import ChatMessage
from backend.providers.client import NeuroFlowClient
from backend.providers.router import RoutingCriteria

logger = logging.getLogger(__name__)




async def evaluate_context_precision(
    query: str,
    chunks: list[str],
    answer: str,
    client: NeuroFlowClient,
    **kwargs: Any,  # noqa: ANN401
) -> float:
    if not chunks:
        return 0.0

    criteria = RoutingCriteria(task_type="evaluation")

    useful_flags = []

    for i, chunk in enumerate(chunks):
        prompt = (
            "Given the following query and answer, was this retrieved passage useful "
            "in generating the answer?\n"
            'Answer ONLY with "yes" or "no".\n'
            f"\nQuery: {query}\n"
            f"Passage: {chunk}\n"
            f"Answer: {answer}\n"
        )  # noqa: E501
        messages = [ChatMessage(role="user", content=prompt)]

        try:
            result = await client.chat(messages, criteria, max_tokens=10, **kwargs)
            verdict = result.content.strip().lower()

            if "yes" in verdict:
                useful_flags.append(1.0)
            else:
                useful_flags.append(0.0)
        except Exception as e:
            logger.info(f"Error checking chunk usefulness: {e}")
            useful_flags.append(0.0)

    # Compute rank-weighted proportion:
    # sum(useful[i] * (1/i) for i in ranks) / sum(1/i for i in ranks)
    # ranks are 1-indexed

    numerator = 0.0
    denominator = 0.0

    for idx, flag in enumerate(useful_flags):
        rank = idx + 1
        weight = 1.0 / rank
        numerator += flag * weight
        denominator += weight

    if denominator == 0.0:
        return 0.0

    return numerator / denominator
