import json
from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Path, Query

from backend.db.pool import get_pool
from backend.models.pipeline import (
    PipelineCreate,
    PipelineResponse,
    PipelineRunResponse,
    PipelineUpdate,
)
from backend.security.auth import RequireScope
from backend.security.prompt_injection import sanitize_text
from backend.services.pipeline_optimizer import PipelineOptimizer

router = APIRouter(prefix="/pipelines", tags=["Admin"])


@router.post(
    "",
    response_model=PipelineResponse,
    summary="Create a new RAG pipeline",
    description=(
        "Creates a new RAG pipeline configuration with specified ingestion, retrieval, "
        "generation, and evaluation parameters. **Errors**: Returns 400 if a pipeline "
        "with the same name already exists. Requires 'admin' scope."
    ),
    response_description="A JSON object containing the newly created pipeline definition."
)
async def create_pipeline(data: PipelineCreate, user: Any = Depends(RequireScope("admin"))) -> Any:  # noqa: ANN401
    pool = get_pool()
    data.config.name = sanitize_text(data.config.name)
    data.config.description = sanitize_text(data.config.description)
    config_json = data.config.model_dump_json()
    name = data.config.name

    async with pool.acquire() as conn:
        try:
            row = await conn.fetchrow(
                """
                INSERT INTO pipelines (name, config, version, status)
                VALUES ($1, $2::jsonb, 1, 'active')
                RETURNING *
                """,
                name,
                config_json,
            )

            await conn.execute(
                """
                INSERT INTO pipeline_versions (pipeline_id, version, config)
                VALUES ($1, 1, $2::jsonb)
                """,
                row["id"],
                config_json,
            )
        except Exception as e:
            if "unique constraint" in str(e).lower():
                raise HTTPException(
                    status_code=400, detail="Pipeline with this name already exists"
                )
            raise HTTPException(status_code=500, detail=str(e))

    res_dict = dict(row)
    res_dict["config"] = json.loads(res_dict["config"])
    return PipelineResponse(**res_dict)


@router.get(
    "",
    summary="List all pipelines",
    description=(
        "Retrieves a list of all active (non-archived) RAG pipelines, including aggregate "
        "metrics like their last run latency and last evaluation score. Useful for building "
        "admin dashboards."
    ),
    response_description="A JSON array of pipeline metadata."
)
async def list_pipelines() -> Any:  # noqa: ANN401
    pool = get_pool()
    async with pool.acquire() as conn:
        # GET /pipelines — list all pipelines with last-run metrics
        records = await conn.fetch(
            """
            SELECT p.id, p.name, p.version, p.status, p.created_at,
                   pr.id as last_run_id, pr.created_at as last_run_time, pr.latency_ms as last_run_latency,
                   e.overall_score as last_run_eval_score
            FROM pipelines p
            LEFT JOIN LATERAL (
                SELECT id, created_at, latency_ms
                FROM pipeline_runs
                WHERE pipeline_id = p.id
                ORDER BY created_at DESC
                LIMIT 1
            ) pr ON true
            LEFT JOIN evaluations e ON e.run_id = pr.id
            WHERE p.status != 'archived'
            ORDER BY p.created_at DESC
            """  # noqa: E501
        )
        return [dict(r) for r in records]


@router.get(
    "/{id}",
    summary="Get pipeline details",
    description=(
        "Retrieves the full configuration and aggregated historical evaluation scores "
        "(faithfulness, precision, recall) for a specific pipeline. **Errors**: Returns "
        "404 if the pipeline does not exist or is archived."
    ),
    response_description=(
        "A JSON object containing the pipeline configuration and aggregated scores."
    )
)
async def get_pipeline(id: UUID = Path(...)) -> Any:  # noqa: ANN401
    pool = get_pool()
    async with pool.acquire() as conn:
        # Full config and aggregate evaluation scores
        row = await conn.fetchrow(
            """
            SELECT p.*, 
                   AVG(e.overall_score) as avg_overall_score,
                   AVG(e.faithfulness) as avg_faithfulness,
                   AVG(e.answer_relevance) as avg_relevance,
                   AVG(e.context_precision) as avg_precision,
                   AVG(e.context_recall) as avg_recall
            FROM pipelines p
            LEFT JOIN pipeline_runs pr ON pr.pipeline_id = p.id
            LEFT JOIN evaluations e ON e.run_id = pr.id
            WHERE p.id = $1 AND p.status != 'archived'
            GROUP BY p.id
            """,
            id,
        )
        if not row:
            raise HTTPException(status_code=404, detail="Pipeline not found or archived")

        res = dict(row)
        res["config"] = (
            json.loads(res["config"]) if isinstance(res["config"], str) else res["config"]
        )
        return res


@router.patch(
    "/{id}",
    summary="Update pipeline configuration",
    description=(
        "Updates the configuration of an existing pipeline and increments its version number "
        "to maintain historical traceability. **Errors**: Returns 404 if the pipeline does "
        "not exist. Requires 'admin' scope."
    ),
    response_description="A JSON object containing the updated pipeline definition."
)
async def update_pipeline(
    data: PipelineUpdate,
    id: UUID = Path(...),
    user: Any = Depends(RequireScope("admin")),  # noqa: ANN401
) -> Any:  # noqa: ANN401
    pool = get_pool()
    data.config.name = sanitize_text(data.config.name)
    data.config.description = sanitize_text(data.config.description)
    config_json = data.config.model_dump_json()

    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT version FROM pipelines WHERE id = $1 AND status != 'archived'", id
        )
        if not row:
            raise HTTPException(status_code=404, detail="Pipeline not found or archived")

        new_version = row["version"] + 1

        updated_row = await conn.fetchrow(
            """
            UPDATE pipelines 
            SET config = $1::jsonb, version = $2
            WHERE id = $3
            RETURNING *
            """,
            config_json,
            new_version,
            id,
        )

        await conn.execute(
            """
            INSERT INTO pipeline_versions (pipeline_id, version, config)
            VALUES ($1, $2, $3::jsonb)
            """,
            id,
            new_version,
            config_json,
        )

    res_dict = dict(updated_row)
    res_dict["config"] = json.loads(res_dict["config"])
    return PipelineResponse(**res_dict)


