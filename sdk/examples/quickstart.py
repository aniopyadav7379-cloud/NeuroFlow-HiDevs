"""NeuroFlow SDK quickstart: ingest a URL, then run a streaming query against it.

Requires a running NeuroFlow deployment (see docs/runbook.md to start one
locally with Docker Compose) plus a real pipeline. Configure via environment
variables:

    NEUROFLOW_URL       Base URL of the API (default: http://localhost:8000)
    NEUROFLOW_API_KEY   Bearer token for your account
    NEUROFLOW_PIPELINE_ID   An existing pipeline's UUID. If unset, this
                            script creates a new pipeline itself via
                            client.create_pipeline() rather than using a
                            hardcoded/fake UUID.

Run:
    NEUROFLOW_API_KEY=... python sdk/examples/quickstart.py
"""

import asyncio
import os

from neuroflow import NeuroFlowClient
from neuroflow.exceptions import (
    IngestionFailedError,
    NeuroFlowAPIError,
    NeuroFlowTimeoutError,
)


async def main() -> None:
    base_url = os.getenv("NEUROFLOW_URL", "http://localhost:8000")
    api_key = os.getenv("NEUROFLOW_API_KEY")
    if not api_key:
        raise SystemExit(
            "Set NEUROFLOW_API_KEY to a real token for your deployment before running this."
        )

    async with NeuroFlowClient(base_url, api_key) as client:
        pipeline_id = os.getenv("NEUROFLOW_PIPELINE_ID")
        if not pipeline_id:
            print("No NEUROFLOW_PIPELINE_ID set - creating a new pipeline for this demo...")
            print("(POST /pipelines requires an API key with 'admin' scope.)")
            # PipelineCreate requires a nested "config" object with all four
            # sub-configs present (backend/models/pipeline.py uses
            # extra="forbid", so no other shape is accepted). ingestion/
            # retrieval/evaluation all have defaults for every field; generation
            # only requires model_routing, whose own fields all have defaults.
            pipeline = await client.create_pipeline(
                {
                    "config": {
                        "name": "quickstart-demo",
                        "description": "Created by sdk/examples/quickstart.py",
                        "ingestion": {},
                        "retrieval": {},
                        "generation": {"model_routing": {}},
                        "evaluation": {},
                    }
                }
            )
            pipeline_id = pipeline["id"]
            print(f"Created pipeline: {pipeline_id}")

        print("\n1. Ingesting a URL...")
        try:
            doc = await client.ingest_url(
                url="https://en.wikipedia.org/wiki/Artificial_intelligence",
                pipeline_id=pipeline_id,
                poll_timeout=300.0,
            )
        except IngestionFailedError as e:
            print(f"Ingestion failed: {e}")
            return
        except NeuroFlowTimeoutError as e:
            print(f"Ingestion did not finish in time: {e}")
            return
        print(f"Document ingested. id={doc.document_id} status={doc.status} "
              f"chunks={doc.chunk_count}")

        print("\n2. Running a streaming query...")
        try:
            # NOTE: query() is an async *function*, not an async generator
            # function - when stream=True it returns an async generator, so
            # it must be awaited first and then iterated. (A previous version
            # of this script did `async for token in client.query(...)`
            # directly, which raises a TypeError - a coroutine is not
            # async-iterable until it's awaited.)
            stream = await client.query(
                query="What is artificial intelligence?",
                pipeline_id=pipeline_id,
                stream=True,
            )
            print("Response: ", end="", flush=True)
            async for token in stream:
                print(token, end="", flush=True)
            print()
        except NeuroFlowAPIError as e:
            print(f"\nQuery failed: {e}")
            return

    print("\nDone!")


if __name__ == "__main__":
    asyncio.run(main())
