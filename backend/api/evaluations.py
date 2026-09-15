import asyncio
import json
import logging
import uuid
from datetime import datetime
from typing import Any

import redis.asyncio as aioredis
from fastapi import APIRouter, Request
from opentelemetry import trace
from opentelemetry.propagate import extract
from pydantic import BaseModel, Field
from sse_starlette.sse import EventSourceResponse

from backend.config import settings
from backend.monitoring.metrics import eval_faithfulness, eval_overall

logger = logging.getLogger(__name__)



tracer = trace.get_tracer(__name__)

router = APIRouter(prefix="/evaluations", tags=["Evaluation"])


@router.get(
    "/stream",
    summary="Stream real-time evaluation metrics",
    description=(
        "Subscribe to real-time RAG evaluation results (faithfulness, answer relevance, "
        "context precision, context recall, overall score) via Server-Sent Events (SSE). "
        "Use this to power live observability dashboards. **Performance notes**: Uses "
        "Redis Pub/Sub under the hood. Keepalive pings are sent automatically."
    ),
    response_description=(
        "An SSE stream emitting `message` events containing the evaluation JSON dictionary."
    )
)
async def stream_evaluations(request: Request) -> Any:  # noqa: ANN401

    async def event_generator() -> Any:  # noqa: ANN401
        r = aioredis.from_url(
            settings.redis_url,
            decode_responses=True,
        )
        pubsub = r.pubsub()
        await pubsub.subscribe("evaluations:new")

        try:
            while True:
                if await request.is_disconnected():
                    break

                message = await pubsub.get_message(ignore_subscribe_messages=True, timeout=5.0)
                if message and message["type"] == "message":
                    yield {"event": "message", "data": message["data"]}
                elif message is None:
                    # Keepalive
                    yield {"event": "keepalive", "data": json.dumps({"type": "keepalive"})}
        finally:
            await pubsub.unsubscribe("evaluations:new")
            await pubsub.close()
            await r.aclose()

    return EventSourceResponse(event_generator())



class SimulateEval(BaseModel):
    pipeline_name: str = Field(
        "Test Pipeline", 
        description="The name of the pipeline to associate with the simulated evaluation run.",
        examples=["RAG Prod v2"]
    )
    query: str = Field(
        "What is the capital of France?",
        description="The synthetic or test query used for the simulated run.",
        examples=["How do I configure Redis?"]
    )


@router.post(
    "/simulate",
    summary="Simulate an evaluation run",
    description=(
        "Generates synthetic evaluation metrics (faithfulness, context precision, etc.) "
        "and publishes them to the Redis Pub/Sub stream for testing dashboard "
        "interactivity without invoking a real LLM judge."
    ),
    response_description=(
        "A JSON object containing the status and the simulated evaluation dictionary."
    )
)
async def simulate_eval(req: SimulateEval) -> Any:  # noqa: ANN401
    # Simulate a run ID and random metrics
    import random

    with tracer.start_as_current_span("evaluation.judge") as judge_span:
        judge_span.set_attribute("pipeline_id", req.pipeline_name)

        with tracer.start_as_current_span("evaluation.faithfulness") as f_span:
            faithfulness = random.uniform(0.6, 1.0)
            f_span.set_attribute("score", faithfulness)

        with tracer.start_as_current_span("evaluation.answer_relevance") as ar_span:
            answer_relevance = random.uniform(0.5, 0.95)
            ar_span.set_attribute("score", answer_relevance)

        with tracer.start_as_current_span("evaluation.context_precision") as cp_span:
            context_precision = random.uniform(0.7, 1.0)
            cp_span.set_attribute("score", context_precision)

        with tracer.start_as_current_span("evaluation.context_recall") as cr_span:
            context_recall = random.uniform(0.4, 0.9)
            cr_span.set_attribute("score", context_recall)

        overall_score = random.uniform(0.6, 0.95)
        judge_span.set_attribute("overall_score", overall_score)

        eval_dict = {
            "id": str(uuid.uuid4()),
            "run_id": str(uuid.uuid4()),
            "pipeline_name": req.pipeline_name,
            "query": req.query,
            "faithfulness": faithfulness,
            "answer_relevance": answer_relevance,
            "context_precision": context_precision,
            "context_recall": context_recall,
            "overall_score": overall_score,
            "evaluated_at": datetime.utcnow().isoformat() + "Z",
            "retrieved_chunks": ["Paris is the capital of France."],
            "generated_answer": "The capital of France is Paris.",
        }

        # Update gauges
        eval_faithfulness.labels(pipeline_id=req.pipeline_name).set(faithfulness)
        eval_overall.labels(pipeline_id=req.pipeline_name).set(overall_score)

        r = aioredis.from_url(
            settings.redis_url,
            decode_responses=True,
        )

        await r.publish("evaluations:new", json.dumps(eval_dict))
        await r.aclose()

        return {"status": "simulated", "eval": eval_dict}


