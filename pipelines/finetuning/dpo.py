"""
DPO (Direct Preference Optimization) data format — stretch goal. Where
the same query has both a highly-rated response (user_rating >= 4) and a
poorly-rated one (user_rating <= 2), format them as a preference pair
instead of (or alongside) the SFT format extractor.py produces. This
targets frameworks like Hugging Face TRL that train directly on
(prompt, chosen, rejected) triples rather than single good examples.
"""
import logging
from collections import defaultdict
from dataclasses import dataclass

import asyncpg

logger = logging.getLogger("neuroflow.finetuning.dpo")

CHOSEN_RATING_MIN = 4
REJECTED_RATING_MAX = 2


@dataclass
class DPOPair:
    prompt: str
    chosen: str
    rejected: str
    chosen_run_id: str
    rejected_run_id: str


async def fetch_rated_runs(pool: asyncpg.Pool) -> list[asyncpg.Record]:
    async with pool.acquire() as conn:
        return await conn.fetch(
            """
            SELECT r.id AS run_id, r.query, r.generation, ev.user_rating
            FROM pipeline_runs r
            JOIN LATERAL (
                SELECT user_rating FROM evaluations
                WHERE run_id = r.id
                ORDER BY evaluated_at DESC
                LIMIT 1
            ) ev ON true
            WHERE ev.user_rating IS NOT NULL AND r.generation IS NOT NULL AND r.generation != ''
            """
        )


def build_dpo_pairs(rated_runs: list[asyncpg.Record]) -> list[DPOPair]:
    """Groups runs by identical query text, and for every group that has
    at least one "chosen" (rating>=4) and one "rejected" (rating<=2)
    response, pairs the single highest-rated with the single
    lowest-rated. A query with only good or only bad responses produces
    no pair — DPO needs a genuine contrast, not just a quality label."""
    by_query: dict[str, list[asyncpg.Record]] = defaultdict(list)
    for row in rated_runs:
        by_query[row["query"]].append(row)

    pairs: list[DPOPair] = []
    for query, runs in by_query.items():
        chosen_candidates = [r for r in runs if r["user_rating"] >= CHOSEN_RATING_MIN]
        rejected_candidates = [r for r in runs if r["user_rating"] <= REJECTED_RATING_MAX]
        if not chosen_candidates or not rejected_candidates:
            continue

        best = max(chosen_candidates, key=lambda r: r["user_rating"])
        worst = min(rejected_candidates, key=lambda r: r["user_rating"])

        pairs.append(
            DPOPair(
                prompt=query,
                chosen=best["generation"],
                rejected=worst["generation"],
                chosen_run_id=str(best["run_id"]),
                rejected_run_id=str(worst["run_id"]),
            )
        )

    return pairs


async def extract_dpo_pairs(pool: asyncpg.Pool) -> list[DPOPair]:
    rated_runs = await fetch_rated_runs(pool)
    return build_dpo_pairs(rated_runs)


def dpo_pair_to_jsonl_entry(pair: DPOPair) -> dict:
    return {"prompt": pair.prompt, "chosen": pair.chosen, "rejected": pair.rejected}


def write_dpo_jsonl(training_data_dir: str, job_id: str, pairs: list[DPOPair]) -> str:
    import json
    from pathlib import Path

    out_dir = Path(training_data_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / f"{job_id}-dpo.jsonl"
    with out_path.open("w") as f:
        for pair in pairs:
            f.write(json.dumps(dpo_pair_to_jsonl_entry(pair)) + "\n")
    return str(out_path)
