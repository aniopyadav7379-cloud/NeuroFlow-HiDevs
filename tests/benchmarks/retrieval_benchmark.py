import asyncio
import json
import logging
import math
from typing import List, Dict, Any

from backend.db.pool import create_pool, get_pool, close_pool
from backend.providers.client import NeuroFlowClient
from backend.providers.base import ChatMessage
from backend.providers.router import RoutingCriteria
from pipelines.retrieval.pipeline import RetrievalPipeline

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

async def generate_synthetic_benchmark_set(pool, client: NeuroFlowClient, num_samples: int = 50) -> List[Dict[str, Any]]:
    test_set = []
    async with pool.acquire() as conn:
        rows = await conn.fetch("""
            SELECT id, content 
            FROM chunks 
            WHERE length(content) > 100 
            ORDER BY RANDOM() 
            LIMIT $1
        """, num_samples)
        
    if not rows:
        logger.warning("No chunks found in the database. Generating fake test set for benchmarking.")
        return [{"query": f"Test question {i}", "relevant_chunk_ids": [f"chunk_{i}"]} for i in range(num_samples)]
        
    criteria = RoutingCriteria(task_type="evaluation")
    for row in rows:
        chunk_id = str(row['id'])
        content = row['content']
        prompt = f"Given this text, generate a single clear, specific question that this text perfectly answers. Text: {content}\n\nQuestion:"
        try:
            result = await client.chat([ChatMessage(role="user", content=prompt)], criteria)
            question = result.message.content.strip()
            test_set.append({
                "query": question,
                "relevant_chunk_ids": [chunk_id]
            })
        except Exception as e:
            logger.error(f"Failed to generate question for {chunk_id}: {e}")
            
    return test_set

def calculate_metrics(test_set, results_list, k_values=[5, 10]):
    metrics = {"hr@5": 0.0, "hr@10": 0.0, "mrr@10": 0.0, "ndcg@10": 0.0}
    num_queries = len(test_set)
    if num_queries == 0:
        return metrics
        
    for i, test in enumerate(test_set):
        relevant_ids = test["relevant_chunk_ids"]
        results = results_list[i]
        
        # Rank of the first relevant chunk
        rank = next((j + 1 for j, r in enumerate(results) if str(r.chunk_id) in relevant_ids), None)
        
        if rank is not None:
            if rank <= 5:
                metrics["hr@5"] += 1.0
            if rank <= 10:
                metrics["hr@10"] += 1.0
                metrics["mrr@10"] += 1.0 / rank
                metrics["ndcg@10"] += 1.0 / math.log2(rank + 1)
                
    return {k: v / num_queries for k, v in metrics.items()}

async def run_benchmark():
    from redis.asyncio import Redis
    from backend.config import settings
    
    redis_client = Redis(host=settings.redis_host, port=settings.redis_port, password=settings.redis_password)
    client = NeuroFlowClient(redis_client)
    
    await create_pool()
    pool = get_pool()
    pipeline = RetrievalPipeline(pool, client)
    
    logger.info("Generating/loading synthetic benchmark set (50 questions)...")
    test_set = await generate_synthetic_benchmark_set(pool, client, num_samples=50)
    
    strategies = {
        "Dense-only": {"dense_k": 10, "sparse_k": 0, "reranker": "none", "top_k_after_rerank": 10},
        "Sparse-only": {"dense_k": 0, "sparse_k": 10, "reranker": "none", "top_k_after_rerank": 10},
        "Hybrid (RRF)": {"dense_k": 10, "sparse_k": 10, "reranker": "none", "top_k_after_rerank": 10},
        "Hybrid+Reranked": {"dense_k": 10, "sparse_k": 10, "reranker": "cohere", "top_k_after_rerank": 10}
    }
    
    final_results = {}
    
    for name, config in strategies.items():
        logger.info(f"Running benchmark for {name}...")
        results_list = []
        for test in test_set:
            try:
                # If pipeline retrieve throws error because DB is empty, mock results for testing
                res = await pipeline.retrieve(test["query"], config=config, k=10)
                results_list.append(res)
            except Exception as e:
                logger.error(f"Retrieve error: {e}")
                results_list.append([])
                
        metrics = calculate_metrics(test_set, results_list)
        final_results[name] = metrics
        
    # Generate markdown table
    md_content = "# Retrieval Benchmark Results\n\n"
    md_content += "| Strategy | Hit Rate@5 | Hit Rate@10 | MRR@10 | NDCG@10 |\n"
    md_content += "|---|---|---|---|---|\n"
    for name, metrics in final_results.items():
        md_content += f"| {name} | {metrics['hr@5']:.4f} | {metrics['hr@10']:.4f} | {metrics['mrr@10']:.4f} | {metrics['ndcg@10']:.4f} |\n"
        
    md_content += "\n## Analysis\n"
    dense_mrr = final_results["Dense-only"]["mrr@10"]
    hybrid_re_mrr = final_results["Hybrid+Reranked"]["mrr@10"]
    
    if dense_mrr > 0:
        improvement = ((hybrid_re_mrr - dense_mrr) / dense_mrr) * 100
        md_content += f"Hybrid+Reranked outperformed Dense-only on MRR@10 by {improvement:.1f}%.\n"
        
        if improvement >= 15.0:
            md_content += "✅ Target met: Hybrid+Reranked outperformed Dense-only by at least 15%.\n"
        else:
            md_content += "❌ Target failed: Hybrid+Reranked did not outperform Dense-only by 15%.\n"
    else:
        md_content += "Dense-only MRR is 0, cannot calculate improvement.\n"
        
    with open("tests/benchmarks/retrieval_benchmark_results.md", "w", encoding="utf-8") as f:
        f.write(md_content)
        
    logger.info("Benchmark complete. Results saved to tests/benchmarks/retrieval_benchmark_results.md")
    
    await close_pool()
    await redis_client.aclose()

if __name__ == "__main__":
    asyncio.run(run_benchmark())