@router.delete(
    "/{id}",
    summary="Archive a pipeline",
    description=(
        "Soft-deletes a pipeline by setting its status to 'archived'. Archived pipelines "
        "cannot be queried but retain their historical data for auditing. **Errors**: "
        "Returns 404 if not found. Requires 'admin' scope."
    ),
    response_description="A JSON object confirming the archival status."
)
async def delete_pipeline(id: UUID = Path(...), user: Any = Depends(RequireScope("admin"))) -> Any:  # noqa: ANN401
    pool = get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            "UPDATE pipelines SET status = 'archived' WHERE id = $1 RETURNING id", id
        )
        if not row:
            raise HTTPException(status_code=404, detail="Pipeline not found")

    return {"status": "archived", "id": id}


@router.get(
    "/{id}/runs",
    response_model=list[PipelineRunResponse],
    summary="List runs for a pipeline",
    description=(
        "Retrieves paginated historical query runs for a specific pipeline, "
        "ordered from newest to oldest."
    ),
    response_description="A JSON array of pipeline run objects."
)
async def list_pipeline_runs(
    id: UUID = Path(...), limit: int = Query(50), offset: int = Query(0)
) -> Any:  # noqa: ANN401
    pool = get_pool()
    async with pool.acquire() as conn:
        records = await conn.fetch(
            """
            SELECT * FROM pipeline_runs 
            WHERE pipeline_id = $1
            ORDER BY created_at DESC
            LIMIT $2 OFFSET $3
            """,
            id,
            limit,
            offset,
        )
        return [PipelineRunResponse(**dict(r)) for r in records]


@router.get(
    "/{id}/analytics",
    summary="Get pipeline analytics",
    description=(
        "Generates advanced analytics for a specific pipeline, including P50/P95 latency "
        "percentiles, average generation latency, aggregated evaluation scores, estimated "
        "LLM costs based on token counts, and a daily time-series of query volume."
    ),
    response_description="A JSON object containing the analytics dashboard metrics."
)
async def get_pipeline_analytics(id: UUID = Path(...)) -> Any:  # noqa: ANN401
    pool = get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow("SELECT 1 FROM pipelines WHERE id = $1", id)
        if not row:
            raise HTTPException(status_code=404, detail="Pipeline not found")

        stats = await conn.fetchrow(
            """
            SELECT 
                percentile_cont(0.5) WITHIN GROUP (ORDER BY retrieval_latency_ms) as p50_retrieval_latency,
                percentile_cont(0.95) WITHIN GROUP (ORDER BY retrieval_latency_ms) as p95_retrieval_latency,
                percentile_cont(0.99) WITHIN GROUP (ORDER BY retrieval_latency_ms) as p99_retrieval_latency,
                AVG(latency_ms) as avg_generation_latency,
                AVG(e.faithfulness) as avg_faithfulness,
                AVG(e.answer_relevance) as avg_relevance,
                AVG(e.context_precision) as avg_precision,
                AVG(e.context_recall) as avg_recall,
                AVG(e.overall_score) as avg_overall
            FROM pipeline_runs pr
            LEFT JOIN evaluations e ON e.run_id = pr.id
            WHERE pr.pipeline_id = $1
            """,  # noqa: E501
            id,
        )

        # We need cost per query. Let's do an approximation based on token counts and model pricing logic.  # noqa: E501
        # "Cost per query (input_tokens * price + output_tokens * price)"
        # Assuming gpt-4o-mini prices: 0.15/1M input, 0.60/1M output
        cost_stats = await conn.fetchrow(
            """
            SELECT 
                AVG((COALESCE(input_tokens, 0) * 0.15 / 1000000.0) + (COALESCE(output_tokens, 0) * 0.60 / 1000000.0)) as avg_cost_per_query
            FROM pipeline_runs
            WHERE pipeline_id = $1
            """,  # noqa: E501
            id,
        )

        daily_series = await conn.fetch(
            """
            SELECT date_trunc('day', created_at)::date as day, count(*) as query_count
            FROM pipeline_runs
            WHERE pipeline_id = $1 AND created_at >= NOW() - INTERVAL '30 days'
            GROUP BY day
            ORDER BY day
            """,
            id,
        )

        res = dict(stats) if stats else {}
        if cost_stats:
            res["avg_cost_per_query"] = cost_stats["avg_cost_per_query"]

        # Ensure daily series returns all 30 days (even empty ones) or just the sparkline points
        # For simplicity, returning just the populated points is often enough for a sparkline
        res["daily_queries"] = [
            {"day": r["day"].isoformat(), "count": r["query_count"]} for r in daily_series
        ]

        return res


@router.post(
    "/{id}/suggestions",
    summary="Get pipeline optimization suggestions",
    description=(
        "Runs the PipelineOptimizer agent to analyze historical metrics and suggest "
        "architectural improvements (e.g., increasing retrieval `k`, swapping models) "
        "based on detected anomalies."
    ),
    response_description="A JSON object containing an array of actionable suggestions."
)
async def get_pipeline_suggestions(id: UUID = Path(...)) -> Any:  # noqa: ANN401
    pool = get_pool()
    optimizer = PipelineOptimizer(pool)
    suggestions = await optimizer.get_suggestions(id)
    return {"suggestions": suggestions}
