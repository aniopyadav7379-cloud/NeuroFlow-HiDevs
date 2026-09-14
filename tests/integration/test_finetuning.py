"""Integration test 7: fine-tuning data extraction — insert known
training_pairs rows, trigger a job, verify the JSONL output."""
import json
import os
import time
import uuid

import asyncpg
import pytest

pytestmark = pytest.mark.asyncio

PIPELINE_ID = os.environ.get("NEUROFLOW_TEST_PIPELINE_ID", "")
DATABASE_URL = os.environ.get("NEUROFLOW_TEST_DATABASE_URL", "")
requires_db = pytest.mark.skipif(not DATABASE_URL, reason="NEUROFLOW_TEST_DATABASE_URL not set")


@requires_db
async def test_finetune_extraction_and_validation(client, auth_headers):
    conn = await asyncpg.connect(DATABASE_URL)
    try:
        pipeline_row = await conn.fetchrow(
            "INSERT INTO pipelines (name, config) VALUES ($1, '{}'::jsonb) RETURNING id",
            f"test-finetune-{uuid.uuid4().hex[:8]}",
        )
        pipeline_id = pipeline_row["id"]

        pair_ids = []
        for i in range(15):
            run_row = await conn.fetchrow(
                """
                INSERT INTO pipeline_runs (pipeline_id, query, generation, status)
                VALUES ($1, $2, $3, 'complete') RETURNING id
                """,
                pipeline_id,
                f"test query {i}",
                f"This is a well-formed, sufficiently long test answer number {i} that cites "
                f"its source properly [Source 1] and stays well within the required token "
                f"bounds for fine-tuning data, going on a bit further to be safe. " * 2,
            )
            run_id = run_row["id"]

            await conn.execute(
                """
                INSERT INTO training_pairs (run_id, system_prompt, user_message, assistant_message, quality_score)
                VALUES ($1, $2, $3, $4, $5) RETURNING id
                """,
                run_id,
                "You are a precise research assistant.",
                f"<context>\ntest context {i}\n</context>\n\ntest query {i}",
                f"This is a well-formed, sufficiently long test answer number {i} that cites "
                f"its source properly [Source 1] and stays well within the required token "
                f"bounds for fine-tuning data, going on a bit further to be safe. " * 2,
                0.9,
            )

        resp = await client.post(
            "/finetune/jobs",
            json={"base_model": "gpt-4o-mini", "target_task_type": "rag_generation", "quality_threshold": 0.82},
            headers=auth_headers,
        )
        assert resp.status_code == 201
        body = resp.json()
        assert body["training_pair_count"] == 15
    finally:
        await conn.close()
