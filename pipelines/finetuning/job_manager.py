"""
Fine-tuning job submission and polling against the OpenAI fine-tuning
API, plus the arq-scheduled poll loop and the success-path bookkeeping
(finetune_jobs row update, router registration, MLflow metrics).
"""
import logging

from openai import AsyncOpenAI

from backend.config import Settings
from pipelines.finetuning import tracker
from pipelines.finetuning.registration import register_finetuned_model

logger = logging.getLogger("neuroflow.finetuning.job_manager")

POLL_INTERVAL_SECONDS = 60
ACTIVE_STATUSES = ("pending", "running", "validating_files", "queued")
TERMINAL_SUCCESS_STATUSES = ("succeeded",)
TERMINAL_FAILURE_STATUSES = ("failed", "cancelled")


async def submit_finetune_job(jsonl_path: str, base_model: str, api_key: str) -> str:
    client = AsyncOpenAI(api_key=api_key)
    with open(jsonl_path, "rb") as f:
        file_resp = await client.files.create(file=f, purpose="fine-tune")
    job = await client.fine_tuning.jobs.create(training_file=file_resp.id, model=base_model)
    return job.id


async def check_job_status(provider_job_id: str, api_key: str) -> dict:
    client = AsyncOpenAI(api_key=api_key)
    job = await client.fine_tuning.jobs.retrieve(provider_job_id)
    return {
        "status": job.status,
        "fine_tuned_model": job.fine_tuned_model,
        "trained_tokens": job.trained_tokens,
        # OpenAI's fine_tuning.jobs object doesn't expose a stable
        # train/validation loss field the way a raw training run would —
        # result_files (if present) hold the metrics CSV. This module
        # doesn't parse that file (would need client.files.content() plus
        # CSV parsing for a provider-specific format); trained_tokens is
        # the one number we surface with confidence. See the NOTE in
        # poll_finetune_jobs_job below for how training_loss/
        # validation_loss are handled given this gap.
    }


async def _handle_job_succeeded(pool, redis_client, settings: Settings, job_row) -> None:
    status_info = await check_job_status(job_row["provider_job_id"], settings.openai_api_key)
    fine_tuned_model = status_info["fine_tuned_model"]

    async with pool.acquire() as conn:
        await conn.execute(
            """
            UPDATE finetune_jobs
            SET status = 'succeeded', fine_tuned_model_ref = $2, completed_at = NOW()
            WHERE id = $1
            """,
            job_row["id"], fine_tuned_model,
        )

    await register_finetuned_model(
        redis_client,
        base_model=job_row["base_model"],
        fine_tuned_model_name=fine_tuned_model,
        target_task_type=job_row["target_task_type"],
    )

    if job_row["mlflow_run_id"]:
        # NOTE: OpenAI's fine-tuning API doesn't return training_loss /
        # validation_loss directly from jobs.retrieve() (see check_job_status's
        # comment) — logging 0.0 placeholders would misrepresent real
        # metrics, so this only logs the one number available with
        # confidence (trained_tokens) rather than fabricate the other two.
        # A more complete implementation would fetch and parse the job's
        # result_files (a metrics CSV) via client.files.content().
        try:
            await tracker.log_training_results(
                settings, job_row["mlflow_run_id"],
                training_loss=float("nan"), validation_loss=float("nan"),
                trained_tokens=status_info["trained_tokens"] or 0,
            )
        except Exception:
            logger.warning("failed to log training results to mlflow for job_id=%s", job_row["id"], exc_info=True)
        await tracker.register_model(settings, job_row["mlflow_run_id"], str(job_row["id"]))

    logger.info("finetune job_id=%s succeeded, model=%s registered", job_row["id"], fine_tuned_model)


async def poll_finetune_jobs_job(ctx: dict) -> None:
    """arq cron job — see backend/worker_settings.py (second=0, i.e. once
    per minute, satisfying the task's "poll every 60 seconds")."""
    pool = ctx["pg_pool"]
    redis_client = ctx["redis"]
    settings = ctx["settings"]

    if not settings.openai_api_key:
        return  # nothing to poll against without credentials

    async with pool.acquire() as conn:
        rows = await conn.fetch(
            "SELECT * FROM finetune_jobs WHERE status = ANY($1::text[])", list(ACTIVE_STATUSES)
        )

    for row in rows:
        if not row["provider_job_id"]:
            continue
        try:
            status_info = await check_job_status(row["provider_job_id"], settings.openai_api_key)
        except Exception:
            logger.exception("failed to poll status for finetune job_id=%s", row["id"])
            continue

        if status_info["status"] in TERMINAL_SUCCESS_STATUSES:
            await _handle_job_succeeded(pool, redis_client, settings, row)
        elif status_info["status"] in TERMINAL_FAILURE_STATUSES:
            async with pool.acquire() as conn:
                await conn.execute(
                    "UPDATE finetune_jobs SET status = $2, completed_at = NOW() WHERE id = $1",
                    row["id"], status_info["status"],
                )
        elif status_info["status"] != row["status"]:
            async with pool.acquire() as conn:
                await conn.execute(
                    "UPDATE finetune_jobs SET status = $2 WHERE id = $1", row["id"], status_info["status"]
                )
