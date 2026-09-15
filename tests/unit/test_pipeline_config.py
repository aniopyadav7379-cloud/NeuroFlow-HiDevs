import pytest
from pydantic import ValidationError

from backend.models.pipeline import (
    PipelineConfig,
    IngestionConfig,
    RetrievalConfig,
    GenerationConfig,
    GenerationRoutingConfig,
    EvaluationConfig,
)

def create_valid_config() -> dict:
    return {
        "name": "Test Pipeline",
        "description": "A test pipeline",
        "ingestion": {
            "chunking_strategy": "fixed_size",
            "chunk_size_tokens": 512,
            "chunk_overlap_tokens": 64,
            "extractors_enabled": ["pdf"],
        },
        "retrieval": {
            "dense_k": 10,
            "sparse_k": 10,
            "reranker": "cross-encoder",
            "top_k_after_rerank": 5,
            "query_expansion": False,
            "metadata_filters_enabled": False,
        },
        "generation": {
            "model_routing": {
                "task_type": "qa",
                "max_cost_per_call": 0.05,
            },
            "max_context_tokens": 4096,
            "temperature": 0.1,
            "system_prompt_variant": "default",
        },
        "evaluation": {
            "auto_evaluate": True,
            "training_threshold": 0.8,
        },
    }

def test_pipeline_config_valid():
    data = create_valid_config()
    config = PipelineConfig(**data)
    assert config.name == "Test Pipeline"
    assert config.ingestion.chunk_size_tokens == 512

def test_pipeline_config_extra_forbid():
    data = create_valid_config()
    data["extra_field"] = "not allowed"
    with pytest.raises(ValidationError) as exc:
        PipelineConfig(**data)
    assert "Extra inputs are not permitted" in str(exc.value)

def test_pipeline_config_missing_field():
    data = create_valid_config()
    del data["retrieval"]
    with pytest.raises(ValidationError) as exc:
        PipelineConfig(**data)
    assert "retrieval" in str(exc.value)
    assert "Field required" in str(exc.value)

def test_pipeline_config_invalid_type():
    data = create_valid_config()
    # Expecting an int, provide a string that cannot be cast
    data["ingestion"]["chunk_size_tokens"] = "not-an-int"
    with pytest.raises(ValidationError) as exc:
        PipelineConfig(**data)
    assert "Input should be a valid integer" in str(exc.value)

def test_pipeline_config_name_too_long():
    data = create_valid_config()
    data["name"] = "A" * 101 # max_length is 100
    with pytest.raises(ValidationError) as exc:
        PipelineConfig(**data)
    assert "String should have at most 100 characters" in str(exc.value)
