"""
Training data extraction: pulls qualifying rows from `training_pairs`,
validates each against the task's rules, and writes the survivors to
training_data/{job_id}.jsonl in OpenAI fine-tuning message format.

Schema note: the task spec describes the user-rating filter as living on
"the source pipeline_runs row" ("user_rating >= 4 OR user_rating IS
NULL"). In NeuroFlow's actual schema (Task 37), user_rating lives on
`evaluations` (set via PATCH /runs/{run_id}/rating), not on
`pipeline_runs` — there is no pipeline_runs.user_rating column. This
module applies the identical filter semantics against evaluations.user_rating
instead, which is where that data actually is.
"""
import json
import logging
import re
from dataclasses import dataclass, field
from pathlib import Path

import asyncpg
import tiktoken

from backend.providers.client import NeuroFlowClient
from evaluation.metrics.faithfulness import evaluate_faithfulness

logger = logging.getLogger("neuroflow.finetuning.extractor")

QUALITY_SCORE_THRESHOLD = 0.82
ASSISTANT_MIN_TOKENS = 50
ASSISTANT_MAX_TOKENS = 2000
FAITHFULNESS_MIN = 0.8

CITATION_RE = re.compile(r"\[Source \d+\]")
EMAIL_RE = re.compile(r"[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+")
# Permissive US/international-ish phone pattern: optional country code,
# then a 10-digit number in any of the common separator styles.
PHONE_RE = re.compile(r"(\+?\d{1,3}[-.\s]?)?\(?\d{3}\)?[-.\s]?\d{3}[-.\s]?\d{4}\b")

_TOKEN_ENCODING = "cl100k_base"
_encoding = None


def _get_encoding():
    global _encoding
    if _encoding is None:
        _encoding = tiktoken.get_encoding(_TOKEN_ENCODING)
    return _encoding


def _count_tokens(text: str) -> int:
    return len(_get_encoding().encode(text)) if text else 0


def _extract_query_from_user_message(user_message: str) -> str:
    """user_message is stored as the full "<context>...</context>\\n\\n{query}"
    blob (pipelines/generation/prompt_builder.build_messages' exact user
    content format). The PII check applies to the QUERY only — the
    context comes from ingested documents and legitimately contains
    emails/phone numbers sometimes (a contract's signature block, a
    support doc's contact info), which shouldn't disqualify training data
    that never asked for that PII."""
    marker = "</context>\n\n"
    idx = user_message.find(marker)
    if idx == -1:
        return user_message
    return user_message[idx + len(marker):]


def _extract_context_from_user_message(user_message: str) -> str:
    match = re.search(r"<context>\n(.*)\n</context>", user_message, flags=re.DOTALL)
    return match.group(1) if match else ""


@dataclass
class RejectedPair:
    training_pair_id: str
    reason: str


@dataclass
class ExtractionResult:
    valid_entries: list[dict] = field(default_factory=list)
    valid_training_pair_ids: list[str] = field(default_factory=list)
    rejected: list[RejectedPair] = field(default_factory=list)
    quality_scores: list[float] = field(default_factory=list)


async def fetch_candidate_pairs(pool: asyncpg.Pool, quality_threshold: float) -> list[asyncpg.Record]:
    async with pool.acquire() as conn:
        return await conn.fetch(
            """
            SELECT
                tp.id, tp.run_id, tp.system_prompt, tp.user_message, tp.assistant_message,
                tp.quality_score, r.query,
                ev.faithfulness, ev.user_rating
            FROM training_pairs tp
            JOIN pipeline_runs r ON r.id = tp.run_id
            LEFT JOIN LATERAL (
                SELECT faithfulness, user_rating
                FROM evaluations
                WHERE run_id = tp.run_id
                ORDER BY evaluated_at DESC
                LIMIT 1
            ) ev ON true
            WHERE tp.quality_score >= $1
              AND tp.included_in_job IS NULL
              AND (ev.user_rating >= 4 OR ev.user_rating IS NULL)
            ORDER BY tp.created_at
            """,
            quality_threshold,
        )


async def validate_pair(row: asyncpg.Record, llm_client: NeuroFlowClient) -> tuple[dict | None, str | None]:
    """Returns (jsonl_entry, None) if valid, or (None, rejection_reason)."""
    assistant_message = row["assistant_message"] or ""
    user_message = row["user_message"] or ""
    system_prompt = row["system_prompt"] or ""

    token_count = _count_tokens(assistant_message)
    if not (ASSISTANT_MIN_TOKENS <= token_count <= ASSISTANT_MAX_TOKENS):
        return None, f"assistant message token count {token_count} outside [{ASSISTANT_MIN_TOKENS}, {ASSISTANT_MAX_TOKENS}]"

    if not CITATION_RE.search(assistant_message):
        return None, "assistant message contains no [Source N] citation"

    query_text = _extract_query_from_user_message(user_message)
    if EMAIL_RE.search(query_text) or PHONE_RE.search(query_text):
        return None, "query contains a PII pattern (email or phone number)"

    faithfulness = row["faithfulness"]
    if faithfulness is None:
        context = _extract_context_from_user_message(user_message)
        logger.info("faithfulness missing for training_pair_id=%s, re-evaluating live", row["id"])
        faithfulness = await evaluate_faithfulness(query_text, assistant_message, context, llm_client)

    if faithfulness <= FAITHFULNESS_MIN:
        return None, f"faithfulness score {faithfulness:.3f} <= {FAITHFULNESS_MIN}"

    entry = {
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_message},
            {"role": "assistant", "content": assistant_message},
        ]
    }
    return entry, None


async def extract_and_validate(
    pool: asyncpg.Pool, llm_client: NeuroFlowClient, quality_threshold: float = QUALITY_SCORE_THRESHOLD
) -> ExtractionResult:
    candidates = await fetch_candidate_pairs(pool, quality_threshold)

    result = ExtractionResult()
    for row in candidates:
        entry, reason = await validate_pair(row, llm_client)
        if entry is not None:
            result.valid_entries.append(entry)
            result.valid_training_pair_ids.append(str(row["id"]))
            result.quality_scores.append(row["quality_score"])
        else:
            result.rejected.append(RejectedPair(training_pair_id=str(row["id"]), reason=reason))

    return result


def write_jsonl(training_data_dir: str, job_id: str, entries: list[dict]) -> str:
    out_dir = Path(training_data_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / f"{job_id}.jsonl"
    with out_path.open("w") as f:
        for entry in entries:
            f.write(json.dumps(entry) + "\n")
    return str(out_path)


async def mark_pairs_included(pool: asyncpg.Pool, training_pair_ids: list[str], job_id: str) -> None:
    if not training_pair_ids:
        return
    async with pool.acquire() as conn:
        await conn.execute(
            "UPDATE training_pairs SET included_in_job = $2 WHERE id = ANY($1::uuid[])",
            training_pair_ids, job_id,
        )
