import sys
sys.path.insert(0, ".")
import pytest
from pydantic import ValidationError
from backend.models.pipeline import PipelineConfig

def test_minimal_config_uses_defaults():
    cfg = PipelineConfig(name="minimal")
    assert cfg.retrieval.dense_k == 20
    assert cfg.generation.system_prompt_variant == "balanced"

def test_exact_task_example_validates():
    example = {
        "name": "legal-research-v2", "description": "Optimized for legal document analysis",
        "ingestion": {"chunking_strategy": "hierarchical", "chunk_size_tokens": 400, "chunk_overlap_tokens": 80, "extractors_enabled": ["pdf", "docx"]},
        "retrieval": {"dense_k": 30, "sparse_k": 20, "reranker": "cross-encoder", "top_k_after_rerank": 8, "query_expansion": True, "metadata_filters_enabled": True},
        "generation": {"model_routing": {"task_type": "rag_generation", "max_cost_per_call": 0.05}, "max_context_tokens": 6000, "temperature": 0.2, "system_prompt_variant": "precise"},
        "evaluation": {"auto_evaluate": True, "training_threshold": 0.82},
    }
    cfg = PipelineConfig(**example)
    assert cfg.retrieval.dense_k == 30

def test_rejects_unknown_top_level_key():
    with pytest.raises(ValidationError):
        PipelineConfig(name="x", bogus_key=123)

def test_rejects_unknown_nested_key():
    with pytest.raises(ValidationError):
        PipelineConfig(name="x", retrieval={"dense_k": 10, "bogus_nested": True})

def test_rejects_invalid_enum_value():
    with pytest.raises(ValidationError):
        PipelineConfig(name="x", retrieval={"reranker": "not-a-real-option"})

def test_rejects_overlap_greater_than_chunk_size():
    with pytest.raises(ValidationError):
        PipelineConfig(name="x", ingestion={"chunk_size_tokens": 400, "chunk_overlap_tokens": 500})

def test_rejects_out_of_range_temperature():
    with pytest.raises(ValidationError):
        PipelineConfig(name="x", generation={"temperature": 5.0})
