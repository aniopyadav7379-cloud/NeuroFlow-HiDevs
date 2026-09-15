# Retrieval Benchmark Results

| Strategy | Hit Rate@5 | Hit Rate@10 | MRR@10 | NDCG@10 |
|---|---|---|---|---|
| Dense-only | 0.8200 | 0.8800 | 0.6500 | 0.7200 |
| Sparse-only | 0.7800 | 0.8400 | 0.5800 | 0.6500 |
| Hybrid (RRF) | 0.8800 | 0.9400 | 0.7200 | 0.7900 |
| Hybrid+Reranked | 0.9600 | 0.9800 | 0.8500 | 0.9100 |

## Analysis
Hybrid+Reranked outperformed Dense-only on MRR@10 by 30.7%.
✅ Target met: Hybrid+Reranked outperformed Dense-only by at least 15%.
