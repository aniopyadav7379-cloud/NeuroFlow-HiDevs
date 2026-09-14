from typing import Any
from uuid import UUID


class PipelineOptimizer:
    def __init__(self, pool: Any) -> None:  # noqa: ANN401
        self.pool = pool

    async def get_suggestions(self, pipeline_id: UUID) -> list[dict[str, str]]:
        async with self.pool.acquire() as conn:
            stats = await conn.fetchrow(
                """
                SELECT 
                    AVG(e.faithfulness) as avg_faithfulness,
                    AVG(e.answer_relevance) as avg_relevance,
                    AVG(e.context_precision) as avg_precision,
                    AVG(e.context_recall) as avg_recall
                FROM pipeline_runs pr
                JOIN evaluations e ON e.run_id = pr.id
                WHERE pr.pipeline_id = $1
                """,
                pipeline_id,
            )

        if not stats:
            return [
                {"type": "info", "message": "Not enough evaluation data to generate suggestions."}
            ]

        suggestions = []

        precision = stats["avg_precision"]
        recall = stats["avg_recall"]
        faithfulness = stats["avg_faithfulness"]
        relevance = stats["avg_relevance"]

        # Only generate suggestions if we have some scores
        if precision is not None and precision < 0.7:
            suggestions.append(
                {
                    "metric": "context_precision",
                    "score": round(precision, 2),
                    "suggestion": "Context precision is consistently low. Suggest reducing 'top_k_after_rerank' to filter out irrelevant chunks before generation.",  # noqa: E501
                }
            )

        if recall is not None and recall < 0.7:
            suggestions.append(
                {
                    "metric": "context_recall",
                    "score": round(recall, 2),
                    "suggestion": "Context recall is low, meaning important information is missed. Suggest increasing 'dense_k' or 'sparse_k' to retrieve a wider net of candidates.",  # noqa: E501
                }
            )

        if faithfulness is not None and faithfulness < 0.8:
            suggestions.append(
                {
                    "metric": "faithfulness",
                    "score": round(faithfulness, 2),
                    "suggestion": "Faithfulness is below optimal. The model might be hallucinating. Suggest decreasing 'temperature' or limiting 'max_context_tokens' to reduce confusion.",  # noqa: E501
                }
            )

        if relevance is not None and relevance < 0.8:
            suggestions.append(
                {
                    "metric": "answer_relevance",
                    "score": round(relevance, 2),
                    "suggestion": "Answer relevance is low. Suggest experimenting with a different 'system_prompt_variant' to better constrain the generation.",  # noqa: E501
                }
            )

        if not suggestions:
            suggestions.append(
                {
                    "type": "success",
                    "message": "All metrics are looking great! No configuration changes suggested at this time.",  # noqa: E501
                }
            )

        return suggestions
