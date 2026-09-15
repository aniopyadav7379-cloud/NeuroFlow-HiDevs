import logging
import re
from typing import Any

from backend.providers.base import ChatMessage
from backend.providers.client import NeuroFlowClient
from backend.providers.router import RoutingCriteria

logger = logging.getLogger(__name__)




async def evaluate_context_recall(
    query: str,
    chunks: list[str],
    answer: str,
    client: NeuroFlowClient,
    **kwargs: Any,  # noqa: ANN401
) -> float:
    if not answer or not answer.strip():
        return 0.0

    # Split the answer into sentences. A simple regex approach works for basic sentences.
    # E.g. split on . ? ! followed by a space or end of string.
    sentences = re.split(r"(?<=[.!?]) +(?=[A-Z])|(?<=[.!?])$", answer.strip())
    sentences = [s.strip() for s in sentences if s.strip()]

    if not sentences:
        return 0.0

    context = "\n".join(chunks)
    criteria = RoutingCriteria(task_type="evaluation")

    attributable_sentences = 0.0

    for sentence in sentences:
        prompt = f"""
        Context:
        {context}
        
        Sentence:
        {sentence}
        
        Can this sentence be attributed to the provided context? 
        Answer ONLY with "yes" or "no".
        """
        messages = [ChatMessage(role="user", content=prompt)]

        try:
            result = await client.chat(messages, criteria, max_tokens=10, **kwargs)
            verdict = result.content.strip().lower()

            if "yes" in verdict:
                attributable_sentences += 1.0
        except Exception as e:
            logger.info(f"Error checking sentence attribution: {e}")

    return attributable_sentences / len(sentences)
