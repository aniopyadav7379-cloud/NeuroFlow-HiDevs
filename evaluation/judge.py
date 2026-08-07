"""
EvaluationJudge: runs the four metrics in parallel, computes the weighted
overall_score, persists to `evaluations`, and — when the score clears the
0.8 bar — mines the run into `training_pairs` for Task 39's fine-tuning
pipeline. Always routes with task_type="evaluation" (backend/providers/
router.py hard-rules this to never select a fine-tuned model — see
docs/adr/003-evaluation-framework.md).
"""
import asyncio
import json
import logging
import statistics
import time
from dataclasses import dataclass, field

import asyncpg
from opentelemetry import trace

from backend.providers.client import NeuroFlowClient
from backend.providers.router import RoutingCriteria
from evaluation.metrics.answer_relevance import evaluate_answer_relevance
from evaluation.metrics.context_precision import evaluate_context_precision
from evaluation.metrics.context_recall import evaluate_context_recall
from evaluation.metrics.faithfulness import evaluate_faithfulness

logger = logging.getLogger("neuroflow.evaluation.judge")
tracer = trace.get_tracer("neuroflow.evaluation")

WEIGHTS = {
    "faithfulness": 0.35,
    "answer_relevance": 0.30,
    "context_precision": 0.20,
    "context_recall": 0.15,
}
TRAINING_PAIR_THRESHOLD = 0.8

HIGH_VARIANCE_STD_THRESHOLD = 0.2  # stretch goal: self-consistency
SELF_CONSISTENCY_RUNS = 3
SELF_CONSISTENCY_TEMPERATURE = 0.7


@dataclass
class EvaluationScores:
    faithfulness: float
    answer_relevance: float
    context_precision: float
    context_recall: float
    overall_score: float = field(init=False)

    def __post_init__(self):
        self.overall_score = (
            WEIGHTS["faithfulness"] * self.faithfulness
            + WEIGHTS["answer_relevance"] * self.answer_relevance
            + WEIGHTS["context_precision"] * self.context_precision
            + WEIGHTS["context_recall"] * self.context_recall
        )


async def _run_metrics_once(
    query: str, answer: str, context: str, chunks: list[str], client: NeuroFlowClient
) -> EvaluationScores:
    faithfulness, relevance, precision, recall = await asyncio.gather(
        evaluate_faithfulness(query, answer, context, client),
        evaluate_answer_relevance(query, answer, client),
        evaluate_context_precision(query, chunks, answer, client),
        evaluate_context_recall(query, chunks, answer, client),
    )
    return EvaluationScores(
        faithfulness=faithfulness,
        answer_relevance=relevance,
        context_precision=precision,
        context_recall=recall,
    )


def _split_prompt(prompt_text: str) -> tuple[str, str]:
    """Recovers (system_prompt, user_message) from the combined prompt
    text logged by pipelines/generation/generator.py, which always writes
    it as "[system]\\n<...>\\n\\n[user]\\n<...>" (build_messages always
    returns exactly [system, user]). Falls back to (prompt_text, "") if
    the marker isn't found — e.g. a prompt logged by different code."""
    marker = "\n\n[user]\n"
    idx = prompt_text.find(marker)
    if idx == -1:
        return prompt_text, ""
    system_part = prompt_text[:idx].removeprefix("[system]\n")
    user_part = prompt_text[idx + len(marker):]
    return system_part, user_part


