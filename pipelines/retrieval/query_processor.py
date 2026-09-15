# ruff: noqa: E501
import json
from typing import Any

from pydantic import BaseModel

from backend.providers.base import ChatMessage
from backend.providers.client import NeuroFlowClient
from backend.providers.router import RoutingCriteria


class ProcessedQuery(BaseModel):
    original_query: str
    expanded_queries: list[str]
    metadata_filters: dict[str, Any]
    query_type: str
    hypothetical_document: str | None = None


class QueryProcessor:
    def __init__(self, client: NeuroFlowClient) -> None:
        self.client = client

    async def process_query(self, query: str, prompt_variant: str = "B") -> ProcessedQuery:
        if prompt_variant == "A":
            system_prompt = """
You are an expert search query processing engine. Analyze the user's query and output a JSON 
object with the following fields:
1. "expanded_queries": A list of 2-3 alternative phrasings or expansions of the query to 
improve search recall. Use different vocabulary but keep the same semantic meaning.
2. "metadata_filters": A JSON object containing any explicit or implicit filters mentioned in 
the query (e.g., {"year": 2023, "topic": "climate"}). If none, output an empty object {}.
3. "query_type": Classify the query into exactly one of: "factual", "analytical", 
"comparative", or "procedural".
4. "hypothetical_document": A detailed hypothetical passage or paragraph that directly answers 
the user's query. Write it in the tone and style of the documents that might contain the answer.

Output ONLY valid JSON. Do not include markdown formatting, explanations, or any other text. 
Ensure the JSON is perfectly well-formed.
"""
        else:
            system_prompt = """Analyze the query and output JSON:
1. "expanded_queries": 2-3 alternative phrasings for search recall.
2. "metadata_filters": JSON filters (e.g., {"year": 2023}) or {}.
3. "query_type": "factual", "analytical", "comparative", or "procedural".
4. "hypothetical_document": A detailed hypothetical passage answering the query.

Examples per query type:
[factual]
User: "What is the capital of France?"
{"expanded_queries": ["French capital city", "capital of France location"], "metadata_filters": {}, "query_type": "factual", "hypothetical_document": "Paris is the capital of France."}  # noqa: E501

[analytical]
User: "Why did housing prices increase in 2021?"
{"expanded_queries": ["causes of 2021 housing market surge", "reasons for real estate jump"], "metadata_filters": {"year": 2021}, "query_type": "analytical", "hypothetical_document": "Surged due to low rates."}  # noqa: E501

[comparative]
User: "How does A compare to B?"
{"expanded_queries": ["difference A and B", "A vs B performance"], "metadata_filters": {}, "query_type": "comparative", "hypothetical_document": "A is faster, whereas B is memory efficient."}  # noqa: E501

[procedural]
User: "How do I reset my password?"
{"expanded_queries": ["steps to change password", "password recovery"], "metadata_filters": {}, "query_type": "procedural", "hypothetical_document": "Click Forgot Password and follow the link."}  # noqa: E501
"""

        messages = [
            ChatMessage(role="system", content=system_prompt),
            ChatMessage(role="user", content=query),
        ]

        criteria = RoutingCriteria(task_type="rag_generation")

        try:
            # Use JSON mode if supported by the provider
            result = await self.client.chat(
                messages, criteria, response_format={"type": "json_object"}
            )

            # Extract JSON string (handling potential markdown blocks just in case)
            content = result.content.strip()
            if content.startswith("```json"):
                content = content[7:-3].strip()
            elif content.startswith("```"):
                content = content[3:-3].strip()

            parsed = json.loads(content)

            return ProcessedQuery(
                original_query=query,
                expanded_queries=parsed.get("expanded_queries", []),
                metadata_filters=parsed.get("metadata_filters", {}),
                query_type=parsed.get("query_type", "factual"),
                hypothetical_document=parsed.get("hypothetical_document"),
            )
        except Exception:
            # Fallback on failure
            return ProcessedQuery(
                original_query=query,
                expanded_queries=[],
                metadata_filters={},
                query_type="factual",
                hypothetical_document=None,
            )
