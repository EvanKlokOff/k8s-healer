from healer.core.config import settings
from healer.core.diagnosers.providers.base import LLMProvider
from healer.core.diagnosers.providers.openai_compat import OpenAICompatibleProvider


def get_provider(name: str | None = None) -> LLMProvider:
    name = name or settings.llm_provider
    if name == "openai_compat":
        return OpenAICompatibleProvider()
    raise ValueError(f"Unknown LLM_PROVIDER: {name}")