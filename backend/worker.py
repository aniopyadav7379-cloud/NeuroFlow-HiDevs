"""
Background worker entrypoint (`python -m worker`), invoked by the
`worker` service in infra/docker-compose.yml.

Runs the Ingestion Subsystem's arq job queue consumer
(pipelines/ingestion/worker_settings.py). The Evaluation Subsystem's async
scorer and the Fine-Tuning Subsystem's mining job (docs/architecture.md
§4, §5) register their own arq functions the same way in later tasks —
WorkerSettings.functions grows, this entrypoint doesn't change.
"""
import logging

from arq import run_worker
from arq.connections import RedisSettings

from backend.config import get_settings
from pipelines.ingestion.worker_settings import WorkerSettings

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("neuroflow.worker")


def main() -> None:
    settings = get_settings()
    WorkerSettings.redis_settings = RedisSettings.from_dsn(settings.redis_url)
    logger.info("starting arq ingestion worker")
    run_worker(WorkerSettings)


if __name__ == "__main__":
    main()
