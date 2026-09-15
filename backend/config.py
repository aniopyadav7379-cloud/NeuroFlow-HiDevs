from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Application configuration settings, loaded from environment variables."""

    postgres_user: str = Field(default="neuroflow", description="PostgreSQL database user")
    postgres_password: str = Field(default="password", description="PostgreSQL database password")
    postgres_host: str = Field(default="postgres", description="PostgreSQL database hostname")
    postgres_port: int = Field(default=5432, description="PostgreSQL database port")
    postgres_db: str = Field(default="neuroflow", description="PostgreSQL database name")

    redis_password: str = Field(default="password", description="Redis server password")
    redis_host: str = Field(default="redis", description="Redis server hostname")
    redis_port: int = Field(default=6379, description="Redis server port")

    mlflow_uri: str = Field(
        default="http://mlflow:5000", description="URI for the MLflow tracking server"
    )

    openai_api_key: str | None = Field(default=None, description="OpenAI API Key")
    anthropic_api_key: str | None = Field(default=None, description="Anthropic API Key")

    env_prefix: str = Field(
        default="", 
        description="Prefix for Postgres schemas and Redis keys to isolate preview environments"
    )

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    @property
    def database_url(self) -> str:
        """Constructs the asyncpg database URL."""
        return f"postgresql://{self.postgres_user}:{self.postgres_password}@{self.postgres_host}:{self.postgres_port}/{self.postgres_db}"
    @property
    def redis_url(self) -> str:
        """Constructs the Redis URL with automatic logical DB isolation for preview environments."""
        db_index = 0
        if self.env_prefix:
            import hashlib
            db_index = int(hashlib.md5(self.env_prefix.encode()).hexdigest(), 16) % 15 + 1
        return f"redis://:{self.redis_password}@{self.redis_host}:{self.redis_port}/{db_index}"
settings = Settings()
