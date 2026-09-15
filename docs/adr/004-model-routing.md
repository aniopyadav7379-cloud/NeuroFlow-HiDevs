# ADR 004: Model Routing Matrix

**Context**  
NeuroFlow processes a diverse set of queries. Some are simple fact-retrieval questions, while others require complex reasoning across multiple conflicting contexts. Using a top-tier LLM for all queries is cost-prohibitive, while using a smaller model universally hurts quality on complex tasks.

**Decision**  
We will implement a **dynamic Model Router** in the Generation Subsystem that dispatches queries to different LLM tiers based on an initial complexity classification.

**Consequences**  

**Routing Matrix:**
- **Tier 1 (Fast & Cheap):** e.g., Llama-3-8B / GPT-4o-mini
  - *Win Condition:* Simple factual lookups, low-latency requirements, high-volume generic queries.
  - *Trigger:* Classifier detects direct question + high confidence retrieval scores.
- **Tier 2 (Balanced):** e.g., fine-tuned domain specific models
  - *Win Condition:* Domain-specific tasks where the base model lacks vocabulary but reasoning is moderate.
  - *Trigger:* Topic matches fine-tuned domain + moderate complexity.
- **Tier 3 (Heavy Reasoning):** e.g., GPT-4o / Claude 3.5 Sonnet
  - *Win Condition:* Multi-hop reasoning, conflicting context resolution, coding tasks.
  - *Trigger:* Classifier detects complex reasoning requirement OR Tier 1 model outputs a low-confidence response (fallback).

- **Pros:** Optimizes the cost/performance frontier.
- **Cons:** Adds latency to the pipeline due to the initial classification step. The classifier itself must be highly optimized and fast.
