"""
The generation step: streams tokens from the LLM, logs the run to
pipeline_runs before and after, parses citations, and fires off an
evaluation job — all per docs/architecture.md §3/§4 and this task's spec.
"""
import asyncio
import json
import logging
import time

import asyncpg
import tiktoken

from backend.providers.client import NeuroFlowClient
from backend.providers.router import RoutingCriteria
from pipelines.generation.citations import parse_citations
from pipelines.generation.prompt_builder import CHAIN_OF_THOUGHT_QUERY_TYPES, build_messages
from pipelines.retrieval.context_assembler import AssembledContext

logger = logging.getLogger("neuroflow.generation.generator")

TOKEN_ENCODING = "cl100k_base"
_encoding = None

EVALUATION_JOB_NAME = "evaluate_generation"  # registered by Task 37's worker


def _get_encoding():
    global _encoding
    if _encoding is None:
        _encoding = tiktoken.get_encoding(TOKEN_ENCODING)
    return _encoding


def _count_tokens(text: str) -> int:
    return len(_get_encoding().encode(text)) if text else 0


class _ThinkTagStripper:
    """Streaming <think>...</think> stripper. Feed deltas as they arrive;
    get back only the text that should be shown to the user, with
    everything inside the tags routed to `.reasoning` instead. Handles a
    tag being split across multiple deltas (e.g. "<th" then "ink>"), which
    is the normal case with real token-by-token streaming.
    """

    _OPEN_TAG = "<think>"
    _CLOSE_TAG = "</think>"

    def __init__(self):
        self._buffer = ""
        self._in_think = False
        self._reasoning_parts: list[str] = []

    def _longest_partial_suffix(self, text: str, tag: str) -> int:
        """Length of the longest suffix of `text` that is a partial
        prefix of `tag` (full matches are handled by the caller first)."""
        max_check = min(len(text), len(tag) - 1)
        for length in range(max_check, 0, -1):
            if text.endswith(tag[:length]):
                return length
        return 0

    def feed(self, delta: str) -> str:
        self._buffer += delta
        visible_out = []

        while True:
            if not self._in_think:
                idx = self._buffer.find(self._OPEN_TAG)
                if idx != -1:
                    visible_out.append(self._buffer[:idx])
                    self._buffer = self._buffer[idx + len(self._OPEN_TAG):]
                    self._in_think = True
                    continue
                hold = self._longest_partial_suffix(self._buffer, self._OPEN_TAG)
                visible_out.append(self._buffer[: len(self._buffer) - hold])
                self._buffer = self._buffer[len(self._buffer) - hold:]
                break
            else:
                idx = self._buffer.find(self._CLOSE_TAG)
                if idx != -1:
                    self._reasoning_parts.append(self._buffer[:idx])
                    self._buffer = self._buffer[idx + len(self._CLOSE_TAG):]
                    self._in_think = False
                    continue
                hold = self._longest_partial_suffix(self._buffer, self._CLOSE_TAG)
                self._reasoning_parts.append(self._buffer[: len(self._buffer) - hold])
                self._buffer = self._buffer[len(self._buffer) - hold:]
                break

        return "".join(visible_out)

    def finish(self) -> str:
        """Call after the stream ends. A partial tag prefix that never
        completed is flushed as plain text, since the stream is over."""
        remainder = self._buffer
        self._buffer = ""
        if self._in_think:
            self._reasoning_parts.append(remainder)
            return ""
        return remainder

    @property
    def reasoning(self) -> str:
        return "".join(self._reasoning_parts).strip()


async def create_pipeline_run(pool: asyncpg.Pool, pipeline_id: str, query: str) -> str:
    """Creates the pipeline_runs row immediately — called from POST /query
    before retrieval even starts, so a run_id can be returned to the
    client right away for streaming requests. Stamps pipeline_version from
    pipelines.current_version at the moment the run starts — if the
    pipeline is edited mid-flight, this run still records the version it
    actually ran under, not whatever version exists by the time someone
    reads pipeline_runs later (Task 38: A/B comparison depends on this)."""
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            """
            INSERT INTO pipeline_runs (pipeline_id, query, status, pipeline_version)
            VALUES ($1, $2, 'queued', (SELECT current_version FROM pipelines WHERE id = $1))
            RETURNING id
            """,
            pipeline_id, query,
        )
    return str(row["id"])


async def mark_run_failed(pool: asyncpg.Pool, run_id: str, error: str = "") -> None:
    async with pool.acquire() as conn:
        await conn.execute(
            "UPDATE pipeline_runs SET status = 'failed', metadata = metadata || $2::jsonb WHERE id = $1",
            run_id, json.dumps({"error": error[:500]}),
        )


