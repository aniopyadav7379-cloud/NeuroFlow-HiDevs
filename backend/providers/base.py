"""
Provider-agnostic interface every LLM backend implements.

NeuroFlow's Generation Subsystem (docs/architecture.md §3) and Evaluation
Subsystem (§4) only ever talk to a `BaseLLMProvider` — never to an
`openai`/`anthropic` client directly. That's the whole point of this
module: swapping or adding a provider means implementing this interface,
not touching the router, the client wrapper, or anything downstream.
"""
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import AsyncGenerator


@dataclass
class ChatMessage:
    role: str  # "system" | "user" | "assistant"
    content: str | list  # str for text, list for multi-modal content parts


@dataclass
class GenerationResult:
    content: str
    model: str
    input_tokens: int
    output_tokens: int
    latency_ms: float
    cost_usd: float
    finish_reason: str


class ProviderError(Exception):
    """Base class for provider-level failures."""


class RetryableProviderError(ProviderError):
    """Rate limits, transient 5xx, timeouts — safe to retry / fail over."""


class NonRetryableProviderError(ProviderError):
    """Bad request, auth failure, content policy — retrying won't help."""


class BaseLLMProvider(ABC):
    """Every provider implementation must be fully stateless with respect
    to conversation history — callers pass the full `messages` list on
    every call. Providers only hold their own client + pricing config."""

    #: Short, stable identifier used in routing config, Redis metrics keys,
    #: and OTel span attributes (e.g. "openai", "anthropic").
    provider_name: str = "base"

    @abstractmethod
    async def complete(self, messages: list[ChatMessage], **kwargs) -> GenerationResult:
        """kwargs commonly include: model (str, defaults to the provider's
        configured default), temperature, max_tokens."""
        ...

    @abstractmethod
    async def stream(self, messages: list[ChatMessage], **kwargs) -> AsyncGenerator[str, None]:
        """Same kwargs as complete(); yields text deltas as they arrive."""
        ...

    @abstractmethod
    async def embed(self, texts: list[str], **kwargs) -> list[list[float]]:
        """kwargs commonly include: model (str, defaults to the provider's
        configured default embedding model)."""
        ...

    @property
    @abstractmethod
    def cost_per_input_token(self) -> float:
        """USD per input token for the currently configured default model.
        Per-call cost for a specific model should be computed from the
        provider's own price table (see cost_usd on GenerationResult) —
        this property is the fallback used for router cost estimates
        before a specific model is chosen."""
        ...

    @property
    @abstractmethod
    def cost_per_output_token(self) -> float: ...

    @property
    @abstractmethod
    def context_window(self) -> int:
        """Context window, in tokens, for the provider's default model."""
        ...
