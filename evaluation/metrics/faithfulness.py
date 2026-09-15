import json
import logging
from typing import Any

from backend.providers.base import ChatMessage
from backend.providers.client import NeuroFlowClient
from backend.providers.router import RoutingCriteria

logger = logging.getLogger(__name__)




async def evaluate_faithfulness(
    query: str,
    answer: str,
    context: str,
    client: NeuroFlowClient,
    **kwargs: Any,  # noqa: ANN401
) -> float:
    if not answer or not answer.strip():
        return 0.0

    # Step 1: Extract claims
    extract_prompt = f"""
    Given the following answer to a query, extract all the factual claims made in the answer.
    Output ONLY a JSON array of strings, where each string is a distinct factual claim.
    If there are no factual claims, output an empty array [].
    
    Answer: {answer}
    """
    messages = [ChatMessage(role="user", content=extract_prompt)]
    criteria = RoutingCriteria(task_type="evaluation")

    try:
        extract_result = await client.chat(messages, criteria, **kwargs)
        claims_text = extract_result.content
        # Strip potential markdown formatting
        if "```json" in claims_text:
            claims_text = claims_text.split("```json")[1].split("```")[0].strip()
        elif "```" in claims_text:
            claims_text = claims_text.split("```")[1].strip()

        claims = json.loads(claims_text)
        if not isinstance(claims, list):
            claims = []
    except Exception as e:
        logger.info(f"Error extracting claims: {e}")
        return 0.0

    if not claims:
        return 1.0

    if not context or not context.strip():
        return 0.0

    # Step 2: Verify each claim
    supported_claims = 0.0

    for claim in claims:
        verify_prompt = f"""
        Context:
        {context}
        
        Claim:
        {claim}
        
        Is this claim supported by the context? Answer ONLY with "yes", "no", or "partial".
        """
        messages = [ChatMessage(role="user", content=verify_prompt)]

        try:
            # We enforce max_tokens=10, and mix in kwargs
            verify_result = await client.chat(messages, criteria, max_tokens=10, **kwargs)
            verdict = verify_result.content.strip().lower()

            if "yes" in verdict:
                supported_claims += 1.0
            elif "partial" in verdict:
                supported_claims += 0.5
        except Exception:
            pass

    return supported_claims / len(claims)