async def _enqueue_evaluation(arq_pool, run_id: str) -> None:
    """Fire-and-forget: called via asyncio.create_task so the caller never
    awaits this — a slow or unavailable Redis must not delay the
    generation response (task spec step 6)."""
    try:
        await arq_pool.enqueue_job(EVALUATION_JOB_NAME, run_id=run_id)
    except Exception:
        logger.exception("failed to enqueue evaluation job for run_id=%s (non-fatal)", run_id)


async def generate(
    *,
    pool: asyncpg.Pool,
    llm_client: NeuroFlowClient,
    arq_pool,
    run_id: str,
    pipeline_id: str,
    query: str,
    query_type: str,
    assembled: AssembledContext,
    use_chain_of_thought: bool = False,
    temperature: float | None = None,
    max_cost_per_call: float | None = None,
    prompt_variant: str = "balanced",
):
    """Async generator yielding SSE-shaped event dicts: {"type": "token", ...}
    while streaming, then a final {"type": "done", ...}. Updates the
    pre-created pipeline_runs row (see create_pipeline_run) before and
    after the LLM call, per the task's 6 steps. `temperature`,
    `max_cost_per_call`, and `prompt_variant` come from a pipeline's
    generation.* config (Task 38) — all optional so callers with no
    pipeline config (or the default pipeline) get the same behavior as
    before this task."""
    use_cot = use_chain_of_thought and query_type in CHAIN_OF_THOUGHT_QUERY_TYPES
    messages = build_messages(
        query, query_type, assembled.context, use_chain_of_thought=use_cot, prompt_variant=prompt_variant
    )

    routing_criteria = RoutingCriteria(task_type="rag_generation", max_cost_per_call=max_cost_per_call)
    model_config = await llm_client.resolve_model(routing_criteria)

    stream_kwargs = {"temperature": temperature} if temperature is not None else {}

    prompt_text = "\n\n".join(f"[{m.role}]\n{m.content}" for m in messages)

    # Step 1: log the complete assembled prompt BEFORE calling the LLM.
    async with pool.acquire() as conn:
        await conn.execute(
            """
            UPDATE pipeline_runs
            SET retrieved_chunk_ids = $2, prompt = $3, model_used = $4, status = 'running'
            WHERE id = $1
            """,
            run_id, assembled.chunks_used, prompt_text, model_config.model,
        )

    # Steps 2/3: stream tokens, accumulate the full response.
    stripper = _ThinkTagStripper() if use_cot else None
    visible_parts: list[str] = []
    started = time.perf_counter()

    async for delta in llm_client.stream(messages, routing_criteria, model_config=model_config, **stream_kwargs):
        visible = stripper.feed(delta) if stripper else delta
        if visible:
            visible_parts.append(visible)
            yield {"type": "token", "delta": visible}

    if stripper:
        trailing = stripper.finish()
        if trailing:
            visible_parts.append(trailing)
            yield {"type": "token", "delta": trailing}
        reasoning_text = stripper.reasoning
    else:
        reasoning_text = ""

    full_response = "".join(visible_parts)
    latency_ms = (time.perf_counter() - started) * 1000

    # Step 4: parse citations, resolve against the actual context window,
    # flag hallucinated source numbers.
    citations = parse_citations(full_response, assembled.sources)

    # Token counts here are an approximation (tiktoken over the assembled
    # prompt/response text), not provider-reported usage — the streaming
    # path (BaseLLMProvider.stream -> AsyncGenerator[str, None]) doesn't
    # carry usage metadata the way a non-streaming complete() call does.
    # Good enough for cost/quality dashboards; not exact-to-the-token.
    input_tokens = _count_tokens(prompt_text)
    output_tokens = _count_tokens(full_response) + _count_tokens(reasoning_text)

    run_metadata = {"chain_of_thought_reasoning": reasoning_text} if reasoning_text else {}

    # Step 5: update pipeline_runs with the completed generation.
    async with pool.acquire() as conn:
        await conn.execute(
            """
            UPDATE pipeline_runs
            SET generation = $2, input_tokens = $3, output_tokens = $4,
                latency_ms = $5, status = 'complete', metadata = metadata || $6::jsonb
            WHERE id = $1
            """,
            run_id, full_response, input_tokens, output_tokens,
            round(latency_ms), json.dumps(run_metadata),
        )

    # Step 6: enqueue evaluation asynchronously — NOT awaited by the caller.
    asyncio.create_task(_enqueue_evaluation(arq_pool, run_id))

    yield {
        "type": "done",
        "run_id": run_id,
        "citations": [
            {
                "source": c.reference,
                "chunk_id": c.chunk_id,
                "document": c.document_name,
                "page": c.page_number,
                **({"invalid_citation": True} if c.invalid_citation else {}),
            }
            for c in citations
        ],
    }
