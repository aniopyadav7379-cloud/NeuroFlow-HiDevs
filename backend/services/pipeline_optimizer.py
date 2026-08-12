"""
Rule-based pipeline optimizer (stretch goal): looks at a pipeline's
recent aggregate evaluation scores and its current config, and suggests
concrete config changes. Deliberately simple, explainable if-then rules —
not a learned model — so every suggestion comes with a reason a human can
sanity-check, which matters more here than squeezing out marginal gains a
black-box tuner might find.
"""
from dataclasses import dataclass

# Below this average score on a metric, the optimizer considers it a
# problem worth suggesting a fix for.
LOW_SCORE_THRESHOLD = 0.7
MIN_EVALUATIONS_FOR_SUGGESTIONS = 5


@dataclass
class Suggestion:
    metric: str
    current_value: float | None
    config_path: str
    current_config_value: object
    suggested_config_value: object
    reason: str


def _get_nested(config: dict, path: str):
    node = config
    for key in path.split("."):
        node = node.get(key, {}) if isinstance(node, dict) else None
    return node


def suggest_improvements(config: dict, aggregate_scores: dict) -> list[Suggestion]:
    """`config` is a pipeline's stored config dict (ingestion/retrieval/
    generation/evaluation sections). `aggregate_scores` matches the shape
    GET /pipelines/{id}/analytics returns under "evaluation_scores"
    (avg_faithfulness, avg_answer_relevance, avg_context_precision,
    avg_context_recall, avg_overall_score), plus "n_evaluations"."""
    suggestions: list[Suggestion] = []

    n_evaluations = aggregate_scores.get("n_evaluations") or 0
    if n_evaluations < MIN_EVALUATIONS_FOR_SUGGESTIONS:
        return suggestions  # not enough data to suggest anything responsibly

    retrieval = config.get("retrieval", {})

    context_precision = aggregate_scores.get("avg_context_precision")
    if context_precision is not None and context_precision < LOW_SCORE_THRESHOLD:
        top_k = retrieval.get("top_k_after_rerank", 8)
        if top_k > 3:
            suggestions.append(
                Suggestion(
                    metric="context_precision",
                    current_value=context_precision,
                    config_path="retrieval.top_k_after_rerank",
                    current_config_value=top_k,
                    suggested_config_value=max(3, top_k - 2),
                    reason=(
                        f"context_precision is low ({context_precision:.2f}), meaning many retrieved "
                        f"chunks aren't actually useful. Reducing top_k_after_rerank from {top_k} to "
                        f"{max(3, top_k - 2)} keeps only the most relevant chunks after reranking."
                    ),
                )
            )

    context_recall = aggregate_scores.get("avg_context_recall")
    if context_recall is not None and context_recall < LOW_SCORE_THRESHOLD:
        dense_k = retrieval.get("dense_k", 20)
        suggestions.append(
            Suggestion(
                metric="context_recall",
                current_value=context_recall,
                config_path="retrieval.dense_k",
                current_config_value=dense_k,
                suggested_config_value=min(200, dense_k + 10),
                reason=(
                    f"context_recall is low ({context_recall:.2f}), meaning relevant information often "
                    f"isn't being retrieved at all. Increasing dense_k from {dense_k} to "
                    f"{min(200, dense_k + 10)} casts a wider net before fusion/reranking narrows it down."
                ),
            )
        )
        if not retrieval.get("query_expansion", True):
            suggestions.append(
                Suggestion(
                    metric="context_recall",
                    current_value=context_recall,
                    config_path="retrieval.query_expansion",
                    current_config_value=False,
                    suggested_config_value=True,
                    reason=(
                        f"context_recall is low ({context_recall:.2f}) and query_expansion is disabled — "
                        "enabling it retrieves for alternative phrasings too, which often surfaces "
                        "relevant chunks a single literal query misses."
                    ),
                )
            )

    faithfulness = aggregate_scores.get("avg_faithfulness")
    if faithfulness is not None and faithfulness < LOW_SCORE_THRESHOLD:
        temperature = _get_nested(config, "generation.temperature")
        if temperature is not None and temperature > 0.3:
            suggestions.append(
                Suggestion(
                    metric="faithfulness",
                    current_value=faithfulness,
                    config_path="generation.temperature",
                    current_config_value=temperature,
                    suggested_config_value=0.2,
                    reason=(
                        f"faithfulness is low ({faithfulness:.2f}) — a lower temperature "
                        f"(currently {temperature}) makes generation stick closer to the provided "
                        "context instead of embellishing, which tends to reduce unsupported claims."
                    ),
                )
            )
        max_context_tokens = _get_nested(config, "generation.max_context_tokens")
        top_k_after_rerank = retrieval.get("top_k_after_rerank", 8)
        if max_context_tokens and top_k_after_rerank and max_context_tokens < top_k_after_rerank * 300:
            suggestions.append(
                Suggestion(
                    metric="faithfulness",
                    current_value=faithfulness,
                    config_path="generation.max_context_tokens",
                    current_config_value=max_context_tokens,
                    suggested_config_value=top_k_after_rerank * 400,
                    reason=(
                        f"faithfulness is low ({faithfulness:.2f}) and max_context_tokens "
                        f"({max_context_tokens}) may be too tight for top_k_after_rerank "
                        f"({top_k_after_rerank}) chunks, causing chunks to be truncated or dropped — "
                        f"raising it to {top_k_after_rerank * 400} gives each chunk more room."
                    ),
                )
            )

    answer_relevance = aggregate_scores.get("avg_answer_relevance")
    if answer_relevance is not None and answer_relevance < LOW_SCORE_THRESHOLD:
        if not retrieval.get("query_expansion", True):
            suggestions.append(
                Suggestion(
                    metric="answer_relevance",
                    current_value=answer_relevance,
                    config_path="retrieval.query_expansion",
                    current_config_value=False,
                    suggested_config_value=True,
                    reason=(
                        f"answer_relevance is low ({answer_relevance:.2f}) — enabling query_expansion "
                        "can help retrieval (and therefore the generated answer) better match the "
                        "actual intent behind oddly-phrased queries."
                    ),
                )
            )
        reranker = retrieval.get("reranker", "cross-encoder")
        if reranker == "none":
            suggestions.append(
                Suggestion(
                    metric="answer_relevance",
                    current_value=answer_relevance,
                    config_path="retrieval.reranker",
                    current_config_value="none",
                    suggested_config_value="cross-encoder",
                    reason=(
                        f"answer_relevance is low ({answer_relevance:.2f}) and reranking is disabled — "
                        "a cross-encoder rerank pass tends to surface the chunks that actually answer "
                        "the query, not just the ones lexically/semantically closest to it."
                    ),
                )
            )

    return suggestions
