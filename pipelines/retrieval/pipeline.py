import time
from typing import Any

import asyncpg
from opentelemetry import trace

from backend.monitoring.metrics import retrieval_latency
from backend.providers.client import NeuroFlowClient

from .context_assembler import ContextAssembler
from .models import RetrievalResult
from .query_processor import QueryProcessor
from .reranker import CrossEncoderReranker
from .retriever import Retriever

tracer = trace.get_tracer(__name__)


class RetrievalPipeline:
    def __init__(self, db_pool: asyncpg.Pool, client: NeuroFlowClient) -> None:
        self.query_processor = QueryProcessor(client)
        self.retriever = Retriever(db_pool, client)
        self.reranker = CrossEncoderReranker(client)
        self.context_assembler = ContextAssembler()
        self.redis = client.redis

    async def retrieve(
        self,
        query: str,
        k: int = 10,
        token_budget: int = 4000,
        use_hyde: bool = False,
        config: dict[str, Any] | None = None,
    ) -> list[RetrievalResult]:
        """
        Mainly for evaluation script which expects a list of results.
        Executes up to reranking and returns the top K results.
        """
        dense_k = None
        sparse_k = None
        rrf_k = 60
        top_k_after_rerank = k
        if config and "retrieval" in config:
            retrieval_conf = config["retrieval"]
            dense_k = retrieval_conf.get("dense_k")
            sparse_k = retrieval_conf.get("sparse_k")
            rrf_k = retrieval_conf.get("rrf_k", 60)
            top_k_after_rerank = retrieval_conf.get("top_k_after_rerank", k)

        # Step 1: Query Processing
        processed_query = await self.query_processor.process_query(query)

        # Step 2: Parallel Retrieval & Fusion
        # Pass max(dense_k/sparse_k/k, 60) to ensure enough candidates if not explicitly overridden
        retrieval_k = max(top_k_after_rerank, 60)
        retrieved_results = await self.retriever.retrieve(
            processed_query,
            k=retrieval_k,
            use_hyde=use_hyde,
            dense_k=dense_k,
            sparse_k=sparse_k,
            rrf_k=rrf_k,
        )

        # Step 3: Reranking
        # Take top 40 for reranking as per instructions
        reranked_results = await self.reranker.rerank(query, retrieved_results, top_n=40)

        return reranked_results[:top_k_after_rerank]

    async def get_context(
        self,
        query: str,
        config: dict[str, Any] | None = None,
        k: int = 10,
        token_budget: int = 4000,
        use_hyde: bool = False,
        pipeline_id: str | None = None,
        run_id: str | None = None,
    ) -> dict[str, Any]:
        """
        Executes the full pipeline including context assembly.
        """
        import hashlib
        import json

        from .models import RetrievalResult

        dense_k = None
        sparse_k = None
        rrf_k = 60
        if config and "retrieval" in config:
            retrieval_conf = config["retrieval"]
            k = retrieval_conf.get("top_k_after_rerank", k)
            if "query_expansion" in retrieval_conf:
                use_hyde = retrieval_conf["query_expansion"]
            rrf_weights = retrieval_conf.get("rrf_weights", [0.6, 0.4, 1.0])
            use_cache = retrieval_conf.get("use_cache", True)
            dense_k = retrieval_conf.get("dense_k")
            sparse_k = retrieval_conf.get("sparse_k")
            rrf_k = retrieval_conf.get("rrf_k", 60)
        else:
            rrf_weights = [0.6, 0.4, 1.0]
            use_cache = True

        prompt_variant = "B"
        if config and "generation" in config:
            token_budget = config["generation"].get("max_context_tokens", token_budget)
            prompt_variant = config["generation"].get("prompt_variant", "B")

        # Create cache key incorporating all configuration parameters
        config_hash = f"{k}_{token_budget}_{use_hyde}_{pipeline_id}_{prompt_variant}_{rrf_weights}_{use_cache}_{dense_k}_{sparse_k}_{rrf_k}"  # noqa: E501
        cache_str = f"{query}_{config_hash}"
        key_hash = hashlib.sha256(cache_str.encode("utf-8")).hexdigest()
        cache_key = f"cache:query:{key_hash}"

        cached = await self.redis.get(cache_key)
        if cached:
            data = json.loads(cached)
            data["raw_results"] = [RetrievalResult(**r) for r in data["raw_results"]]
            return data  # type: ignore

        start_time = time.time()
        with tracer.start_as_current_span("retrieval.pipeline") as span:
            if pipeline_id:
                span.set_attribute("pipeline_id", pipeline_id)
            if run_id:
                span.set_attribute("run_id", run_id)

            processed_query = await self.query_processor.process_query(
                query, prompt_variant=prompt_variant
            )
            retrieval_k = max(k, 60)
            retrieved_results = await self.retriever.retrieve(
                processed_query,
                k=retrieval_k,
                use_hyde=use_hyde,
                pipeline_id=pipeline_id,
                run_id=run_id,
                rrf_weights=rrf_weights,
                use_cache=use_cache,
                dense_k=dense_k,
                sparse_k=sparse_k,
                rrf_k=rrf_k,
            )
            reranked_results = await self.reranker.rerank(
                query, retrieved_results, top_n=40, pipeline_id=pipeline_id, run_id=run_id
            )

            final_results = reranked_results[:k]

            self.context_assembler.token_budget = token_budget
            assembled_context = self.context_assembler.assemble(
                final_results, pipeline_id=pipeline_id, run_id=run_id
            )

            span.set_attribute("final_chunks", len(final_results))

            duration = time.time() - start_time
            retrieval_latency.labels(strategy="full_pipeline").observe(duration)

            result_data = {
                "query": processed_query.original_query,
                "expanded_queries": processed_query.expanded_queries,
                "query_type": processed_query.query_type,
                "context_data": assembled_context,
                "raw_results": final_results,
            }

            cache_payload = result_data.copy()
            cache_payload["raw_results"] = [r.dict() for r in final_results]
            await self.redis.setex(cache_key, 1800, json.dumps(cache_payload))

            return result_data
