"""
Fine-tuning API: trigger a job (extraction -> validation -> MLflow ->
OpenAI submission), list/inspect jobs, and preview what a job would
extract without actually running one.
"""
import logging
import uuid

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

from pipelines.finetuning import job_manager, tracker
from pipelines.finetuning.extractor import extract_and_validate, mark_pairs_included, write_jsonl

logger = logging.getLogger("neuroflow.api.finetune")
router = APIRouter()


class CreateJobRequest(BaseModel):
    base_model: str
    target_task_type: str = "rag_generation"
    quality_threshold: float = 0.82


class CreateJobResponse(BaseModel):
    job_id: str
    status: str
    training_pair_count: int
    rejected_count: int
    mlflow_run_id: str | None = None


@router.post("/finetune/jobs", response_model=CreateJobResponse, status_code=201)
async def create_finetune_job(request: Request, body: CreateJobRequest) -> CreateJobResponse:
    pool = request.app.state.pg_pool
    llm_client = request.app.state.llm_client
    settings = request.app.state.settings

    if not settings.openai_api_key:
        raise HTTPException(status_code=400, detail="OPENAI_API_KEY is not configured — cannot submit a fine-tuning job")

    job_id = str(uuid.uuid4())

    async with pool.acquire() as conn:
        await conn.execute(
            """
            INSERT INTO finetune_jobs (id, base_model, status, target_task_type)
            VALUES ($1, $2, 'pending', $3)
            """,
            job_id, body.base_model, body.target_task_type,
        )

    extraction = await extract_and_validate(pool, llm_client, quality_threshold=body.quality_threshold)

    if not extraction.valid_entries:
        async with pool.acquire() as conn:
            await conn.execute("UPDATE finetune_jobs SET status = 'failed' WHERE id = $1", job_id)
        raise HTTPException(
            status_code=422,
            detail=f"no training pairs passed validation ({len(extraction.rejected)} candidates rejected) — job not submitted",
        )

    jsonl_path = write_jsonl(settings.training_data_dir, job_id, extraction.valid_entries)
    await mark_pairs_included(pool, extraction.valid_training_pair_ids, job_id)

    mlflow_run_id = None
    try:
        mlflow_run_id = await tracker.start_training_job(
            settings, job_id, jsonl_path, body.base_model, extraction.quality_scores
        )
    except Exception:
        logger.warning("failed to start mlflow run for job_id=%s (continuing without it)", job_id, exc_info=True)

    async with pool.acquire() as conn:
        await conn.execute(
            "UPDATE finetune_jobs SET training_pair_count = $2, mlflow_run_id = $3 WHERE id = $1",
            job_id, len(extraction.valid_entries), mlflow_run_id,
        )

    try:
        provider_job_id = await job_manager.submit_finetune_job(jsonl_path, body.base_model, settings.openai_api_key)
    except Exception:
        logger.exception("failed to submit fine-tune job to OpenAI for job_id=%s", job_id)
        async with pool.acquire() as conn:
            await conn.execute("UPDATE finetune_jobs SET status = 'failed' WHERE id = $1", job_id)
        raise HTTPException(status_code=502, detail="failed to submit fine-tuning job to the provider")

    async with pool.acquire() as conn:
        await conn.execute(
            "UPDATE finetune_jobs SET status = 'running', provider_job_id = $2 WHERE id = $1",
            job_id, provider_job_id,
        )

    return CreateJobResponse(
        job_id=job_id,
        status="running",
        training_pair_count=len(extraction.valid_entries),
        rejected_count=len(extraction.rejected),
        mlflow_run_id=mlflow_run_id,
    )


@router.get("/finetune/jobs")
async def list_finetune_jobs(request: Request):
    pool = request.app.state.pg_pool
    async with pool.acquire() as conn:
        rows = await conn.fetch("SELECT * FROM finetune_jobs ORDER BY created_at DESC")

    return {
        "jobs": [
            {
                "job_id": str(r["id"]),
                "base_model": r["base_model"],
                "status": r["status"],
                "target_task_type": r["target_task_type"],
                "training_pair_count": r["training_pair_count"],
                "fine_tuned_model_ref": r["fine_tuned_model_ref"],
                "created_at": r["created_at"].isoformat(),
                "completed_at": r["completed_at"].isoformat() if r["completed_at"] else None,
            }
            for r in rows
        ]
    }


@router.get("/finetune/jobs/{job_id}")
async def get_finetune_job(request: Request, job_id: str):
    pool = request.app.state.pg_pool
    settings = request.app.state.settings

    async with pool.acquire() as conn:
        row = await conn.fetchrow("SELECT * FROM finetune_jobs WHERE id = $1", job_id)
    if row is None:
        raise HTTPException(status_code=404, detail=f"finetune job {job_id} not found")

    metrics = row["metrics"]
    if isinstance(metrics, str):
        import json
        metrics = json.loads(metrics)

    return {
        "job_id": str(row["id"]),
        "base_model": row["base_model"],
        "status": row["status"],
        "target_task_type": row["target_task_type"],
        "provider_job_id": row["provider_job_id"],
        "fine_tuned_model_ref": row["fine_tuned_model_ref"],
        "training_pair_count": row["training_pair_count"],
        "mlflow_run_id": row["mlflow_run_id"],
        "mlflow_run_url": tracker.run_url(settings, row["mlflow_run_id"]) if row["mlflow_run_id"] else None,
        "metrics": metrics,
        "created_at": row["created_at"].isoformat(),
        "completed_at": row["completed_at"].isoformat() if row["completed_at"] else None,
    }


@router.get("/finetune/training-data/preview")
async def preview_training_data(request: Request, quality_threshold: float = 0.82, sample_size: int = 5):
    """Shows what a job would extract right now, WITHOUT writing a JSONL
    file, marking any training_pairs as included_in_job, or submitting
    anything — purely a read-only quality check."""
    pool = request.app.state.pg_pool
    llm_client = request.app.state.llm_client

    extraction = await extract_and_validate(pool, llm_client, quality_threshold=quality_threshold)

    return {
        "would_extract_count": len(extraction.valid_entries),
        "would_reject_count": len(extraction.rejected),
        "sample_pairs": extraction.valid_entries[:sample_size],
        "sample_rejections": [
            {"training_pair_id": r.training_pair_id, "reason": r.reason} for r in extraction.rejected[:sample_size]
        ],
    }