@router.get(
    "",
    summary="List all evaluation runs",
    description=(
        "Fetches a paginated list of historical evaluation records from the database, "
        "sorted chronologically descending. Useful for historical reporting and trend analysis."
    ),
    response_description="A JSON array of evaluation records."
)
async def list_evaluations(limit: int = 50, offset: int = 0) -> Any:  # noqa: ANN401
    from backend.db.pool import get_pool

    pool = get_pool()
    async with pool.acquire() as conn:
        records = await conn.fetch(
            "SELECT * FROM evaluations ORDER BY evaluated_at DESC LIMIT $1 OFFSET $2", limit, offset
        )
        return [dict(r) for r in records]


@router.get(
    "/{run_id}",
    summary="Get evaluation by Run ID",
    description=(
        "Fetches the explicit evaluation metrics for a specific pipeline `run_id`. "
        "**Errors**: Returns 404 if the evaluation does not exist or has not completed yet."
    ),
    response_description="A JSON object containing the evaluation metrics for the run."
)
async def get_evaluation(run_id: uuid.UUID) -> Any:  # noqa: ANN401
    from fastapi import HTTPException

    from backend.db.pool import get_pool

    pool = get_pool()
    async with pool.acquire() as conn:
        record = await conn.fetchrow("SELECT * FROM evaluations WHERE run_id = $1", run_id)
        if not record:
            raise HTTPException(status_code=404, detail="Evaluation not found")

        eval_dict = dict(record)
        # Assuming status logic for the polling mechanism in the test:
        eval_dict["status"] = "complete"
        return eval_dict


