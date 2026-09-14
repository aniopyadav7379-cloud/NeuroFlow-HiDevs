from typing import Any
from uuid import UUID

import mlflow


class FineTuneTracker:
    def __init__(self, tracking_uri: str = "http://mlflow:5000") -> None:
        mlflow.set_tracking_uri(tracking_uri)
        mlflow.set_experiment("neuroflow_finetuning")

    def start_training_job(self, job_id: UUID, base_model: str, pairs: list[dict[str, Any]]) -> str:
        with mlflow.start_run(run_name=f"finetune-{job_id}") as run:
            avg_quality = (
                sum([p.get("quality_score", 0.0) for p in pairs]) / len(pairs) if pairs else 0.0
            )

            mlflow.log_params(
                {
                    "base_model": base_model,
                    "training_pair_count": len(pairs),
                    "avg_quality_score": avg_quality,
                }
            )

            # Log training data as artifact
            try:
                mlflow.log_artifact(f"training_data/{job_id}.jsonl")
            except Exception as e:
                print(f"Failed to log artifact to MLflow: {e}")

            return run.info.run_id  # type: ignore

    def log_job_completion(
        self, run_id: str, job_id: UUID, provider_job_id: str, metrics: dict[str, Any]
    ) -> Any:  # noqa: ANN401
        with mlflow.start_run(run_id=run_id):
            mlflow.log_metrics(metrics)

            # Register the model
            model_uri = f"runs:/{run_id}/model"
            model_name = f"neuroflow-finetune-{job_id}"

            try:
                mlflow.register_model(model_uri, model_name)
            except Exception as e:
                print(f"Failed to register model in MLflow: {e}")
