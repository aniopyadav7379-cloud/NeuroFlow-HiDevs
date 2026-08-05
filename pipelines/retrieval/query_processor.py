"""
Query processing: the step before retrieval runs at all.

Three independent pieces of work happen here, all off the raw user query:
  - expand_query: LLM-generated alternative phrasings, retrieved in parallel
    with the original (broadens dense recall for queries phrased unlike the
    source documents)
  - extract_metadata_filters: heuristic detection of implicit filters
    ("2023", "about climate change") -> Postgres WHERE-clause-ready dict
  - classify_query_type: factual / analytical / comparative / procedural,
    consumed by context assembly (Task 36) and generation prompting later

Both expand_query and classify_query_type call the LLM (via NeuroFlowClient)
and have a keyword-heuristic fallback so query processing degrades instead
of hard-failing if the LLM call errors — retrieval should still run on the
raw query rather than blocking on this step.
"""
import asyncio
import logging
import re
from dataclasses import dataclass, field
from backend.providers.base import ChatMessage
from backend.providers.client import NeuroFlowClient
from backend.providers.router import RoutingCriteria

logger = logging.getLogger("neuroflow.retrieval.query_processor")

QUERY_TYPES = ("factual", "analytical", "comparative", "procedural")

EXPANSION_PROMPT = (
    "Generate 2 to 3 alternative phrasings of the following search query. "
    "Each phrasing should preserve the original meaning but use different "
    "wording, so it can surface documents phrased differently than the "
    "original query. Return ONLY the phrasings, one per line, no numbering, "
    "no extra commentary.\n\nQuery: {query}"
)

CLASSIFICATION_PROMPT = (
    "Classify the following search query into exactly one of these types: "
    "factual, analytical, comparative, procedural. "
    "- factual: asks for a specific fact or definition "
    "- analytical: asks why something happens or for an explanation of a mechanism "
    "- comparative: asks to compare two or more things "
    "- procedural: asks how to do something, a series of steps "
    "Return ONLY the single type word, nothing else.\n\nQuery: {query}"
)

# Heuristic fallback keyword sets, used if the LLM call fails or no client
# is available (e.g. offline unit tests) — deliberately simple, this is a
# degrade path, not the primary classifier.
_COMPARATIVE_KEYWORDS = re.compile(r"\b(vs\.?|versus|compare|compared to|difference between)\b", re.I)
_PROCEDURAL_KEYWORDS = re.compile(r"^\s*(how (do|can|to)|steps? (to|for)|guide to)\b", re.I)
_ANALYTICAL_KEYWORDS = re.compile(r"\b(why|how does .* work|explain|analyz[es]|mechanism)\b", re.I)

_YEAR_RE = re.compile(r"\b(19|20)\d{2}\b")
_TOPIC_RE = re.compile(r"\b(?:about|on|regarding|concerning)\s+([a-z0-9][\w\s\-]{2,40})", re.I)
# trims trailing filler words a naive capture would otherwise swallow
_TOPIC_TRAILING_STOPWORDS = re.compile(
    r"\s+\b(from|in|during|published|written|dated)\b.*$", re.I
)


@dataclass
class ProcessedQuery:
    original_query: str
    expanded_queries: list[str] = field(default_factory=list)
    metadata_filters: dict = field(default_factory=dict)
    query_type: str = "factual"

    @property
    def all_queries(self) -> list[str]:
        """Original + expansions, deduplicated, original first."""
        seen = {self.original_query}
        out = [self.original_query]
        for q in self.expanded_queries:
            if q not in seen:
                seen.add(q)
                out.append(q)
        return out


def extract_metadata_filters(query: str) -> dict:
    """Heuristic extraction — deliberately regex-based (not LLM-based) so
    it's fast, free, and deterministic on every query, including the vast
    majority that carry no filters at all. Handles the two filter kinds
    the task spec calls out explicitly: a 4-digit year, and an "about X" /
    "on X" / "regarding X" topic phrase.
    """
    filters: dict = {}

    year_match = _YEAR_RE.search(query)
    if year_match:
        filters["year"] = int(year_match.group(0))

    topic_match = _TOPIC_RE.search(query)
    if topic_match:
        topic = topic_match.group(1).strip()
        topic = _TOPIC_TRAILING_STOPWORDS.sub("", topic).strip()
        # Drop a leading/trailing year token that the topic regex may have
        # swept in (e.g. "about 2023 climate change" -> topic="climate change")
        topic = _YEAR_RE.sub("", topic).strip()
        if topic:
            filters["topic"] = topic.lower()

    return filters


def _heuristic_classify(query: str) -> str:
    if _PROCEDURAL_KEYWORDS.search(query):
        return "procedural"
    if _COMPARATIVE_KEYWORDS.search(query):
        return "comparative"
    if _ANALYTICAL_KEYWORDS.search(query):
        return "analytical"
    return "factual"


async def classify_query_type(query: str, client: NeuroFlowClient | None) -> str:
    if client is None:
        return _heuristic_classify(query)

    try:
        result = await client.chat(
            [ChatMessage(role="user", content=CLASSIFICATION_PROMPT.format(query=query))],
            RoutingCriteria(task_type="query_classification", max_cost_per_call=0.001),
        )
        answer = result.content.strip().lower()
        for qt in QUERY_TYPES:
            if qt in answer:
                return qt
        logger.warning("query classification returned unrecognized type %r, falling back to heuristic", answer)
        return _heuristic_classify(query)
    except Exception:
        logger.exception("query classification LLM call failed, falling back to heuristic")
        return _heuristic_classify(query)


async def expand_query(query: str, client: NeuroFlowClient | None) -> list[str]:
    if client is None:
        return []

    try:
        result = await client.chat(
            [ChatMessage(role="user", content=EXPANSION_PROMPT.format(query=query))],
            RoutingCriteria(task_type="query_expansion", max_cost_per_call=0.002),
        )
        lines = [
            re.sub(r"^[\d.\-\)\s]+", "", line).strip()  # strip "1. " / "- " style prefixes
            for line in result.content.strip().splitlines()
        ]
        return [line for line in lines if line][:3]
    except Exception:
        logger.exception("query expansion LLM call failed, proceeding with original query only")
        return []


async def process_query(query: str, client: NeuroFlowClient | None) -> ProcessedQuery:
    """Runs expansion and classification concurrently — both are
    independent LLM calls with no data dependency between them. Metadata
    extraction is synchronous/regex-based so it isn't worth a task."""

    expanded, query_type = await asyncio.gather(
        expand_query(query, client),
        classify_query_type(query, client),
    )
    filters = extract_metadata_filters(query)

    return ProcessedQuery(
        original_query=query,
        expanded_queries=expanded,
        metadata_filters=filters,
        query_type=query_type,
    )
