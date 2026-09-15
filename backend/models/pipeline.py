from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class IngestionConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")
    chunking_strategy: str = Field(
        "recursive_character", 
        description="Strategy used to split documents into smaller text chunks.", 
        examples=["recursive_character"]
    )
    chunk_size_tokens: int = Field(
        512, description="The maximum size of each chunk in tokens.", examples=[512]
    )
    chunk_overlap_tokens: int = Field(
        50, 
        description="The number of overlapping tokens between consecutive chunks.", 
        examples=[50]
    )
    extractors_enabled: list[str] = Field(
        [], 
        description="List of ML extractors to run during ingestion.", 
        examples=[["keyword_extractor"]]
    )


class RetrievalConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")
    dense_k: int = Field(
        5, description="Number of documents to retrieve using dense vector search.", examples=[5]
    )
    sparse_k: int = Field(
        5, 
        description="Number of documents to retrieve using sparse keyword search (BM25).", 
        examples=[5]
    )
    reranker: str = Field(
        "cross-encoder", 
        description="Model used to rerank the combined retrieval results.", 
        examples=["cross-encoder"]
    )
    top_k_after_rerank: int = Field(
        3, description="Final number of chunks to send to the generator.", examples=[3]
    )
    query_expansion: bool = Field(
        False, 
        description="Whether to synthetically expand the query before retrieval.", 
        examples=[True]
    )
    metadata_filters_enabled: bool = Field(
        False, 
        description="Whether to apply pre-filtering based on document metadata.", 
        examples=[False]
    )


class GenerationRoutingConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")
    task_type: str = Field("qa", description="The type of generation task.", examples=["qa"])
    max_cost_per_call: float = Field(
        0.05, description="The maximum allowed LLM cost per call in USD.", examples=[0.01]
    )


class GenerationConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")
    model_routing: GenerationRoutingConfig = Field(
        ..., description="Configuration for how to route the generation task to an LLM provider."
    )
    max_context_tokens: int = Field(
        4000, 
        description="The maximum number of tokens allowed in the context window.", 
        examples=[4000]
    )
    temperature: float = Field(
        0.0, description="The generation temperature. 0.0 is deterministic.", examples=[0.1]
    )
    system_prompt_variant: str = Field(
        "default", 
        description="The identifier of the system prompt template to use.", 
        examples=["concise"]
    )


class EvaluationConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")
    auto_evaluate: bool = Field(
        True, 
        description=(
            "Whether to automatically run LLM-as-a-judge evaluations "
            "asynchronously after generation."
        ), 
        examples=[True]
    )
    training_threshold: float = Field(
        0.8, 
        description=(
            "The minimum overall score required to auto-include the query in "
            "future fine-tuning datasets."
        ), 
        examples=[0.85]
    )





class PipelineConfig(BaseModel):
    name: str = Field(
        ..., 
        max_length=100, 
        description="A unique human-readable name for the pipeline.", 
        examples=["Customer Support v2"]
    )
    description: str = Field(
        ..., 
        description="A detailed explanation of the pipeline's purpose and configuration.", 
        examples=["Optimized for answering fast factual questions."]
    )
    ingestion: IngestionConfig = Field(..., description="Ingestion pipeline parameters.")
    retrieval: RetrievalConfig = Field(..., description="Retrieval pipeline parameters.")
    generation: GenerationConfig = Field(..., description="Generation pipeline parameters.")
    evaluation: EvaluationConfig = Field(..., description="Evaluation pipeline parameters.")

    model_config = ConfigDict(
        extra="forbid",
        json_schema_extra={
            "examples": [
                {
                    "name": "Prod Customer Support",
                    "description": "Standard pipeline for support queries",
                    "ingestion": {
                        "chunking_strategy": "recursive_character",
                        "chunk_size_tokens": 512,
                        "chunk_overlap_tokens": 50,
                        "extractors_enabled": ["keyword"]
                    },
                    "retrieval": {
                        "dense_k": 5,
                        "sparse_k": 3,
                        "reranker": "cross-encoder",
                        "top_k_after_rerank": 3,
                        "query_expansion": False,
                        "metadata_filters_enabled": False
                    },
                    "generation": {
                        "model_routing": {
                            "task_type": "qa",
                            "max_cost_per_call": 0.05
                        },
                        "max_context_tokens": 4000,
                        "temperature": 0.1,
                        "system_prompt_variant": "default"
                    },
                    "evaluation": {
                        "auto_evaluate": True,
                        "training_threshold": 0.85
                    }
                }
            ]
        }
    )


class PipelineCreate(BaseModel):
    config: PipelineConfig


class PipelineUpdate(BaseModel):
    config: PipelineConfig


class PipelineResponse(BaseModel):
    id: UUID
    name: str
    version: int
    status: str
    config: Any
    created_at: Any

    class Config:
        from_attributes = True


class PipelineRunResponse(BaseModel):
    id: UUID
    pipeline_id: UUID
    pipeline_version: int | None
    query: str
    generation: str | None
    retrieval_latency_ms: int | None
    latency_ms: int | None
    input_tokens: int | None
    output_tokens: int | None
    model_used: str | None
    status: str
    created_at: Any

    class Config:
        from_attributes = True
