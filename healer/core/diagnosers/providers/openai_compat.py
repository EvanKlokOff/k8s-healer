from __future__ import annotations

import logging
import time
from typing import Any

import httpx

from healer.core.config import settings
from healer.core.diagnosers.providers.base import LLMProvider

log = logging.getLogger(__name__)

RETRY_DELAYS = (0.5, 1.5, 3.0)


class OpenAICompatibleProvider(LLMProvider):
    """Покрывает vLLM, Ollama, TGI, llama.cpp server, OpenAI, Together, Groq."""

    def __init__(
        self,
        base_url: str | None = None,
        api_key: str | None = None,
        model: str | None = None,
    ):
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

        last_exc: Exception | None = None
        for attempt, delay in enumerate((0.0, *RETRY_DELAYS), start=1):
            if delay:
                time.sleep(delay)
            try:
                with httpx.Client(timeout=settings.llm_timeout_sec) as client:
                    resp = client.post(url, json=payload, headers=headers)
                if resp.status_code == 429 or resp.status_code >= 500:
                    log.warning(
                        "LLM %s on attempt %d: %s",
                        resp.status_code, attempt, resp.text[:200],
                    )
                    last_exc = httpx.HTTPStatusError(
                        f"{resp.status_code}", request=resp.request, response=resp,
                    )
                    continue
                resp.raise_for_status()
                return resp.json()
            except (httpx.TransportError, httpx.TimeoutException) as exc:
                log.warning("LLM unreachable on attempt %d: %s", attempt, exc)
                last_exc = exc
        raise RuntimeError(f"LLM failed after retries: {last_exc}")