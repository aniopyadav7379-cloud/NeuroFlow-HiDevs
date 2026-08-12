"""
Typed application settings, loaded from environment variables / .env.

Every setting used anywhere in the backend must be declared here — no
os.environ[...] calls scattered through the codebase. This is the single
source of truth for what the service needs to run, and it's what
db/migrations.py, db/pool.py, and main.py all import from.
"""
from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # ── App ──────────────────────────────────────────────────────────────
    app_env: str = Field(default="development", description="development | staging | production")
    log_level: str = Field(default="INFO", description="Python logging level name")
    api_host: str = Field(default="0.0.0.0", description="Bind host for uvicorn")
    api_port: int = Field(default=8000, description="Bind port for uvicorn")

    # ── Postgres ─────────────────────────────────────────────────────────
    postgres_host: str = Field(default="postgres", description="Postgres hostname (service name in compose)")
    postgres_port: int = Field(default=5432, description="Postgres port")
    postgres_db: str = Field(default="neuroflow", description="Postgres database name")
    postgres_user: str = Field(default="neuroflow", description="Postgres user")
    postgres_password: str = Field(description="Postgres password — required, no default")
    postgres_pool_min_size: int = Field(default=2, description="asyncpg pool minimum connections")
    postgres_pool_max_size: int = Field(default=10, description="asyncpg pool maximum connections")

    @property
    def database_url(self) -> str:
        return (
            f"postgresql://{self.postgres_user}:{self.postgres_password}"
            f"@{self.postgres_host}:{self.postgres_port}/{self.postgres_db}"
        )

    # ── Redis ────────────────────────────────────────────────────────────
    redis_host: str = Field(default="redis", description="Redis hostname (service name in compose)")
    redis_port: int = Field(default=6379, description="Redis port")
    redis_password: str = Field(description="Redis password — required, no default")

    @property
    def redis_url(self) -> str:
        return f"redis://:{self.redis_password}@{self.redis_host}:{self.redis_port}/0"

    # ── MLflow ───────────────────────────────────────────────────────────
    mlflow_tracking_uri: str = Field(
        default="http://mlflow:5000", description="MLflow tracking server base URL"
    )

    # ── Tracing (OpenTelemetry → Jaeger) ────────────────────────────────
    otel_service_name: str = Field(default="neuroflow-api", description="Service name reported to the tracer")
    otel_exporter_otlp_endpoint: str = Field(
        default="http://jaeger:4317", description="OTLP gRPC endpoint (Jaeger collector)"
    )
    otel_traces_enabled: bool = Field(default=True, description="Toggle tracing instrumentation on/off")

    # ── Embeddings / model routing ──────────────────────────────────────
    embedding_model: str = Field(default="text-embedding-3-small", description="Default embedding model")
    embedding_dimensions: int = Field(default=1536, description="Must match the vector(N) column in chunks")

    # ── LLM provider credentials (backend/providers/) ───────────────────
    openai_api_key: str | None = Field(default=None, description="OpenAI API key; provider disabled if unset")
    openai_base_url: str | None = Field(
        default=None, description="Override for OpenAI-compatible endpoints; unset uses the default OpenAI API"
    )
    anthropic_api_key: str | None = Field(default=None, description="Anthropic API key; provider disabled if unset")

    # ── Ingestion (pipelines/ingestion/, backend/api/ingest.py) ─────────
    upload_dir: str = Field(default="/app/uploads", description="Directory uploaded files are written to before enqueue")
    max_upload_size_mb: int = Field(default=100, description="Reject uploads larger than this")

    # ── Fine-tuning (pipelines/finetuning/) ─────────────────────────────
    training_data_dir: str = Field(default="/app/training_data", description="Where validated JSONL training files are written")
    mlflow_experiment_name: str = Field(default="neuroflow-finetuning", description="MLflow experiment all fine-tune runs are logged under")

    # ── Auth (backend/security/auth.py) ─────────────────────────────────
    jwt_secret_key: str = Field(description="HMAC signing key for issued JWTs — required, no default")
    # JSON map of client_id -> {"secret": ..., "scopes": [...]}. A real
    # deployment would back this with a client table; for this scope it's
    # a Settings-configured registry, see auth.py's module docstring.
    auth_clients_json: str = Field(
        default='{"demo-client": {"secret": "change-me", "scopes": ["query", "ingest", "admin"]}}',
        description="JSON registry of valid client_id -> {secret, scopes}",
    )

    # ── RLS ──────────────────────────────────────────────────────────────
    db_app_role: str = Field(default="neuroflow_app", description="Pipeline-scoped Postgres role (see 002_rls.sql)")
    db_admin_role: str = Field(default="neuroflow_admin", description="Admin Postgres role for finetune_jobs")


@lru_cache
def get_settings() -> Settings:
    """Cached settings singleton — import get_settings() and call it, don't
    instantiate Settings() directly, so the whole process shares one parse
    of the environment."""
    return Settings()
