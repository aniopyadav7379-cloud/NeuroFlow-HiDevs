import asyncio
import json
import logging
from typing import Any
from uuid import UUID

from opentelemetry import trace

from backend.providers.client import NeuroFlowClient
from evaluation.metrics.answer_relevance import evaluate_answer_relevance
from evaluation.metrics.context_precision import evaluate_context_precision
from evaluation.metrics.context_recall import evaluate_context_recall
from evaluation.metrics.faithfulness import evaluate_faithfulness

logger = logging.getLogger(__name__)



tracer = trace.get_tracer(__name__)


class EvaluationJudge:
    def __init__(self, db_pool: Any, redis_client: Any) -> None:  # noqa: ANN401
        self.db_pool = db_pool
        self.redis_client = redis_client
        self.client = NeuroFlowClient(redis_client)

    async def _run_metrics(
        self,
        query: str,
        generation: str,
        context: str,
        chunks: list[str],
        temperature: float | None = None,  # noqa: E501
    ) -> tuple[float, float, float, float]:
        kwargs: dict[str, Any] = {"temperature": temperature} if temperature is not None else {}

        faithfulness_task = evaluate_faithfulness(query, generation, context, self.client, **kwargs)
        relevance_task = evaluate_answer_relevance(query, generation, self.client, **kwargs)
        precision_task = evaluate_context_precision(
            query, chunks, generation, self.client, **kwargs
        )
        recall_task = evaluate_context_recall(query, chunks, generation, self.client, **kwargs)

        return await asyncio.gather(faithfulness_task, relevance_task, precision_task, recall_task)

    async def evaluate_run(self, run_id: str) -> float | None:
        # Fetch the run data
        async with self.db_pool.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT query, retrieved_chunk_ids, generation, prompt FROM pipeline_runs WHERE id = $1",  # noqa: E501
                UUID(run_id),
            )
            if not row:
                logger.info(f"Run {run_id} not found for evaluation.")
                return None

            query = row["query"]
            generation = row["generation"]
            prompt = row["prompt"]
            chunk_ids = row["retrieved_chunk_ids"] or []

            # Fetch the chunks content
            chunks = []
            if chunk_ids:
                records = await conn.fetch(
                    "SELECT content FROM chunks WHERE id = ANY($1)", chunk_ids
                )
                chunks = [r["content"] for r in records]

        context = "\n".join(chunks)

        with tracer.start_as_current_span("evaluation.judge") as span:
            # Run 3 times with temperature 0.7
            tasks = [
                self._run_metrics(query, generation, context, chunks, temperature=0.7)
                for _ in range(3)
            ]
            results = await asyncio.gather(*tasks)

            # results is a list of 3 tuples: [(f1, a1, p1, r1), (f2, a2, p2, r2), (f3, a3, p3, r3)]
            faithfulness_scores = [res[0] for res in results]
            relevance_scores = [res[1] for res in results]
            precision_scores = [res[2] for res in results]
            recall_scores = [res[3] for res in results]

            def compute_overall(f: float, a: float, p: float, r: float) -> float:
                return 0.35 * f + 0.30 * a + 0.20 * p + 0.15 * r

            overall_scores = [
                compute_overall(f, a, p, r)
                for f, a, p, r in zip(
                    faithfulness_scores, relevance_scores, precision_scores, recall_scores
                )
            ]

            avg_faithfulness = sum(faithfulness_scores) / 3.0
            avg_relevance = sum(relevance_scores) / 3.0
            avg_precision = sum(precision_scores) / 3.0
            avg_recall = sum(recall_scores) / 3.0
            avg_overall = sum(overall_scores) / 3.0

            # Compute standard deviation of overall scores
            mean = avg_overall
            variance = sum((x - mean) ** 2 for x in overall_scores) / 3.0
            std_dev = variance**0.5

            metadata = {}
            if std_dev > 0.2:
                metadata["high_variance"] = True

            # Add attributes to span
            span.set_attribute("faithfulness", avg_faithfulness)
            span.set_attribute("answer_relevance", avg_relevance)
            span.set_attribute("context_precision", avg_precision)
            span.set_attribute("context_recall", avg_recall)
            span.set_attribute("overall_score", avg_overall)
            span.set_attribute("std_dev", std_dev)

            # Write to evaluations table
            async with self.db_pool.acquire() as conn:
                await conn.execute(
                    """
                    INSERT INTO evaluations (
                        run_id, faithfulness, answer_relevance, context_precision, context_recall,
                        overall_score, judge_model, metadata
                    ) VALUES ($1, $2, $3, $4, $5, $6, $7, $8)
                    """,
                    UUID(run_id),
                    avg_faithfulness,
                    avg_relevance,
                    avg_precision,
                    avg_recall,
                    avg_overall,
                    "routed_evaluator",
                    json.dumps(metadata),
                )

                # If high quality, mark as training pair candidate
                if avg_overall > 0.8:
                    await conn.execute(
                        """
                        INSERT INTO training_pairs (
                            run_id, system_prompt, user_message, assistant_message, quality_score
                        ) VALUES ($1, $2, $3, $4, $5)
                        """,
                        UUID(run_id),
                        prompt,
                        query,
                        generation,
                        avg_overall,
                    )

                    # Mark pipeline_runs row as a candidate training pair in metadata
                    await conn.execute(
                        """
                        UPDATE pipeline_runs 
                        SET metadata = jsonb_set(
                            COALESCE(metadata, '{}'::jsonb),
                            '{is_training_candidate}',
                            'true'::jsonb
                        )
                        WHERE id = $1
                        """,
                        UUID(run_id),
                    )

            return avg_overall
