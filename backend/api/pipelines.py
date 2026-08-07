"""
Pipeline configuration CRUD, versioning, run history, and analytics.
"""
import json
import logging
from dataclasses import asdict

import asyncpg
from fastapi import APIRouter, HTTPException, Query, Request

from backend.models.pipeline import PipelineConfig
from backend.services.pipeline_optimizer import suggest_improvements

logger = logging.getLogger("neuroflow.api.pipelines")
router = APIRouter()


def _config_to_dict(config: PipelineConfig) -> dict:
    """Stored config excludes name/description — those live as their own
    pipelines columns (so renaming a pipeline doesn't require a new
    version), the JSONB blob holds only ingestion/retrieval/generation/
    evaluation."""
    return config.model_dump(exclude={"name", "description"})


@router.post("/pipelines", status_code=201)
async def create_pipeline(request: Request, config: PipelineConfig):
    pool = request.app.state.pg_pool
    config_dict = _config_to_dict(config)

    async with pool.acquire() as conn:
        try:
            async with conn.transaction():
                row = await conn.fetchrow(
                    """
                    INSERT INTO pipelines (name, description, config, status, current_version)
                    VALUES ($1, $2, $3::jsonb, 'active', 1)
                    RETURNING id
                    """,
                    config.name, config.description, json.dumps(config_dict),
                )
                pipeline_id = row["id"]
                await conn.execute(
                    """
                    INSERT INTO pipeline_versions (pipeline_id, version, config)
                    VALUES ($1, 1, $2::jsonb)
                    """,
                    pipeline_id, json.dumps(config_dict),
                )
        except asyncpg.UniqueViolationError:
            raise HTTPException(status_code=409, detail=f"a pipeline named '{config.name}' already exists")

    return {"pipeline_id": str(pipeline_id)}


@router.get("/pipelines")
async def list_pipelines(request: Request, status: str | None = Query(default=None)):
    pool = request.app.state.pg_pool

    where_clause = "WHERE p.status = $1" if status else ""
    args = [status] if status else []

    async with pool.acquire() as conn:
        rows = await conn.fetch(
            f"""
            SELECT
                p.id, p.name, p.description, p.status, p.current_version, p.created_at,
                last_run.id AS last_run_id, last_run.created_at AS last_run_at,
                last_run.latency_ms AS last_run_latency_ms, last_run.status AS last_run_status,
                last_eval.overall_score AS last_run_eval_score
            FROM pipelines p
            LEFT JOIN LATERAL (
                SELECT id, created_at, latency_ms, status
                FROM pipeline_runs
                WHERE pipeline_id = p.id
                ORDER BY created_at DESC
                LIMIT 1
            ) last_run ON true
            LEFT JOIN LATERAL (
                SELECT overall_score
                FROM evaluations
                WHERE run_id = last_run.id
                ORDER BY evaluated_at DESC
                LIMIT 1
            ) last_eval ON true
            {where_clause}
            ORDER BY p.created_at DESC
            """,
            *args,
        )

    return {
        "pipelines": [
            {
                "pipeline_id": str(r["id"]),
                "name": r["name"],
                "description": r["description"],
                "status": r["status"],
                "current_version": r["current_version"],
                "created_at": r["created_at"].isoformat(),
                "last_run": (
                    {
                        "run_id": str(r["last_run_id"]),
                        "created_at": r["last_run_at"].isoformat(),
                        "latency_ms": r["last_run_latency_ms"],
                        "status": r["last_run_status"],
                        "eval_score": r["last_run_eval_score"],
                    }
                    if r["last_run_id"]
                    else None
                ),
            }
            for r in rows
        ]
    }


@router.get("/pipelines/{pipeline_id}")
async def get_pipeline(request: Request, pipeline_id: str):
    pool = request.app.state.pg_pool

    async with pool.acquire() as conn:
        pipeline_row = await conn.fetchrow("SELECT * FROM pipelines WHERE id = $1", pipeline_id)
        if pipeline_row is None:
            raise HTTPException(status_code=404, detail=f"pipeline {pipeline_id} not found")

        agg_row = await conn.fetchrow(
            """
            SELECT
                COUNT(*) AS n_evaluations,
                AVG(overall_score) AS avg_overall_score,
                AVG(faithfulness) AS avg_faithfulness,
                AVG(answer_relevance) AS avg_answer_relevance,
                AVG(context_precision) AS avg_context_precision,
                AVG(context_recall) AS avg_context_recall
            FROM evaluations e
            JOIN pipeline_runs r ON r.id = e.run_id
            WHERE r.pipeline_id = $1
            """,
            pipeline_id,
        )

    config = pipeline_row["config"]
    if isinstance(config, str):
        config = json.loads(config)

    return {
        "pipeline_id": str(pipeline_row["id"]),
        "name": pipeline_row["name"],
        "description": pipeline_row["description"],
        "status": pipeline_row["status"],
        "current_version": pipeline_row["current_version"],
        "config": config,
        "created_at": pipeline_row["created_at"].isoformat(),
        "aggregate_evaluation": {
            "n_evaluations": agg_row["n_evaluations"],
            "avg_overall_score": agg_row["avg_overall_score"],
            "avg_faithfulness": agg_row["avg_faithfulness"],
            "avg_answer_relevance": agg_row["avg_answer_relevance"],
            "avg_context_precision": agg_row["avg_context_precision"],
            "avg_context_recall": agg_row["avg_context_recall"],
        },
    }


