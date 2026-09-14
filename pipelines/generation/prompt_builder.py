from opentelemetry import trace

tracer = trace.get_tracer(__name__)


def build_prompt(
    query: str,
    assembled_context: str,
    query_type: str = "factual",
    pipeline_id: str | None = None,
    run_id: str | None = None,
) -> str:
    with tracer.start_as_current_span("generation.prompt_build") as span:
        if pipeline_id:
            span.set_attribute("pipeline_id", pipeline_id)
        if run_id:
            span.set_attribute("run_id", run_id)
        base_prompt = (
            "You are a precise research assistant. Answer the user's question using ONLY the provided context.\n"  # noqa: E501
            "If the context does not contain enough information to answer fully, say so explicitly.\n"  # noqa: E501
            "For every factual claim, include a citation in the format [Source N].\n"
            "Do not introduce information not present in the context."
        )

        query_type_additions = {
            "factual": "Provide a direct, concise answer. If multiple sources agree, cite all of them.",  # noqa: E501
            "analytical": "Before answering, think step by step inside <think>...</think> tags. Then analyze and synthesize across the provided sources. Identify agreements and contradictions.",  # noqa: E501
            "comparative": "Before answering, think step by step inside <think>...</think> tags. Then organize your response as a structured comparison. Use a table if appropriate.",  # noqa: E501
            "procedural": "Provide numbered steps. Each step must be cited.",
        }

        addition = query_type_additions.get(query_type, query_type_additions["factual"])

        system_instruction = f"{base_prompt}\n\n{addition}"

        final_prompt = (
            f"{system_instruction}\n\n"
            f"<context>\n{assembled_context}\n</context>\n\n"
            f"Question: {query}"
        )

        return final_prompt
