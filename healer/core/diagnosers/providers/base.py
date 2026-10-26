from abc import ABC, abstractmethod
from typing import Any


class LLMProvider(ABC):
    """Абстракция LLM. Реализации:
    - OpenAICompatibleProvider (vLLM, Ollama, OpenAI, Together, ...)
    - AnthropicProvider (позже)
    Замена модели = смена env-переменных, ядро не трогаем."""

    @abstractmethod
    def chat(
        self,
        messages: list[dict],
        tools: list[dict] | None = None,
        response_schema: dict | None = None,
    ) -> dict[str, Any]:
        ...