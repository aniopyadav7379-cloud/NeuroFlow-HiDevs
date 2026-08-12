"""
PATCH /runs/{run_id}/rating — human feedback on a generation. When both an
automated overall_score and a human rating exist and they disagree by more
than 0.3 (on the same 0-1 scale), flags the evaluation `calibration_needed`
so miscalibration is visible rather than silently averaged away.
"""
import json
import logging

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

logger = logging.getLogger("neuroflow.api.runs")
router = APIRouter()

CALIBRATION_DISAGREEMENT_THRESHOLD = 0.3


class RatingRequest(BaseModel):
    rating: int = Field(ge=1, le=5)


class RatingResponse(BaseModel):
    run_id: str
    user_rating: int
    automated_overall_score: float | None
    calibration_needed: bool


@router.patch("/runs/{run_id}/rating", response_model=RatingResponse)
async def rate_run(request: Request, run_id: str, body: RatingRequest) -> RatingResponse:
    pool = request.app.state.pg_pool

    async with pool.acquire() as conn:
        # A run can in principle have more than one evaluations row (e.g.
        # if it's ever re-scored), so this takes the most recent one —
        # that's the one a human reviewing the run right now is rating.
        eval_row = await conn.fetchrow(
            """
            SELECT id, overall_score, metadata FROM evaluations
            WHERE run_id = $1
            ORDER BY evaluated_at DESC
            LIMIT 1
            """,
            run_id,
        )
        if eval_row is None:
            raise HTTPException(
                status_code=404,
                detail=f"no evaluation found for run_id={run_id} — the run may not have been evaluated yet",
            )

        automated_score = eval_row["overall_score"]
        calibration_needed = False
        if automated_score is not None:
            human_normalized = body.rating / 5.0
            calibration_needed = abs(automated_score - human_normalized) > CALIBRATION_DISAGREEMENT_THRESHOLD

        metadata = eval_row["metadata"] or {}
        if isinstance(metadata, str):
            metadata = json.loads(metadata)
        metadata["calibration_needed"] = calibration_needed

        await conn.execute(
            "UPDATE evaluations SET user_rating = $2, metadata = $3::jsonb WHERE id = $1",
            eval_row["id"], body.rating, json.dumps(metadata),
        )

    if calibration_needed:
        logger.warning(
            "run_id=%s flagged calibration_needed: automated=%.3f human=%.3f (rating=%d/5)",
            run_id, automated_score, body.rating / 5.0, body.rating,
        )

    return RatingResponse(
        run_id=run_id,
        user_rating=body.rating,
        automated_overall_score=automated_score,
        calibration_needed=calibration_needed,
    )


@router.get("/runs/{run_id}")
async def get_run(request: Request, run_id: str):
    """Single-run detail — used by the frontend playground (polling for
    the async evaluation result) and the evaluation feed's expand-to-see-
    full-answer card."""
    pool = request.app.state.pg_pool

    async with pool.acquire() as conn:
        run_row = await conn.fetchrow(
            """
            SELECT id, pipeline_id, query, generation, status, latency_ms,
                   retrieval_latency_ms, input_tokens, output_tokens, model_used, created_at
            FROM pipeline_runs WHERE id = $1
            """,
            run_id,
        )
        if run_row is None:
            raise HTTPException(status_code=404, detail=f"run {run_id} not found")

        eval_row = await conn.fetchrow(
            """
            SELECT overall_score, faithfulness, answer_relevance, context_precision, context_recall, user_rating
            FROM evaluations WHERE run_id = $1
            ORDER BY evaluated_at DESC LIMIT 1
            """,
            run_id,
        )

    return {
        "run_id": str(run_row["id"]),
        "pipeline_id": str(run_row["pipeline_id"]),
        "query": run_row["query"],
        "generation": run_row["generation"],
        "status": run_row["status"],
        "latency_ms": run_row["latency_ms"],
        "retrieval_latency_ms": run_row["retrieval_latency_ms"],
        "input_tokens": run_row["input_tokens"],
        "output_tokens": run_row["output_tokens"],
        "model_used": run_row["model_used"],
        "created_at": run_row["created_at"].isoformat(),
        "evaluation": (
            {
                "overall_score": eval_row["overall_score"],
                "faithfulness": eval_row["faithfulness"],
                "answer_relevance": eval_row["answer_relevance"],
                "context_precision": eval_row["context_precision"],
                "context_recall": eval_row["context_recall"],
                "user_rating": eval_row["user_rating"],
            }
            if eval_row
            else None
        ),
    }