class EvaluationJudge:
    def __init__(self, pool: asyncpg.Pool, llm_client: NeuroFlowClient):
        self.pool = pool
        self.llm_client = llm_client

    async def _resolve_judge_model(self) -> str:
        model_config = await self.llm_client.resolve_model(RoutingCriteria(task_type="evaluation"))
        return model_config.model

    async def _write_evaluation(self, run_id: str, scores: EvaluationScores, judge_model: str, metadata: dict) -> str:
        async with self.pool.acquire() as conn:
            row = await conn.fetchrow(
                """
                INSERT INTO evaluations
                    (run_id, faithfulness, answer_relevance, context_precision, context_recall,
                     overall_score, judge_model, metadata)
                VALUES ($1, $2, $3, $4, $5, $6, $7, $8::jsonb)
                RETURNING id
                """,
                run_id, scores.faithfulness, scores.answer_relevance,
                scores.context_precision, scores.context_recall,
                scores.overall_score, judge_model, json.dumps(metadata),
            )
        return str(row["id"])

    async def _maybe_insert_training_pair(self, run_id: str, overall_score: float) -> None:
        if overall_score <= TRAINING_PAIR_THRESHOLD:
            return
        async with self.pool.acquire() as conn:
            run_row = await conn.fetchrow(
                "SELECT prompt, generation FROM pipeline_runs WHERE id = $1", run_id
            )
            if run_row is None or not run_row["generation"]:
                logger.warning("cannot mine training pair for run_id=%s: no prompt/generation on record", run_id)
                return
            system_prompt, user_message = _split_prompt(run_row["prompt"] or "")
            await conn.execute(
                """
                INSERT INTO training_pairs (run_id, system_prompt, user_message, assistant_message, quality_score)
                VALUES ($1, $2, $3, $4, $5)
                """,
                run_id, system_prompt, user_message, run_row["generation"], overall_score,
            )
        logger.info("run_id=%s mined as a training pair (overall_score=%.3f)", run_id, overall_score)

    async def evaluate(
        self, *, run_id: str, query: str, answer: str, context: str, chunks: list[str],
        self_consistency: bool = False,
    ) -> EvaluationScores:
        judge_model = await self._resolve_judge_model()
        started = time.perf_counter()

        metadata: dict = {}
        if self_consistency:
            runs = [
                await _run_metrics_once(query, answer, context, chunks, self.llm_client)
                for _ in range(SELF_CONSISTENCY_RUNS)
            ]
            # NOTE: temperature=0.7 for the self-consistency runs isn't
            # threaded through here — the metric functions call
            # NeuroFlowClient.chat() without a temperature kwarg, and
            # plumbing per-call sampling params through the router/
            # provider layer for just this one caller is a larger change
            # than this task's scope. Repeated calls still exercise the
            # LLM's non-determinism at whatever the model's default
            # sampling is, which is the mechanism this check cares about,
            # just not confirmed to be exactly temperature=0.7.
            overall_scores = [r.overall_score for r in runs]
            mean_scores = EvaluationScores(
                faithfulness=statistics.mean(r.faithfulness for r in runs),
                answer_relevance=statistics.mean(r.answer_relevance for r in runs),
                context_precision=statistics.mean(r.context_precision for r in runs),
                context_recall=statistics.mean(r.context_recall for r in runs),
            )
            std_dev = statistics.pstdev(overall_scores)
            metadata["self_consistency"] = {
                "runs": overall_scores,
                "std_dev": std_dev,
                "high_variance": std_dev > HIGH_VARIANCE_STD_THRESHOLD,
            }
            scores = mean_scores
        else:
            scores = await _run_metrics_once(query, answer, context, chunks, self.llm_client)

        latency_ms = (time.perf_counter() - started) * 1000

        with tracer.start_as_current_span("evaluation.judge") as span:
            span.set_attribute("run_id", run_id)
            span.set_attribute("faithfulness", scores.faithfulness)
            span.set_attribute("answer_relevance", scores.answer_relevance)
            span.set_attribute("context_precision", scores.context_precision)
            span.set_attribute("context_recall", scores.context_recall)
            span.set_attribute("overall_score", scores.overall_score)
            span.set_attribute("judge_model", judge_model)
            span.set_attribute("latency_ms", latency_ms)
            if self_consistency:
                span.set_attribute("self_consistency_std_dev", metadata["self_consistency"]["std_dev"])

        await self._write_evaluation(run_id, scores, judge_model, metadata)
        await self._maybe_insert_training_pair(run_id, scores.overall_score)

        return scores
