"""
PipelineConfig: the validated shape of a pipeline's JSON config, stored in
`pipelines.config` / `pipeline_versions.config`. Every nested section uses
`extra="forbid"` so a typo or a stale field from an old schema version
raises a validation error instead of being silently ignored.
"""
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


class IngestionConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    chunking_strategy: Literal["fixed_size", "semantic", "hierarchical"] = "fixed_size"
    chunk_size_tokens: int = Field(default=512, gt=0, le=8192)
    chunk_overlap_tokens: int = Field(default=64, ge=0)
    extractors_enabled: list[Literal["pdf", "docx", "image", "csv", "url", "pptx"]] = Field(
        default_factory=lambda: ["pdf", "docx", "image", "csv", "url"]
    )

    @model_validator(mode="after")
    def _overlap_smaller_than_size(self) -> "IngestionConfig":
        if self.chunk_overlap_tokens >= self.chunk_size_tokens:
            raise ValueError("chunk_overlap_tokens must be smaller than chunk_size_tokens")
        return self


class RetrievalConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    dense_k: int = Field(default=20, gt=0, le=200)
    sparse_k: int = Field(default=20, gt=0, le=200)
    reranker: Literal["cross-encoder", "local-cross-encoder", "none"] = "cross-encoder"
    top_k_after_rerank: int = Field(default=8, gt=0, le=100)
    query_expansion: bool = True
    metadata_filters_enabled: bool = True


class ModelRoutingConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    task_type: str = "rag_generation"
    max_cost_per_call: float | None = Field(default=None, ge=0)


class GenerationConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    model_routing: ModelRoutingConfig = Field(default_factory=ModelRoutingConfig)
    max_context_tokens: int = Field(default=4000, gt=0, le=200_000)
    temperature: float = Field(default=0.2, ge=0, le=2)
    system_prompt_variant: Literal["precise", "balanced", "creative"] = "balanced"


class EvaluationConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    auto_evaluate: bool = True
    training_threshold: float = Field(default=0.8, ge=0, le=1)


class PipelineConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1, max_length=200)
    description: str | None = None
    rate_limit_rpm: int | None = Field(
        default=None, gt=0,
        description="Per-pipeline requests-per-minute cap (backend/resilience/rate_limiter.py); unset means no pipeline-specific limit beyond the global provider limit",
    )
    ingestion: IngestionConfig = Field(default_factory=IngestionConfig)
    retrieval: RetrievalConfig = Field(default_factory=RetrievalConfig)
    generation: GenerationConfig = Field(default_factory=GenerationConfig)
    evaluation: EvaluationConfig = Field(default_factory=EvaluationConfig)
