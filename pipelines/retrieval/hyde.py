"""
HyDE — Hypothetical Document Embeddings (stretch goal).

Instead of embedding the raw query, ask the LLM to write a plausible
*answer* to the query first, then embed that hypothetical answer instead.
The idea: a hypothetical answer is written in the same register/vocabulary
as real answer passages in the corpus, so it sits closer to them in
embedding space than a short, differently-phrased question does — often
improving dense recall, especially for terse or keyword-poor queries.

Wired into Retriever.retrieve(query, use_hyde=True) (pipelines/retrieval/
retriever.py) as a drop-in replacement for the query text used in dense
retrieval only — sparse (full-text) and metadata retrieval still use the
literal query, since HyDE is specifically a dense-embedding technique.
"""
import logging

from backend.providers.base import ChatMessage
from backend.providers.client import NeuroFlowClient
from backend.providers.router import RoutingCriteria

logger = logging.getLogger("neuroflow.retrieval.hyde")

HYDE_PROMPT = (
    "Write a short, direct passage (3-5 sentences) that answers the "
    "following question as if it were an excerpt from a reference "
    "document. Do not mention that this is hypothetical or that you are "
    "uncertain — write it as a confident, factual-sounding passage, even "
    "if you aren't sure of the exact details. This will be used only to "
    "find real documents with similar content, not shown to anyone as an "
    "actual answer.\n\nQuestion: {query}"
)

HYDE_MAX_COST_PER_CALL = 0.001


async def generate_hypothetical_answer(query: str, client: NeuroFlowClient | None) -> str | None:
    """Returns the hypothetical passage text, or None if generation fails
    (caller should fall back to embedding the raw query in that case)."""
    if client is None:
        return None
    try:
        result = await client.chat(
            [ChatMessage(role="user", content=HYDE_PROMPT.format(query=query))],
            RoutingCriteria(task_type="hyde", max_cost_per_call=HYDE_MAX_COST_PER_CALL),
        )
        text = result.content.strip()
        return text or None
    except Exception:
        logger.exception("HyDE generation failed, caller should fall back to embedding the raw query")
        return None