@router.patch("/pipelines/{pipeline_id}")
async def update_pipeline(request: Request, pipeline_id: str, config: PipelineConfig):
    """Creates a new version — never overwrites pipeline_versions history.
    `pipelines.config`/`current_version` are updated to point at the new
    version, since that's what future runs (and GET /pipelines/{id})
    should use, but every prior version stays queryable via
    GET /pipelines/{id}/runs (each run recorded its own pipeline_version)."""
    pool = request.app.state.pg_pool
    config_dict = _config_to_dict(config)

    async with pool.acquire() as conn:
        async with conn.transaction():
            current = await conn.fetchrow(
                "SELECT current_version FROM pipelines WHERE id = $1 FOR UPDATE", pipeline_id
            )
            if current is None:
                raise HTTPException(status_code=404, detail=f"pipeline {pipeline_id} not found")

            new_version = current["current_version"] + 1

            await conn.execute(
                """
                INSERT INTO pipeline_versions (pipeline_id, version, config)
                VALUES ($1, $2, $3::jsonb)
                """,
                pipeline_id, new_version, json.dumps(config_dict),
            )
            await conn.execute(
                """
                UPDATE pipelines
                SET config = $2::jsonb, current_version = $3, name = $4, description = $5
                WHERE id = $1
                """,
                pipeline_id, json.dumps(config_dict), new_version, config.name, config.description,
            )

    return {"pipeline_id": pipeline_id, "version": new_version}


@router.delete("/pipelines/{pipeline_id}", status_code=204)
async def delete_pipeline(request: Request, pipeline_id: str):
    pool = request.app.state.pg_pool
    async with pool.acquire() as conn:
        result = await conn.execute(
            "UPDATE pipelines SET status = 'archived' WHERE id = $1", pipeline_id
        )
    if result == "UPDATE 0":
        raise HTTPException(status_code=404, detail=f"pipeline {pipeline_id} not found")


@router.get("/pipelines/{pipeline_id}/runs")
async def get_pipeline_runs(
    request: Request, pipeline_id: str, page: int = Query(default=1, ge=1), page_size: int = Query(default=25, ge=1, le=100)
):
    pool = request.app.state.pg_pool
    offset = (page - 1) * page_size

    async with pool.acquire() as conn:
        total = await conn.fetchval("SELECT COUNT(*) FROM pipeline_runs WHERE pipeline_id = $1", pipeline_id)
        rows = await conn.fetch(
            """
            SELECT
                r.id, r.query, r.pipeline_version, r.status, r.latency_ms, r.retrieval_latency_ms,
                r.input_tokens, r.output_tokens, r.model_used, r.created_at,
                e.overall_score, e.faithfulness, e.answer_relevance, e.context_precision, e.context_recall
            FROM pipeline_runs r
            LEFT JOIN evaluations e ON e.run_id = r.id
            WHERE r.pipeline_id = $1
            ORDER BY r.created_at DESC
            LIMIT $2 OFFSET $3
            """,
            pipeline_id, page_size, offset,
        )

    return {
        "pipeline_id": pipeline_id,
        "page": page,
        "page_size": page_size,
        "total": total,
        "runs": [
            {
                "run_id": str(r["id"]),
                "query": r["query"],
                "pipeline_version": r["pipeline_version"],
                "status": r["status"],
                "latency_ms": r["latency_ms"],
                "retrieval_latency_ms": r["retrieval_latency_ms"],
                "input_tokens": r["input_tokens"],
                "output_tokens": r["output_tokens"],
                "model_used": r["model_used"],
                "created_at": r["created_at"].isoformat(),
                "evaluation": (
                    {
                        "overall_score": r["overall_score"],
                        "faithfulness": r["faithfulness"],
                        "answer_relevance": r["answer_relevance"],
                        "context_precision": r["context_precision"],
                        "context_recall": r["context_recall"],
                    }
                    if r["overall_score"] is not None
                    else None
                ),
            }
            for r in rows
        ],
    }


