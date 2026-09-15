import logging
from typing import Any

import numpy as np

from backend.providers.base import ChatMessage
from backend.providers.client import NeuroFlowClient
from backend.providers.router import RoutingCriteria

logger = logging.getLogger(__name__)




async def evaluate_answer_relevance(
    query: str,
    answer: str,
    client: NeuroFlowClient,
    **kwargs: Any,  # noqa: ANN401
) -> float:
    if not answer or not answer.strip():
        return 0.0

    # Step 1: Generate questions
    gen_prompt = (
        "Given the following answer, generate 3 distinct questions that an oracle would ask "
        "if they received this answer.\n"
        "Output ONLY the questions, one per line. Do not include numbering or extra text.\n"
        f"\nAnswer: {answer}\n"
    )
    messages = [ChatMessage(role="user", content=gen_prompt)]
    criteria = RoutingCriteria(task_type="evaluation")

    try:
        gen_result = await client.chat(messages, criteria, **kwargs)
        questions_text = gen_result.content.strip()
        # Parse into a list, stripping empty lines
        generated_questions = [q.strip() for q in questions_text.split("\n") if q.strip()]

        # Fallback if generation went weird
        if not generated_questions:
            return 0.0

        # Limit to 5 just in case
        generated_questions = generated_questions[:5]
    except Exception as e:
        logger.info(f"Error generating questions: {e}")
        return 0.0

    # Step 2: Embed queries
    texts_to_embed = [query] + generated_questions
    try:
        embeddings = await client.embed(texts_to_embed)
    except Exception as e:
        logger.info(f"Error embedding questions: {e}")
        return 0.0

    query_emb = np.array(embeddings[0])
    gen_embs = np.array(embeddings[1:])

    # Step 3: Compute mean cosine similarity
    similarities = []
    norm_q = np.linalg.norm(query_emb)

    for g_emb in gen_embs:
        norm_g = np.linalg.norm(g_emb)
        if norm_q > 0 and norm_g > 0:
            sim = np.dot(query_emb, g_emb) / (norm_q * norm_g)
            similarities.append(sim)

    if not similarities:
        return 0.0

    mean_sim = float(np.mean(similarities))

    # Clamp to [0, 1]
    return max(0.0, min(1.0, mean_sim))
