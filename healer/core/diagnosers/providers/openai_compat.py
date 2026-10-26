from __future__ import annotations

import logging
from typing import Any

import httpx

from healer.core.config import settings
from healer.core.diagnosers.providers.base import LLMProvider

log = logging.getLogger(__name__)


class OpenAICompatibleProvider(LLMProvider):
    """Покрывает vLLM, Ollama, TGI, llama.cpp server, OpenAI, Together, Groq."""

    def __init__(self, base_url: str | None = None, api_key: str | None = None,
                 model: str | None = None):
        self.base_url = (base_url or settings.llm_base_url).rstrip("/")
        self.api_key = api_key or settings.llm_api_key
        self.model = model or settings.llm_model

    def chat(self, messages, tools=None, response_schema=None) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "model": self.model,
            "messages": messages,
            "temperature": 0.1,
        }
        if response_schema is not None:
            payload["response_format"] = {"type": "json_object"}
        if tools:
            payload["tools"] = tools

        headers = {"Authorization": f"Bearer {self.api_key}"}
        url = f"{self.base_url}/chat/completions"
        log.debug("LLM request → %s", url)
        with httpx.Client(timeout=settings.llm_timeout_sec) as client:
            resp = client.post(url, json=payload, headers=headers)
            resp.raise_for_status()
            return resp.json()