@router.get("/pipelines/{pipeline_id}/analytics")
async def get_pipeline_analytics(request: Request, pipeline_id: str):
    pool = request.app.state.pg_pool

    async with pool.acquire() as conn:
        pipeline_row = await conn.fetchrow("SELECT id FROM pipelines WHERE id = $1", pipeline_id)
        if pipeline_row is None:
            raise HTTPException(status_code=404, detail=f"pipeline {pipeline_id} not found")

        # Percentiles computed in Postgres (percentile_cont) rather than
        # pulled into Python — accurate, and avoids fetching every row.
        latency_row = await conn.fetchrow(
            """
            SELECT
                percentile_cont(0.5) WITHIN GROUP (ORDER BY retrieval_latency_ms) AS retrieval_p50,
                percentile_cont(0.95) WITHIN GROUP (ORDER BY retrieval_latency_ms) AS retrieval_p95,
                percentile_cont(0.99) WITHIN GROUP (ORDER BY retrieval_latency_ms) AS retrieval_p99,
                AVG(retrieval_latency_ms) AS retrieval_avg,
                AVG(latency_ms) AS generation_avg,
                percentile_cont(0.5) WITHIN GROUP (ORDER BY latency_ms) AS generation_p50,
                percentile_cont(0.95) WITHIN GROUP (ORDER BY latency_ms) AS generation_p95,
                percentile_cont(0.99) WITHIN GROUP (ORDER BY latency_ms) AS generation_p99,
                SUM(input_tokens) AS total_input_tokens,
                SUM(output_tokens) AS total_output_tokens,
                COUNT(*) AS n_runs
            FROM pipeline_runs
            WHERE pipeline_id = $1 AND status = 'complete'
            """,
            pipeline_id,
        )

        eval_row = await conn.fetchrow(
            """
            SELECT
                AVG(e.faithfulness) AS avg_faithfulness,
                AVG(e.answer_relevance) AS avg_answer_relevance,
                AVG(e.context_precision) AS avg_context_precision,
                AVG(e.context_recall) AS avg_context_recall,
                AVG(e.overall_score) AS avg_overall_score
            FROM evaluations e
            JOIN pipeline_runs r ON r.id = e.run_id
            WHERE r.pipeline_id = $1
            """,
            pipeline_id,
        )

        daily_rows = await conn.fetch(
            """
            SELECT date_trunc('day', created_at)::date AS day, COUNT(*) AS n
            FROM pipeline_runs
            WHERE pipeline_id = $1 AND created_at >= NOW() - INTERVAL '30 days'
            GROUP BY day
            ORDER BY day
            """,
            pipeline_id,
        )

    # Cost per query: this endpoint doesn't hardcode a price table (that
    # lives per-provider in backend/providers/*_provider.py and can differ
    # by model_used per run) — token totals are returned so a caller with
    # the right price table can compute cost; a true per-run cost would
    # need generation.py to persist cost_usd per run, which it doesn't
    # today (see NOTE in the task summary).
    return {
        "pipeline_id": pipeline_id,
        "n_runs": latency_row["n_runs"],
        "retrieval_latency_ms": {
            "p50": latency_row["retrieval_p50"],
            "p95": latency_row["retrieval_p95"],
            "p99": latency_row["retrieval_p99"],
            "avg": latency_row["retrieval_avg"],
        },
        "generation_latency_ms": {
            "p50": latency_row["generation_p50"],
            "p95": latency_row["generation_p95"],
            "p99": latency_row["generation_p99"],
            "avg": latency_row["generation_avg"],
        },
        "evaluation_scores": {
            "avg_overall_score": eval_row["avg_overall_score"],
            "avg_faithfulness": eval_row["avg_faithfulness"],
            "avg_answer_relevance": eval_row["avg_answer_relevance"],
            "avg_context_precision": eval_row["avg_context_precision"],
            "avg_context_recall": eval_row["avg_context_recall"],
        },
        "token_totals": {
            "input_tokens": latency_row["total_input_tokens"],
            "output_tokens": latency_row["total_output_tokens"],
        },
        "queries_per_day_last_30d": [
            {"date": r["day"].isoformat(), "count": r["n"]} for r in daily_rows
        ],
    }


@router.get("/pipelines/{pipeline_id}/suggestions")
async def get_pipeline_suggestions(request: Request, pipeline_id: str):
    pool = request.app.state.pg_pool

    async with pool.acquire() as conn:
        pipeline_row = await conn.fetchrow("SELECT config FROM pipelines WHERE id = $1", pipeline_id)
        if pipeline_row is None:
            raise HTTPException(status_code=404, detail=f"pipeline {pipeline_id} not found")

        agg_row = await conn.fetchrow(
            """
            SELECT
                COUNT(*) AS n_evaluations,
                AVG(overall_score) AS avg_overall_score,
                AVG(faithfulness) AS avg_faithfulness,
                AVG(answer_relevance) AS avg_answer_relevance,
                AVG(context_precision) AS avg_context_precision,
                AVG(context_recall) AS avg_context_recall
            FROM evaluations e
            JOIN pipeline_runs r ON r.id = e.run_id
            WHERE r.pipeline_id = $1
            """,
            pipeline_id,
        )

    config = pipeline_row["config"]
    if isinstance(config, str):
        config = json.loads(config)

    aggregate_scores = dict(agg_row) if agg_row else {}
    suggestions = suggest_improvements(config, aggregate_scores)

    return {
        "pipeline_id": pipeline_id,
        "based_on_n_evaluations": aggregate_scores.get("n_evaluations", 0),
        "suggestions": [asdict(s) for s in suggestions],
    }
