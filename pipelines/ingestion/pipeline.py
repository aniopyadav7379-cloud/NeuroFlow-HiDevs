import json
import logging
import os
from typing import Any

import asyncpg
import docker
from opentelemetry import trace

from backend.monitoring.metrics import ingestion_docs_total
from backend.providers.client import NeuroFlowClient
from backend.security.prompt_injection import scan_for_prompt_injection
from backend.security.secrets_scanner import scan_and_redact_secrets

from .chunker import Chunker
from .extractors import (
    ExtractedPage,
    extract_image,
    extract_pptx,
    extract_url,
)

tracer = trace.get_tracer(__name__)
logger = logging.getLogger(__name__)


async def process_document_pipeline(
    db_pool: asyncpg.Pool,
    client: NeuroFlowClient,
    document_id: str,
    file_path: str,
    source_type: str,
) -> Any:  # noqa: ANN401
    with tracer.start_as_current_span("ingestion.process") as span:
        span.set_attribute("document_id", document_id)
        span.set_attribute("source_type", source_type)

        try:
            # 1. Extraction
            with tracer.start_as_current_span(f"ingestion.extract.{source_type}") as extract_span:
                # Local documents go to the sandbox to prevent malicious execution
                if source_type in ["pdf", "docx", "csv", "text", "txt"]:
                    try:
                        docker_client = docker.from_env()

                        output_path = f"{file_path}_output.json"

                        # In docker-compose.yml we explicitly map the volume name neuroflow_uploads_data to /app/uploads  # noqa: E501
                        try:
                            docker_client.containers.run(
                                image="neuroflow-backend:latest",
                                command=[
                                    "python",
                                    "-m",
                                    "pipelines.ingestion.sandbox_extractor",
                                    file_path,
                                    source_type,
                                    output_path,
                                ],
                                network_mode="none",
                                mem_limit="256m",
                                volumes={
                                    "neuroflow_uploads_data": {"bind": "/app/uploads", "mode": "rw"}
                                },
                                remove=True,
                                stdout=True,
                                stderr=True,
                            )
                        except Exception as docker_e:
                            # The sandbox container might have failed to run entirely or exited 1
                            logger.error(f"Sandbox container error: {docker_e}")

                        # Read output
                        if not os.path.exists(output_path):  # noqa: ASYNC240
                            raise Exception(
                                "Sandbox failed to produce an output file. It may have crashed."
                            )

                        with open(output_path, encoding="utf-8") as f:  # noqa: ASYNC230
                            output_data = json.load(f)

                        os.remove(output_path)

                        if isinstance(output_data, dict) and "error" in output_data:
                            raise Exception(f"Sandbox extraction error: {output_data['error']}")

                        pages = [ExtractedPage(**p) for p in output_data]
                    except Exception as e:
                        logger.error(f"Sandbox extraction failed for {document_id}: {e}")
                        raise e
                # Network dependent extractions happen natively (but carefully)
                elif source_type in ["image", "jpeg", "png", "webp", "jpg"]:
                    pages = await extract_image(file_path, client)
                elif source_type == "url":
                    pages = await extract_url(file_path)
                elif source_type == "pptx":
                    pages = await extract_pptx(file_path, client)
                else:
                    raise Exception(f"Unsupported source type: {source_type}")

                extract_span.set_attribute("page_count", len(pages))
                span.set_attribute("page_count", len(pages))

            # 2. Chunking
            with tracer.start_as_current_span("ingestion.chunk") as chunk_span:
                chunker = Chunker(client=client)
                chunks = await chunker.chunk_document(pages, source_type)
                chunk_span.set_attribute("chunk_count", len(chunks))
                span.set_attribute("chunk_count", len(chunks))

            # 2.5 Security Scanning
            with tracer.start_as_current_span("ingestion.security_scan"):
                for chunk in chunks:
                    # Secret Detection
                    redacted_text, events = scan_and_redact_secrets(chunk.content, document_id)
                    chunk.content = redacted_text
                    if events:
                        for event in events:
                            logger.info(json.dumps(event))
                        chunk.metadata["secrets_redacted"] = len(events)

                    # Prompt Injection
                    inj_result = scan_for_prompt_injection(chunk.content)
                    if inj_result:
                        logger.warning(
                            f"Prompt injection pattern detected in document {document_id}: {inj_result['pattern']}"  # noqa: E501
                        )
                        chunk.metadata["prompt_injection_detected"] = True
                        chunk.metadata["pattern"] = inj_result["pattern"]

            # 3. Embed chunks
            with tracer.start_as_current_span("ingestion.embed") as embed_span:
                texts = [c.content for c in chunks]
                embeddings = await client.embed(texts) if texts else []
                embed_span.set_attribute("embedding_calls", 1 if embeddings else 0)
                embed_span.set_attribute("model", "default_embedding_model")
                span.set_attribute("embedding_calls", 1 if embeddings else 0)

            # 4. DB Persistence
            with tracer.start_as_current_span("ingestion.write_db") as db_span:
                async with db_pool.acquire() as conn:
                    async with conn.transaction():
                        for chunk, emb in zip(chunks, embeddings):
                            await conn.execute(
                                """
                                INSERT INTO chunks (document_id, content, embedding, chunk_index, token_count, metadata)
                                VALUES ($1, $2, $3, $4, $5, $6)
                                """,  # noqa: E501
                                document_id,
                                chunk.content,
                                json.dumps(emb),
                                chunk.chunk_index,
                                chunk.token_count,
                                json.dumps(chunk.metadata),
                            )

                        # Aggregate metadata
                        doc_metadata = {}
                        for p in pages:
                            doc_metadata.update(p.metadata)

                        # Update document status
                        await conn.execute(
                            "UPDATE documents SET status = 'complete', chunk_count = $1, metadata = $2 WHERE id = $3",  # noqa: E501
                            len(chunks),
                            json.dumps(doc_metadata),
                            document_id,
                        )
                        db_span.set_attribute("chunks_written", len(chunks))

            # Prometheus Metric Update
            ingestion_docs_total.labels(source_type=source_type).inc()

            total_tokens = sum(c.token_count for c in chunks)
            chunk_span.set_attribute("token_count", total_tokens)
            span.set_attribute("token_count", total_tokens)

            logger.info(
                json.dumps(
                    {
                        "event": "ingestion_complete",
                        "document_id": str(document_id),
                        "chunks": len(chunks),
                        "tokens": total_tokens,
                    }
                )
            )

        except Exception as e:
            span.record_exception(e)
            span.set_status(trace.StatusCode.ERROR, str(e))
            async with db_pool.acquire() as conn:
                await conn.execute(
                    "UPDATE documents SET status = 'failed' WHERE id = $1", document_id
                )
            raise e
