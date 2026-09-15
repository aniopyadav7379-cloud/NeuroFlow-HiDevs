from typing import Any
from uuid import UUID, uuid4

import redis.asyncio as aioredis
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from backend.config import settings
from backend.db.pool import get_pool
from backend.security.auth import RequireScope
from backend.security.prompt_injection import sanitize_text
from pipelines.finetuning.extractor import FineTuneExtractor
from pipelines.finetuning.job_manager import FineTuneManager
from pipelines.finetuning.tracker import FineTuneTracker

router = APIRouter(prefix="/finetune", tags=["Fine-Tuning"])

class FineTuneRequest(BaseModel):
    base_model: str = Field(
        "gpt-3.5-turbo-0613", 
        description="The base LLM to fine-tune (e.g., an OpenAI base model).",
        examples=["gpt-3.5-turbo-0613"]
    )
    format: str = Field(
        "sft", 
        description=(
            "The fine-tuning format: 'sft' (Supervised Fine-Tuning) "
            "or 'dpo' (Direct Preference Optimization)."
        ),
        examples=["sft"]
    )


async def get_redis() -> Any:  # noqa: ANN401
    client = aioredis.from_url(
        settings.redis_url,
        decode_responses=True,
    )
    try:
        yield client
    finally:
        await client.aclose()


@router.post(
    "/jobs",
    summary="Create a new fine-tuning job",
    description=(
        "Analyzes historical high-quality evaluation runs to automatically extract a dataset "
        "of query/context/answer pairs, and submits them to the upstream LLM provider to "
        "create a fine-tuned model. **Errors**: Returns 400 if there are fewer than 10 "
        "valid training pairs. Requires 'admin' scope."
    ),
    response_description="A JSON object containing the internal job_id and the provider_job_id."
)
async def create_finetune_job(
    req: FineTuneRequest,
    db_pool: Any = Depends(get_pool),  # noqa: ANN401
    redis_client: Any = Depends(get_redis),  # noqa: ANN401
    user: Any = Depends(RequireScope("admin")),  # noqa: ANN401
) -> Any:  # noqa: ANN401
    job_id = uuid4()
    req.base_model = sanitize_text(req.base_model)
    req.format = sanitize_text(req.format)

    if req.format not in ["sft", "dpo"]:
        raise HTTPException(status_code=400, detail="format must be 'sft' or 'dpo'")

    # Extract & Validate
    extractor = FineTuneExtractor(db_pool, redis_client)
    valid_pairs = await extractor.extract_for_job(job_id, format=req.format)

    if len(valid_pairs) < 10 and req.format == "sft":  # Minimum pairs for OpenAI is usually 10
        raise HTTPException(
            status_code=400,
            detail=f"Not enough valid training pairs found (found {len(valid_pairs)}, need 10+)",
        )
    elif len(valid_pairs) == 0 and req.format == "dpo":
        raise HTTPException(status_code=400, detail="No valid DPO pairs found")

    # Start MLflow run
    tracker = FineTuneTracker(
        tracking_uri="http://mlflow:5000"
        if settings.postgres_host == "postgres"
        else "http://localhost:5000"
    )
    run_id = tracker.start_training_job(job_id, req.base_model, valid_pairs)

    # Submit job
    manager = FineTuneManager()
    try:
        provider_job_id = await manager.submit_finetune_job(
            f"training_data/{job_id}.jsonl", req.base_model
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to submit to OpenAI: {str(e)}")

    # Save job to DB
    async with db_pool.acquire() as conn:
        await conn.execute(
            """
            INSERT INTO finetune_jobs (id, provider_job_id, base_model, status, training_pair_count, mlflow_run_id)
            VALUES ($1, $2, $3, 'pending', $4, $5)
            """,  # noqa: E501
            job_id,
            provider_job_id,
            req.base_model,
            len(valid_pairs),
            run_id,
        )

    return {"job_id": job_id, "provider_job_id": provider_job_id, "status": "pending"}


@router.get(
    "/jobs",
    summary="List fine-tuning jobs",
    description=(
        "Retrieves a list of all historical fine-tuning jobs and their current processing "
        "status from the upstream provider. Requires 'admin' scope."
    ),
    response_description="A JSON array of fine-tuning job metadata."
)
async def list_finetune_jobs(
    db_pool: Any = Depends(get_pool),  # noqa: ANN401
    user: Any = Depends(RequireScope("admin")),  # noqa: ANN401
) -> Any:  # noqa: ANN401
    async with db_pool.acquire() as conn:
        records = await conn.fetch(
            "SELECT id, provider_job_id, base_model, status, created_at, completed_at FROM finetune_jobs ORDER BY created_at DESC"  # noqa: E501
        )
    return [dict(r) for r in records]


@router.get(
    "/jobs/{job_id}",
    summary="Get fine-tuning job details",
    description=(
        "Fetches detailed metadata about a specific fine-tuning job, including its upstream "
        "provider ID and MLflow tracking URL. **Errors**: Returns 404 if the job is not found. "
        "Requires 'admin' scope."
    ),
    response_description="A JSON object of the fine-tuning job details."
)
async def get_finetune_job(
    job_id: UUID,
    db_pool: Any = Depends(get_pool),  # noqa: ANN401
    user: Any = Depends(RequireScope("admin")),  # noqa: ANN401
) -> Any:  # noqa: ANN401
    async with db_pool.acquire() as conn:
        record = await conn.fetchrow("SELECT * FROM finetune_jobs WHERE id = $1", job_id)
    if not record:
        raise HTTPException(status_code=404, detail="Job not found")

    job_data = dict(record)
    job_data["mlflow_url"] = f"http://localhost:5000/#/experiments/0/runs/{record['mlflow_run_id']}"
    return job_data


@router.get(
    "/training-data/preview",
    summary="Preview extracted training data",
    description=(
        "Simulates the data extraction process to show a preview of up to 5 training pairs "
        "that would be used for a fine-tuning job. Extremely useful for verifying data quality "
        "before initiating a costly fine-tuning run. Requires 'admin' scope."
    ),
    response_description="A JSON array of up to 5 structured training pairs."
)
async def preview_training_data(
    format: str = "sft",
    db_pool: Any = Depends(get_pool),  # noqa: ANN401
    redis_client: Any = Depends(get_redis),  # noqa: ANN401
    user: Any = Depends(RequireScope("admin")),  # noqa: ANN401
) -> Any:  # noqa: ANN401
    format = sanitize_text(format)
    if format not in ["sft", "dpo"]:
        raise HTTPException(status_code=400, detail="format must be 'sft' or 'dpo'")

    extractor = FineTuneExtractor(db_pool, redis_client)
    candidates = (
        await extractor.get_dpo_candidates(limit=50)
        if format == "dpo"
        else await extractor.get_candidates(limit=50)
    )

    valid_pairs = []
    for pair in candidates:
        if format == "sft":
            if await extractor.validate_pair(pair):
                valid_pairs.append(pair)
                if len(valid_pairs) == 5:
                    break
        else:
            # DPO doesn't have deep validation yet
            valid_pairs.append(pair)
            if len(valid_pairs) == 5:
                break

    return valid_pairs
