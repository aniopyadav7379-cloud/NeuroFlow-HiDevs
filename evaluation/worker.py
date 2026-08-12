"""
The arq job function that actually runs when pipelines/generation/
generator.py enqueues "evaluate_generation" (fire-and-forget, Task 6 step
6). Registered into the shared worker's WorkerSettings.functions list in
backend/worker_settings.py — one arq worker process consumes jobs from
every subsystem that's registered a function, ingestion and evaluation
alike.
"""
import logging

from evaluation.judge import EvaluationJudge

logger = logging.getLogger("neuroflow.evaluation.worker")

JOB_NAME = "evaluate_generation"


async def evaluate_generation_job(ctx: dict, *, run_id: str) -> None:
    pool = ctx["pg_pool"]
    llm_client = ctx["llm_client"]

    async with pool.acquire() as conn:
        run_row = await conn.fetchrow(
            "SELECT query, generation, retrieved_chunk_ids FROM pipeline_runs WHERE id = $1",
            run_id,
        )
        if run_row is None:
            logger.error("evaluate_generation_job: no pipeline_runs row for run_id=%s", run_id)
            return
        if not run_row["generation"]:
            logger.warning("evaluate_generation_job: run_id=%s has no generation yet, skipping", run_id)
            return

        chunk_ids = run_row["retrieved_chunk_ids"] or []
        chunk_rows = (
            await conn.fetch("SELECT id, content FROM chunks WHERE id = ANY($1::uuid[])", chunk_ids)
            if chunk_ids
            else []
        )

    # Preserve retrieval order (retrieved_chunk_ids is ordered; the SQL
    # `= ANY(...)` fetch above is not) — context_precision's rank
    # weighting depends on this order matching what was actually shown to
    # the generation model.
    content_by_id = {str(r["id"]): r["content"] for r in chunk_rows}
    chunks = [content_by_id[cid] for cid in chunk_ids if cid in content_by_id]
    context = "\n\n".join(chunks)

    judge = EvaluationJudge(pool, llm_client)
    scores = await judge.evaluate(
        run_id=run_id,
        query=run_row["query"],
        answer=run_row["generation"],
        context=context,
        chunks=chunks,
    )
    logger.info(
        "evaluated run_id=%s: overall_score=%.3f (faithfulness=%.2f, relevance=%.2f, precision=%.2f, recall=%.2f)",
        run_id, scores.overall_score, scores.faithfulness, scores.answer_relevance,
        scores.context_precision, scores.context_recall,
    )
