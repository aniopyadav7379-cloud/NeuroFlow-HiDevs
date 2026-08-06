"""
Background worker entrypoint (`python -m worker`), invoked by the
`worker` service in infra/docker-compose.yml.

Runs the shared arq worker (backend/worker_settings.py) — every subsystem
with background jobs (ingestion, evaluation, and fine-tuning once Task 39
adds it) registers its function into that one WorkerSettings.functions
list; this entrypoint itself never changes.
"""
import logging

from arq import run_worker
from arq.connections import RedisSettings

from backend.config import get_settings
from backend.worker_settings import WorkerSettings

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("neuroflow.worker")


def main() -> None:
    settings = get_settings()
    WorkerSettings.redis_settings = RedisSettings.from_dsn(settings.redis_url)
    logger.info("starting arq worker")
    run_worker(WorkerSettings)


if __name__ == "__main__":
    main()
