import asyncio
from typing import Any
from unittest.mock import AsyncMock

from backend.providers.base import ChatMessage
from backend.providers.client import NeuroFlowClient
from backend.providers.router import RoutingCriteria


async def main() -> Any:  # noqa: ANN401
    print("Testing Provider Capabilities...")

    # Normally we'd use a real redis client if it's running
    mock_redis = AsyncMock()
    mock_redis.get.return_value = None
    client = NeuroFlowClient(redis_client=mock_redis)

    # Test 1: Embeddings
    print("\n--- Testing embed(['hello world']) ---")
    try:
        embeddings = await client.embed(["hello world"])
        print(f"Generated {len(embeddings)} embedding(s).")
        if embeddings:
            print(f"Embedding length: {len(embeddings[0])}, preview: {embeddings[0][:5]}...")
    except Exception as e:
        print(f"Embedding error: {e}")

    # Test 2: Streaming
    print("\n--- Testing stream('Say one word') ---")
    messages = [ChatMessage(role="user", content="Say one word")]
    criteria = RoutingCriteria(task_type="rag_generation")

    try:
        # Loop through stream generator
        async for token in await client.stream_chat(messages, criteria):
            print(token, end="", flush=True)
        print("\n")
    except Exception as e:
        print(f"Stream error: {e}")


if __name__ == "__main__":
    asyncio.run(main())
