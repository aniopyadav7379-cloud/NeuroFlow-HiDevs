import asyncio
import json
import time
from collections.abc import AsyncGenerator
from typing import Any
from uuid import UUID

import tiktoken
from opentelemetry import trace

from backend.monitoring.metrics import generation_latency, llm_cost, lm_calls_total
from backend.providers.base import ChatMessage
from backend.providers.client import NeuroFlowClient
from backend.providers.router import RoutingCriteria
from pipelines.generation.citations import parse_citations
from pipelines.generation.prompt_builder import build_prompt

tracer = trace.get_tracer(__name__)


class StreamingGenerator:
    def __init__(self, client: NeuroFlowClient, db_pool: Any, redis_client: Any) -> None:  # noqa: ANN401
        self.client = client
        self.db_pool = db_pool
        self.redis = redis_client
        self.tokenizer = tiktoken.get_encoding("cl100k_base")

    async def generate_stream(
        self,
        run_id: str,
        pipeline_id: str,
        query: str,
        query_type: str,
        assembled_context: dict[str, Any],
        config: dict[str, Any] | None = None,
    ) -> AsyncGenerator[tuple[str, list[dict[str, Any]]], None]:

        start_time = time.time()

        with tracer.start_as_current_span("generation.pipeline") as pipeline_span:
            pipeline_span.set_attribute("run_id", str(run_id))
            pipeline_span.set_attribute("pipeline_id", pipeline_id)

            prompt = build_prompt(
                query, assembled_context["context_data"], query_type, pipeline_id, run_id
            )

            # Log assembled prompt to DB
            async with self.db_pool.acquire() as conn:
                await conn.execute(
                    """
                    UPDATE pipeline_runs 
                    SET prompt = $1, status = 'running'
                    WHERE id = $2
                    """,
                    prompt,
                    UUID(run_id),
                )

            messages = [ChatMessage(role="user", content=prompt)]

            task_type = "rag_generation"
            max_cost = 0.05
            temperature = 0.2
            if config and "generation" in config:
                gen_conf = config["generation"]
                if "model_routing" in gen_conf:
                    task_type = gen_conf["model_routing"].get("task_type", task_type)
                    max_cost = gen_conf["model_routing"].get("max_cost_per_call", max_cost)
                temperature = gen_conf.get("temperature", temperature)

            criteria = RoutingCriteria(task_type=task_type, max_cost_per_call=max_cost)

            # Override client stream_chat temperature if supported? The provider interface usually relies on kwargs.  # noqa: E501
            # We can pass temperature as kwargs to stream_chat in NeuroFlowClient.
            # Actually our NeuroFlowClient.stream_chat(messages, criteria, **kwargs) handles extra kwargs.  # noqa: E501
            stream_gen = await self.client.stream_chat(messages, criteria, temperature=temperature)

            full_response = []
            is_thinking = False
            buffer = ""
            think_content = ""
            clean_response = []

            with tracer.start_as_current_span("generation.llm_call") as llm_span:
                llm_span.set_attribute("pipeline_id", pipeline_id)
                llm_span.set_attribute("run_id", str(run_id))
                llm_span.set_attribute(
                    "model", task_type
                )  # The router decides, so task_type is our placeholder
                # Stream from LLM
                async for chunk in stream_gen:
                    full_response.append(chunk)
                    buffer += chunk

                    while True:
                        if not is_thinking:
                            if "<think>" in buffer:
                                pre, post = buffer.split("<think>", 1)
                                if pre:
                                    clean_response.append(pre)
                                    yield (pre, [])
                                is_thinking = True
                                buffer = post
                            else:
                                last_lt = buffer.rfind("<")
                                if last_lt != -1 and "<think>".startswith(buffer[last_lt:]):
                                    pre = buffer[:last_lt]
                                    buffer = buffer[last_lt:]
                                    if pre:
                                        clean_response.append(pre)
                                        yield (pre, [])
                                    break
                                else:
                                    pre = buffer
                                    buffer = ""
                                    if pre:
                                        clean_response.append(pre)
                                        yield (pre, [])
                                    break
                        else:
                            if "</think>" in buffer:
                                pre, post = buffer.split("</think>", 1)
                                think_content += pre
                                is_thinking = False
                                buffer = post
                            else:
                                last_lt = buffer.rfind("<")
                                if last_lt != -1 and "</think>".startswith(buffer[last_lt:]):
                                    pre = buffer[:last_lt]
                                    buffer = buffer[last_lt:]
                                    think_content += pre
                                    break
                                else:
                                    think_content += buffer
                                    buffer = ""
                                    break

                # Assume NeuroFlowClient tracks provider/model somewhere or we use generic. We'll use criteria task_type  # noqa: E501
                lm_calls_total.labels(provider="routed", model="routed", task_type=task_type).inc()

            duration = time.time() - start_time
            generation_latency.labels(model="routed").observe(duration)

            latency_ms = int(duration * 1000)
            final_text = "".join(full_response)
            clean_text = "".join(clean_response)

            input_tokens = len(self.tokenizer.encode(prompt))
            output_tokens = len(self.tokenizer.encode(final_text))

            # Approximate cost tracking based on standard GPT-3.5 turbo rates ($0.0015/1K in, $0.002/1K out)  # noqa: E501
            approx_cost = (input_tokens / 1000 * 0.0015) + (output_tokens / 1000 * 0.002)
            llm_cost.labels(model=task_type).observe(approx_cost)

            pipeline_span.set_attribute("input_tokens", input_tokens)
            pipeline_span.set_attribute("output_tokens", output_tokens)

            # Parse citations from clean text
            citations = parse_citations(clean_text, assembled_context, pipeline_id, run_id)

            metadata_json = json.dumps({"think_content": think_content}) if think_content else "{}"

            with tracer.start_as_current_span("generation.log_run") as log_span:
                log_span.set_attribute("pipeline_id", pipeline_id)
                log_span.set_attribute("run_id", str(run_id))
                # Log to DB
                async with self.db_pool.acquire() as conn:
                    await conn.execute(
                        """
                        UPDATE pipeline_runs 
                        SET generation = $1, input_tokens = $2, output_tokens = $3, latency_ms = $4, status = 'complete', metadata = $5
                        WHERE id = $6
                        """,  # noqa: E501
                        clean_text,
                        input_tokens,
                        output_tokens,
                        latency_ms,
                        metadata_json,
                        UUID(run_id),
                    )

            # Enqueue evaluation job (Task 37) asynchronously
            from opentelemetry.propagate import inject

            carrier: dict[str, str] = {}
            inject(carrier)
            payload = json.dumps(
                {
                    "run_id": str(run_id),
                    "pipeline_id": pipeline_id,
                    "query": query,
                    "trace_context": carrier,
                }
            )
            asyncio.create_task(self.redis.rpush("evaluation_queue", payload))

            # Final yield to send citations
            yield ("", citations)
