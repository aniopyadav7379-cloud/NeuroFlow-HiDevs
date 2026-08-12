"""
Calibration check: run evaluate_faithfulness against evaluation/calibration/
annotated_set.json (30 human-scored (query, answer, context, human_score)
tuples) and compute Pearson correlation between automated and human
faithfulness scores. Must be > 0.85 before the evaluator is trusted.

NOT runnable without live LLM API keys (there's no automated score to
compute without calling the judge). The committed annotated_set.json is a
template with placeholder scores, not real human annotations — see its
header comment. Replace it with real annotations before trusting any
number this script prints.

Usage:
    python -m evaluation.calibration.run_calibration
"""
import asyncio
import json
import logging
import sys
from pathlib import Path

from backend.config import get_settings
from backend.providers.client import build_client
from evaluation.calibration.pearson import pearson_correlation
from evaluation.metrics.faithfulness import evaluate_faithfulness

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("neuroflow.evaluation.calibration")

CORRELATION_THRESHOLD = 0.85
ANNOTATED_SET_PATH = Path(__file__).parent / "annotated_set.json"
RESULTS_PATH = Path(__file__).parent.parent / "calibration_results.json"


async def run_calibration(annotated_set: list[dict]) -> dict:
    import redis.asyncio as redis

    settings = get_settings()
    redis_client = redis.from_url(settings.redis_url, decode_responses=True)
    llm_client = build_client(settings, redis_client)

    automated_scores = []
    human_scores = []
    per_example = []

    try:
        for example in annotated_set:
            score = await evaluate_faithfulness(
                example["query"], example["answer"], example["context"], llm_client
            )
            automated_scores.append(score)
            human_scores.append(example["human_score"])
            per_example.append({
                "query": example["query"],
                "automated_score": score,
                "human_score": example["human_score"],
                "abs_diff": abs(score - example["human_score"]),
            })
            logger.info(
                "query=%r automated=%.3f human=%.3f",
                example["query"][:60], score, example["human_score"],
            )
    finally:
        await redis_client.aclose()

    correlation = pearson_correlation(automated_scores, human_scores)

    return {
        "n_examples": len(annotated_set),
        "pearson_correlation": correlation,
        "threshold": CORRELATION_THRESHOLD,
        "passed": correlation > CORRELATION_THRESHOLD,
        "per_example": per_example,
    }


def main() -> None:
    annotated_set = json.loads(ANNOTATED_SET_PATH.read_text())
    if any(ex.get("human_score") == "REPLACE_WITH_REAL_HUMAN_SCORE" for ex in annotated_set):
        logger.error(
            "annotated_set.json at %s still contains placeholder scores — replace with "
            "real human-annotated (query, answer, context, human_score) tuples before "
            "running calibration.", ANNOTATED_SET_PATH,
        )
        sys.exit(1)

    results = asyncio.run(run_calibration(annotated_set))
    RESULTS_PATH.write_text(json.dumps(results, indent=2))

    logger.info(
        "Pearson correlation: %.4f (threshold: %.2f) — %s",
        results["pearson_correlation"], CORRELATION_THRESHOLD,
        "PASSED" if results["passed"] else "FAILED",
    )
    sys.exit(0 if results["passed"] else 1)


if __name__ == "__main__":
    main()
