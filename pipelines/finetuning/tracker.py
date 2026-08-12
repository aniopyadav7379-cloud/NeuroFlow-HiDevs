"""
MLflow experiment tracking for fine-tuning jobs. The mlflow SDK is
synchronous (it makes blocking HTTP calls to the tracking server), so
every public function here is a thin async wrapper that runs the real
work via asyncio.to_thread — callers (job_manager.py, backend/api/
finetune.py) never block the event loop on an MLflow call.
"""
import asyncio
import logging
from statistics import mean

import mlflow

from backend.config import Settings

logger = logging.getLogger("neuroflow.finetuning.tracker")


def _configure(settings: Settings) -> None:
    mlflow.set_tracking_uri(settings.mlflow_tracking_uri)
    mlflow.set_experiment(settings.mlflow_experiment_name)


def _start_training_job_sync(
    settings: Settings, job_id: str, jsonl_path: str, base_model: str,
    training_pair_count: int, avg_quality_score: float, date_range: str,
) -> str:
    _configure(settings)
    with mlflow.start_run(run_name=f"finetune-{job_id}") as run:
        mlflow.log_params({
            "base_model": base_model,
            "training_pair_count": training_pair_count,
            "avg_quality_score": round(avg_quality_score, 4),
            "date_range": date_range,
        })
        mlflow.log_artifact(jsonl_path)
        return run.info.run_id


async def start_training_job(
    settings: Settings, job_id: str, jsonl_path: str, base_model: str, quality_scores: list[float],
) -> str:
    avg_quality_score = mean(quality_scores) if quality_scores else 0.0
    date_range = "n/a"  # see NOTE in backend/api/finetune.py: min/max training_pairs.created_at
    return await asyncio.to_thread(
        _start_training_job_sync, settings, job_id, jsonl_path, base_model,
        len(quality_scores), avg_quality_score, date_range,
    )


def _log_training_results_sync(
    settings: Settings, run_id: str, training_loss: float, validation_loss: float, trained_tokens: int,
) -> None:
    _configure(settings)
    with mlflow.start_run(run_id=run_id):
        mlflow.log_metrics({
            "training_loss": training_loss,
            "validation_loss": validation_loss,
            "training_token_count": trained_tokens,
        })


async def log_training_results(
    settings: Settings, run_id: str, training_loss: float, validation_loss: float, trained_tokens: int,
) -> None:
    await asyncio.to_thread(
        _log_training_results_sync, settings, run_id, training_loss, validation_loss, trained_tokens
    )


def _register_model_sync(settings: Settings, run_id: str, job_id: str) -> None:
    _configure(settings)
    mlflow.register_model(f"runs:/{run_id}/model", f"neuroflow-finetune-{job_id}")


async def register_model(settings: Settings, run_id: str, job_id: str) -> None:
    try:
        await asyncio.to_thread(_register_model_sync, settings, run_id, job_id)
    except Exception:
        # mlflow.register_model needs a logged model artifact under
        # runs:/{run_id}/model, which an OpenAI-hosted fine-tune (no local
        # model weights) never produces — this call is expected to fail
        # for that provider and is best-effort bookkeeping, not a hard
        # requirement for the fine-tune job itself to be considered done.
        logger.warning(
            "mlflow.register_model failed for run_id=%s job_id=%s (expected for "
            "provider-hosted fine-tunes with no local model artifact)", run_id, job_id, exc_info=True,
        )


def run_url(settings: Settings, run_id: str) -> str:
    return f"{settings.mlflow_tracking_uri}/#/experiments/0/runs/{run_id}"
