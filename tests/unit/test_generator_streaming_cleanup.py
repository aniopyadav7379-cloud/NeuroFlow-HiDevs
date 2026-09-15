"""Regression test for pipelines.generation.generator.StreamingGenerator.

Covers the Phase 9 gap: if the consumer of generate_stream() stops iterating
early (e.g. a client disconnect mid-stream triggers GeneratorExit), the
pipeline_runs row must be marked 'failed' instead of being left stuck at
'running' forever. No live Postgres/Redis/LLM is used - the db pool, redis
client, and streaming LLM client are all mocked so this runs anywhere.
"""

import sys
from unittest.mock import AsyncMock, MagicMock

import pytest

# tiktoken.get_encoding("cl100k_base") needs a one-time network download that
# this sandbox's egress allowlist blocks (see tests/unit/test_chunker.py) -
# stub it out so this test exercises the generator's control flow, which is
# what's actually under test here, without depending on that download.
sys.modules.setdefault("tiktoken", MagicMock())

from pipelines.generation.generator import StreamingGenerator  # noqa: E402


def _make_pool_and_conn():
    """Returns (pool, conn, executed_calls) where pool.acquire() is an async
    context manager yielding conn, and conn.execute() records every call."""
    executed = []

    conn = MagicMock()

    async def fake_execute(query, *args):
        executed.append((query, args))

    conn.execute = AsyncMock(side_effect=fake_execute)

    class FakeAcquireCtx:
        async def __aenter__(self):
            return conn

        async def __aexit__(self, *exc):
            return False

    pool = MagicMock()
    pool.acquire = MagicMock(return_value=FakeAcquireCtx())
    return pool, conn, executed


async def _infinite_chunks():
    """A stream that never ends on its own - simulates an LLM still generating
    when the consumer walks away."""
    while True:
        yield "token "


class TestStreamingAbortCleanup:
    @pytest.mark.asyncio
    async def test_early_aclose_marks_run_failed(self):
        pool, conn, executed = _make_pool_and_conn()

        client = MagicMock()
        client.stream_chat = AsyncMock(return_value=_infinite_chunks())

        gen = StreamingGenerator(client=client, db_pool=pool, redis_client=MagicMock())

        stream = gen.generate_stream(
            run_id="11111111-1111-1111-1111-111111111111",
            pipeline_id="pipeline-1",
            query="hello",
            query_type="factual",
            assembled_context={"context_data": "some context"},
        )

        # Consume exactly one chunk, then simulate the consumer disconnecting -
        # this is what FastAPI does when an SSE client goes away mid-response.
        await stream.__anext__()
        await stream.aclose()

        # The very first DB call sets status='running'; there must be a later
        # call that sets status='failed' for the same run, proving the run
        # doesn't get stuck at 'running' when the stream is aborted early.
        assert any("status = 'running'" in q for q, _ in executed), (
            "expected the initial 'running' UPDATE to have run"
        )
        assert any("status = 'failed'" in q for q, _ in executed), (
            "aborting the stream early must mark the run as 'failed', not leave "
            "it stuck at 'running'"
        )

    @pytest.mark.asyncio
    async def test_normal_completion_still_marks_complete(self):
        """Regression guard: the abort-handling try/except must not change
        behavior on the normal, non-aborted path."""
        pool, conn, executed = _make_pool_and_conn()

        async def short_stream():
            yield "hello world"

        client = MagicMock()
        client.stream_chat = AsyncMock(return_value=short_stream())

        redis_client = MagicMock()
        redis_client.rpush = AsyncMock()

        gen = StreamingGenerator(client=client, db_pool=pool, redis_client=redis_client)

        stream = gen.generate_stream(
            run_id="22222222-2222-2222-2222-222222222222",
            pipeline_id="pipeline-1",
            query="hello",
            query_type="factual",
            assembled_context={"context_data": "some context"},
        )

        chunks = [item async for item in stream]

        assert any("status = 'complete'" in q for q, _ in executed)
        assert not any("status = 'failed'" in q for q, _ in executed)
        assert len(chunks) >= 1
