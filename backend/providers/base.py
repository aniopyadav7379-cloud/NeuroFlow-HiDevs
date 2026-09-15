from abc import ABC, abstractmethod
from collections.abc import AsyncGenerator
from dataclasses import dataclass
from typing import Any


@dataclass
class ChatMessage:
    role: str  # "system" | "user" | "assistant"
    content: str | list[Any]  # str for text, list for multi-modal


@dataclass
class GenerationResult:
    content: str
    model: str
    input_tokens: int
    output_tokens: int
    latency_ms: float
    cost_usd: float
    finish_reason: str


class BaseLLMProvider(ABC):
    def __init__(self, model_name: str) -> None:
        self.model_name = model_name

    @abstractmethod
    async def complete(self, messages: list[ChatMessage], **kwargs: Any) -> GenerationResult: ...  # noqa: ANN401

    @abstractmethod
    async def stream(
        self,
        messages: list[ChatMessage],
        **kwargs: Any,  # noqa: ANN401
    ) -> AsyncGenerator[str, None]: ...

    @abstractmethod
    async def embed(self, texts: list[str]) -> list[list[float]]: ...

    @property
    @abstractmethod
    def cost_per_input_token(self) -> float: ...

    @property
    @abstractmethod
    def cost_per_output_token(self) -> float: ...

    @property
    @abstractmethod
    def context_window(self) -> int: ...
