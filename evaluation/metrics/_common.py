"""
Shared plumbing for evaluation/metrics/*.py — the LLM call pattern (always
task_type="evaluation", which the router (backend/providers/router.py)
hard-rules to never route to a fine-tuned model) and the small parsers
each metric needs (JSON array extraction, yes/no/partial, sentence split,
cosine similarity), kept in one place so the four metric files only
contain their actual scoring algorithm.
"""
import json
import logging
import re

from backend.providers.base import ChatMessage
from backend.providers.client import NeuroFlowClient
from backend.providers.router import RoutingCriteria

logger = logging.getLogger("neuroflow.evaluation.metrics")

EVAL_MAX_COST_PER_CALL = 0.001


async def ask(client: NeuroFlowClient, prompt: str) -> str:
    result = await client.chat(
        [ChatMessage(role="user", content=prompt)],
        RoutingCriteria(task_type="evaluation", max_cost_per_call=EVAL_MAX_COST_PER_CALL),
    )
    return result.content.strip()


def parse_json_array(text: str) -> list:
    cleaned = re.sub(r"^```(?:json)?\s*|\s*```$", "", text.strip(), flags=re.MULTILINE).strip()
    try:
        data = json.loads(cleaned)
        if isinstance(data, list):
            return data
    except json.JSONDecodeError:
        pass
    logger.warning("could not parse a JSON array from LLM output: %r", text[:200])
    return []


def parse_yes_no_partial(text: str) -> float:
    t = text.strip().lower()
    if "partial" in t:
        return 0.5
    if "yes" in t:
        return 1.0
    if "no" in t:
        return 0.0
    logger.warning("could not parse yes/no/partial from %r, defaulting to 0.0", text)
    return 0.0


def parse_yes_no(text: str) -> float:
    t = text.strip().lower()
    if "yes" in t:
        return 1.0
    if "no" in t:
        return 0.0
    logger.warning("could not parse yes/no from %r, defaulting to 0.0", text)
    return 0.0


_SENTENCE_END_RE = re.compile(r"(?<=[.!?])\s+")


def split_sentences(text: str) -> list[str]:
    return [s.strip() for s in _SENTENCE_END_RE.split(text.strip()) if s.strip()]


def cosine_similarity(a: list[float], b: list[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b))
    norm_a = sum(x * x for x in a) ** 0.5
    norm_b = sum(y * y for y in b) ** 0.5
    if norm_a == 0 or norm_b == 0:
        return 0.0
    return dot / (norm_a * norm_b)