async def process_evaluation_queue() -> Any:  # noqa: ANN401
    """Consume real pipeline-run evaluation jobs from Redis and score them with the
    genuine LLM-as-judge (evaluation/judge.py::EvaluationJudge).

    NOTE: this previously generated faithfulness/relevance/precision/recall/overall
    scores with random.uniform() instead of calling the judge, so every dashboard
    metric and anomaly-detection trigger driven by this queue was fabricated. That
    has been fixed: EvaluationJudge.evaluate_run() does the real per-metric LLM
    evaluation and persists it; this function only reads those real values back to
    publish them for the SSE dashboard and to run anomaly detection.
    """
    from backend.db.pool import get_pool
    from evaluation.judge import EvaluationJudge

    r = aioredis.from_url(
        settings.redis_url,
        decode_responses=True,
    )

    while True:
        try:
            item = await r.blpop("evaluation_queue", timeout=5)
            if not item:
                continue

            _, payload_str = item
            try:
                # Support old format (just string run_id) or new format (JSON dict)
                payload = json.loads(payload_str)
                run_id = payload["run_id"]
                pipeline_id = payload.get("pipeline_id", "unknown")
                query = payload.get("query", "unknown")
                trace_context = payload.get("trace_context", {})
            except json.JSONDecodeError:
                run_id = payload_str
                pipeline_id = "unknown"
                query = "unknown"
                trace_context = {}

            # Extract parent trace context
            context = extract(trace_context)

            with tracer.start_as_current_span("evaluation.judge", context=context) as judge_span:
                judge_span.set_attribute("pipeline_id", pipeline_id)
                judge_span.set_attribute("run_id", run_id)

                try:
                    pool = get_pool()
                except Exception as e:
                    logger.error(f"DB pool unavailable; cannot evaluate run {run_id}: {e}")
                    continue

                judge = EvaluationJudge(pool, r)
                try:
                    judged_score = await judge.evaluate_run(run_id)
                except Exception as e:
                    logger.error(f"Real evaluation failed for run {run_id}: {e}")
                    continue

                if judged_score is None:
                    logger.info(f"Run {run_id} not found; nothing to evaluate.")
                    continue

                # judge.evaluate_run() already persisted the real per-metric scores
                # to the evaluations table - read them back rather than recomputing,
                # so what we publish is exactly what was measured and stored.
                async with pool.acquire() as conn:
                    eval_row = await conn.fetchrow(
                        """
                        SELECT faithfulness, answer_relevance, context_precision,
                               context_recall, overall_score
                        FROM evaluations WHERE run_id = $1
                        ORDER BY evaluated_at DESC LIMIT 1
                        """,
                        uuid.UUID(run_id),
                    )

                if not eval_row:
                    logger.error(f"No evaluations row found for run {run_id} after judging.")
                    continue

                faithfulness = float(eval_row["faithfulness"])
                answer_relevance = float(eval_row["answer_relevance"])
                context_precision = float(eval_row["context_precision"])
                context_recall = float(eval_row["context_recall"])
                overall_score = float(eval_row["overall_score"])

                judge_span.set_attribute("faithfulness", faithfulness)
                judge_span.set_attribute("answer_relevance", answer_relevance)
                judge_span.set_attribute("context_precision", context_precision)
                judge_span.set_attribute("context_recall", context_recall)
                judge_span.set_attribute("overall_score", overall_score)

                eval_dict = {
                    "id": str(uuid.uuid4()),
                    "run_id": run_id,
                    "pipeline_name": pipeline_id,
                    "query": query,
                    "faithfulness": faithfulness,
                    "answer_relevance": answer_relevance,
                    "context_precision": context_precision,
                    "context_recall": context_recall,
                    "overall_score": overall_score,
                    "evaluated_at": datetime.utcnow().isoformat() + "Z",
                    "retrieved_chunks": [],
                    "generated_answer": "",
                }

                eval_faithfulness.labels(pipeline_id=pipeline_id).set(faithfulness)
                eval_overall.labels(pipeline_id=pipeline_id).set(overall_score)

                await r.publish("evaluations:new", json.dumps(eval_dict))

                # Check for anomalies against the real rolling stats (the evaluation
                # row itself was already inserted by EvaluationJudge.evaluate_run above).
                if pipeline_id != "unknown":
                    try:
                        async with pool.acquire() as conn:
                            # Get rolling mean and stddev
                            stats = await conn.fetchrow(
                                """
                                SELECT 
                                  AVG(e.overall_score) as mean_score, 
                                  STDDEV(e.overall_score) as stddev_score
                                FROM evaluations e
                                JOIN pipeline_runs pr ON e.run_id = pr.id
                                WHERE pr.pipeline_id = $1 
                                AND e.evaluated_at >= NOW() - INTERVAL '7 days'
                                """,
                                uuid.UUID(pipeline_id),
                            )

                            if (
                                stats
                                and stats["mean_score"] is not None
                                and stats["stddev_score"] is not None
                            ):
                                mean_score = float(stats["mean_score"])
                                stddev_score = float(stats["stddev_score"])

                                # 3. Trigger anomaly detection
                                if overall_score < (mean_score - 2 * stddev_score):
                                    import httpx

                                    async with httpx.AsyncClient() as client:
                                        # Use HTTP POST as requested (point to api service for docker network, fallback to localhost)  # noqa: E501
                                        api_host = (
                                            "api"
                                            if settings.postgres_host == "postgres"
                                            else "localhost"
                                        )
                                        url = f"http://{api_host}:8000/pipelines/{pipeline_id}/suggestions"
                                        resp = await client.post(url)
                                        suggestions_data = resp.json()
                                        suggestions = suggestions_data.get("suggestions", [])

                                    # 4. Insert anomaly
                                    await conn.execute(
                                        """
                                        INSERT INTO pipeline_anomalies (pipeline_id, run_id, score, rolling_mean, rolling_stddev, suggestions)
                                        VALUES ($1, $2, $3, $4, $5, $6::jsonb)
                                        """,  # noqa: E501
                                        uuid.UUID(pipeline_id),
                                        uuid.UUID(run_id),
                                        overall_score,
                                        mean_score,
                                        stddev_score,
                                        json.dumps(suggestions),
                                    )

                    except Exception as db_err:
                        logger.info(f"Error checking anomalies: {db_err}")

        except asyncio.CancelledError:
            break
        except Exception as e:
            if "Timeout reading" in str(e) or "TimeoutError" in type(e).__name__:
                continue
            logger.info(f"Error processing evaluation queue: {e}")
            await asyncio.sleep(1)

    await r.aclose()
