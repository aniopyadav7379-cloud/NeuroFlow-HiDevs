"""
Startup migration check.

docker-compose's postgres service applies infra/init/*.sql automatically on
first container init (docker-entrypoint-initdb.d), so in the normal compose
flow this module's apply step is a no-op. It exists so the API is safe to
point at a Postgres instance that *didn't* go through that entrypoint
(e.g. a pre-existing managed database) — it will detect the missing schema
and apply the same SQL files itself, in the same lexical order, rather than
starting up against a database it can't actually serve requests from.
"""
import logging
from pathlib import Path

import asyncpg

logger = logging.getLogger(__name__)

INIT_SQL_DIR = Path(__file__).resolve().parents[2] / "infra" / "init"

# Tables defined by 001_schema.sql — used as the "is the schema applied?"
# probe. If any is missing we treat the schema as not-yet-applied.
EXPECTED_TABLES = (
    "documents",
    "chunks",
    "pipelines",
    "pipeline_runs",
    "evaluations",
    "training_pairs",
    "finetune_jobs",
)


async def schema_is_applied(conn: asyncpg.Connection) -> bool:
    rows = await conn.fetch(
        """
        SELECT table_name FROM information_schema.tables
        WHERE table_schema = 'public' AND table_name = ANY($1::text[])
        """,
        list(EXPECTED_TABLES),
    )
    found = {r["table_name"] for r in rows}
    missing = set(EXPECTED_TABLES) - found
    if missing:
        logger.warning("schema check: missing tables %s", sorted(missing))
        return False
    return True


async def apply_init_sql(conn: asyncpg.Connection) -> None:
    """Apply every infra/init/*.sql file in lexical order (000_, 001_, 002_...).
    Skips 000_create_mlflow_db.sql, which provisions a *separate* database
    and can't run inside this connection's transaction against `neuroflow`.
    """
    sql_files = sorted(p for p in INIT_SQL_DIR.glob("*.sql") if not p.name.startswith("000_"))
    if not sql_files:
        raise RuntimeError(f"no init SQL files found in {INIT_SQL_DIR}")

    for path in sql_files:
        logger.info("applying migration: %s", path.name)
        sql = path.read_text()
        async with conn.transaction():
            await conn.execute(sql)
    logger.info("all migrations applied (%d files)", len(sql_files))


async def ensure_schema(pool: asyncpg.Pool) -> None:
    """Called from the lifespan handler at startup: apply schema if missing."""
    async with pool.acquire() as conn:
        if await schema_is_applied(conn):
            logger.info("schema already applied, skipping migrations")
            return
        logger.warning("schema not applied — applying infra/init/*.sql now")
        await apply_init_sql(conn)
