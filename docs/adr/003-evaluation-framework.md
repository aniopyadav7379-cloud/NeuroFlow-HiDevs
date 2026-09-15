# ADR 003: Automated Evaluation Framework

**Context**  
To continuously improve the RAG system and generate fine-tuning data, we need to evaluate every generation. Relying solely on human annotation is unscalable, expensive, and slow, preventing rapid iteration and dataset generation.

**Decision**  
We will implement an automated **LLM-as-a-judge** evaluation framework that scores generations asynchronously on Faithfulness, Answer Relevance, Context Precision, and Context Recall using an advanced reasoning model (e.g., GPT-4 or Claude 3 Opus).

**Consequences**  
- **Pros:**
  - Scales to 100% of queries, providing massive datasets for fine-tuning.
  - Immediate feedback loop on system health and prompt changes.
- **Cons (Failure Modes):**
  - **Bias:** The judge model may have biases (e.g., preference for longer answers).
  - **Hallucinated Scores:** The judge might incorrectly penalize a valid answer if the context is highly technical and misunderstood by the judge.
- **Mitigation:** We will implement a random sampling of 1% of evaluations to be reviewed by human annotators. If the human-annotator and LLM-judge correlation drops below 0.85 (Pearson), we will pause fine-tuning extraction, adjust the judge prompts, and explicitly define criteria for the edge cases.
