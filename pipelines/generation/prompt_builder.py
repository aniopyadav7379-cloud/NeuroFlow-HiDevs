"""
Prompt assembly: builds the system + user messages sent to the generation
model, from the query type classified in Task 35's QueryProcessor and the
context string assembled by Task 35's context_assembler.
"""
from backend.providers.base import ChatMessage

BASE_SYSTEM_PROMPT = (
    "You are a precise research assistant. Answer the user's question using ONLY the provided context.\n"
    "If the context does not contain enough information to answer fully, say so explicitly.\n"
    "For every factual claim, include a citation in the format [Source N].\n"
    "Do not introduce information not present in the context."
)

QUERY_TYPE_ADDITIONS = {
    "factual": "Provide a direct, concise answer. If multiple sources agree, cite all of them.",
    "analytical": "Analyze and synthesize across the provided sources. Identify agreements and contradictions.",
    "comparative": "Organize your response as a structured comparison. Use a table if appropriate.",
    "procedural": "Provide numbered steps. Each step must be cited.",
}

# Chain-of-thought (stretch goal) only applies to query types where a
# hidden reasoning pass plausibly earns its cost — a one-line factual
# lookup doesn't need it.
CHAIN_OF_THOUGHT_QUERY_TYPES = {"analytical", "comparative"}

_COT_INSTRUCTION = (
    "\n\nBefore answering, think through the problem step by step inside "
    "<think></think> tags — lay out what each source says, how they relate, "
    "and how you'll structure the answer. After the closing </think> tag, "
    "write your final answer for the user. The text inside <think></think> "
    "will never be shown to the user, so it does not need citations, but "
    "your final answer after </think> still must follow all the citation "
    "rules above."
)

# A pipeline's generation.system_prompt_variant config selects one of
# these — "balanced" (the default, no addition) matches the base prompt
# exactly as specified; "precise" and "creative" are additive style knobs
# a pipeline config can opt into without touching code.
PROMPT_VARIANT_ADDITIONS = {
    "balanced": "",
    "precise": (
        "\n\nBe terse. Prefer short sentences and avoid hedging language where the "
        "context supports a direct answer."
    ),
    "creative": (
        "\n\nYou may use a more conversational tone and illustrative phrasing, as long "
        "as every factual claim still traces back to the context and is cited."
    ),
}


def build_system_prompt(
    query_type: str, use_chain_of_thought: bool = False, prompt_variant: str = "balanced"
) -> str:
    addition = QUERY_TYPE_ADDITIONS.get(query_type, "")
    prompt = f"{BASE_SYSTEM_PROMPT}\n\n{addition}" if addition else BASE_SYSTEM_PROMPT
    prompt += PROMPT_VARIANT_ADDITIONS.get(prompt_variant, "")
    if use_chain_of_thought:
        prompt += _COT_INSTRUCTION
    return prompt


def build_messages(
    query: str,
    query_type: str,
    context: str,
    use_chain_of_thought: bool = False,
    prompt_variant: str = "balanced",
) -> list[ChatMessage]:
    system_prompt = build_system_prompt(query_type, use_chain_of_thought, prompt_variant)
    user_content = f"<context>\n{context}\n</context>\n\n{query}"
    return [
        ChatMessage(role="system", content=system_prompt),
        ChatMessage(role="user", content=user_content),
    ]
