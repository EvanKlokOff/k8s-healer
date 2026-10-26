# healer/core/diagnosers/llm.py
"""LLMDiagnoser: инцидент → Decision + LLMMeta.

- Промпт из prompts/v0.1.0.txt (версионирование).
- Structured output: JSON Schema, парсинг markdown-JSON.
- Retry 1 раз с уточняющим промптом при невалидном ответе.
- Confidence < threshold → принудительно raise_alert + escalate.
- Кэш по sha256(incident) в Redis (TTL 1 ч).
"""
from __future__ import annotations

import hashlib
import json
import logging
import re
import time
from datetime import datetime, timezone
from pathlib import Path

from pydantic import ValidationError

from healer.core.config import settings
from healer.core.diagnosers.base import Diagnoser
from healer.core.diagnosers.providers.base import LLMProvider
from healer.core.diagnosers.providers.factory import get_provider
from healer.core.schemas import Decision, Incident, LLMMeta

log = logging.getLogger(__name__)

PROMPT_VERSION = "0.1.0"
PROMPT_PATH = Path(__file__).parent / "prompts" / f"v{PROMPT_VERSION}.txt"

CACHE_TTL_SEC = 3600

_JSON_BLOCK_RE = re.compile(r"```(?:json)?\s*(\{.*?\})\s*```", re.DOTALL)


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _load_system_prompt() -> str:
    try:
        return PROMPT_PATH.read_text(encoding="utf-8")
    except FileNotFoundError:
        log.warning("prompt file %s not found, using minimal fallback", PROMPT_PATH)
        return (
            "You are a Kubernetes healer. Reply ONLY with JSON: "
            '{"diagnosis":"...","confidence":0.0,"action_id":"raise_alert",'
            '"action_params":{},"reason":"...","escalate":true}'
        )


def _extract_json(text: str) -> dict | None:
    """LLM может вернуть markdown ```json ... ``` или голый JSON."""
    if not text:
        return None
    # 1) markdown-блок
    m = _JSON_BLOCK_RE.search(text)
    if m:
        try:
            return json.loads(m.group(1))
        except json.JSONDecodeError:
            pass
    # 2) голый JSON — ищем первый { и последний }
    start = text.find("{")
    end = text.rfind("}")
    if start != -1 and end > start:
        try:
            return json.loads(text[start:end + 1])
        except json.JSONDecodeError:
            pass
    # 3) весь текст
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return None


def _cache_key(incident: Incident) -> str:
    raw = incident.model_dump_json()
    return "healer:llm:" + hashlib.sha256(raw.encode()).hexdigest()[:32]


class LLMDiagnoser(Diagnoser):
    def __init__(
        self,
        provider: LLMProvider | None = None,
        redis_url: str | None = None,
        confidence_threshold: float | None = None,
    ):
        self.provider = provider or get_provider()
        self.confidence_threshold = (
            confidence_threshold
            if confidence_threshold is not None
            else settings.confidence_threshold
        )
        self.system_prompt = _load_system_prompt()
        self._redis = None
        if redis_url is not False:                       # явный opt-out для тестов
            try:
                import redis as _redis
                self._redis = _redis.from_url(
                    redis_url or settings.redis_url, decode_responses=True,
                )
            except Exception:
                log.warning("redis unavailable, LLM cache disabled")
                self._redis = None

    # ---------- public ----------

    def diagnose(self, incident: Incident) -> tuple[Decision, LLMMeta | None]:
        # 1) кэш
        cached = self._cache_get(incident)
        if cached is not None:
            decision, meta = cached
            meta.cached = True
            return decision, meta

        # 2) вызов LLM (2 попытки: обычная + уточняющая)
        decision, meta = self._call_llm(incident, retry_hint=None)
        if decision is None:
            decision, meta = self._call_llm(incident, retry_hint="invalid_json")

        if decision is None:
            return self._fallback(incident, reason="LLM returned unparseable output")

        # 3) confidence threshold
        if decision.confidence < self.confidence_threshold and not decision.escalate:
            log.info(
                "incident %s: confidence %.2f < %.2f, forcing escalate",
                incident.id, decision.confidence, self.confidence_threshold,
            )
            decision = decision.model_copy(update={
                "action_id": "raise_alert",
                "action_params": {},
                "escalate": True,
                "reason": (
                    f"confidence {decision.confidence:.2f} < "
                    f"threshold {self.confidence_threshold:.2f}; "
                    f"original action: {decision.action_id}. "
                    f"{decision.reason}"
                )[:500],
            })

        # 4) кэш
        self._cache_set(incident, decision, meta)
        return decision, meta

    # ---------- LLM call ----------

    def _call_llm(
        self, incident: Incident, retry_hint: str | None,
    ) -> tuple[Decision | None, LLMMeta]:
        user_msg = json.dumps(
            {"incident": incident.model_dump(mode="json")},
            ensure_ascii=False,
        )
        if retry_hint:
            user_msg += (
                "\n\nYour previous response was not valid JSON. "
                "Reply ONLY with a JSON object, no markdown, no comments."
            )

        t0 = time.monotonic()
        try:
            raw = self.provider.chat(
                messages=[
                    {"role": "system", "content": self.system_prompt},
                    {"role": "user", "content": user_msg},
                ],
                response_schema={"type": "object"},
            )
        except Exception:
            log.exception("LLM provider failed for incident %s", incident.id)
            latency_ms = int((time.monotonic() - t0) * 1000)
            return None, LLMMeta(
                provider=settings.llm_provider,
                model=settings.llm_model,
                prompt_version=PROMPT_VERSION,
                latency_ms=latency_ms,
                cached=False,
            )

        latency_ms = int((time.monotonic() - t0) * 1000)
        meta = self._build_meta(raw, latency_ms)

        content = (
            raw.get("choices", [{}])[0].get("message", {}).get("content", "")
        )
        data = _extract_json(content)
        if data is None:
            log.warning(
                "incident %s: LLM response is not JSON: %r",
                incident.id, content[:500],
            )
            return None, meta

        # 5) валидация через pydantic
        try:
            decision = Decision(
                incident_id=incident.id,
                cluster_id=incident.cluster_id,
                diagnosis=str(data.get("diagnosis", ""))[:500] or "no diagnosis",
                confidence=float(data.get("confidence", 0.0)),
                action_id=str(data.get("action_id", "raise_alert")),
                action_params=dict(data.get("action_params") or {}),
                reason=str(data.get("reason", ""))[:500] or "no reason",
                escalate=bool(data.get("escalate", False)),
            )
        except (ValidationError, ValueError, TypeError) as exc:
            log.warning(
                "incident %s: LLM output failed Decision validation: %s",
                incident.id, exc,
            )
            return None, meta

        return decision, meta

    @staticmethod
    def _build_meta(raw: dict, latency_ms: int) -> LLMMeta:
        usage = raw.get("usage") or {}
        return LLMMeta(
            provider=settings.llm_provider,
            model=settings.llm_model,
            prompt_version=PROMPT_VERSION,
            prompt_tokens=int(usage.get("prompt_tokens", 0) or 0),
            completion_tokens=int(usage.get("completion_tokens", 0) or 0),
            latency_ms=latency_ms,
            cached=False,
        )

    # ---------- fallback ----------

    def _fallback(self, incident: Incident, reason: str) -> tuple[Decision, LLMMeta]:
        log.warning("incident %s: LLM fallback → raise_alert (%s)", incident.id, reason)
        return Decision(
            incident_id=incident.id,
            cluster_id=incident.cluster_id,
            diagnosis="llm_failure",
            confidence=0.0,
            action_id="raise_alert",
            action_params={},
            reason=f"LLM unavailable or invalid output: {reason}"[:500],
            escalate=True,
        ), LLMMeta(
            provider=settings.llm_provider,
            model=settings.llm_model,
            prompt_version=PROMPT_VERSION,
            latency_ms=0,
            cached=False,
        )

    # ---------- cache ----------

    def _cache_get(self, incident: Incident):
        if self._redis is None:
            return None
        try:
            raw = self._redis.get(_cache_key(incident))
            if not raw:
                return None
            data = json.loads(raw)
            decision = Decision.model_validate(data["decision"])
            meta = LLMMeta.model_validate(data["meta"])
            log.info("incident %s: LLM cache hit", incident.id)
            return decision, meta
        except Exception:
            log.exception("LLM cache get failed, ignoring")
            return None

    def _cache_set(self, incident: Incident, decision: Decision, meta: LLMMeta) -> None:
        if self._redis is None:
            return
        try:
            self._redis.set(
                _cache_key(incident),
                json.dumps({
                    "decision": decision.model_dump(mode="json"),
                    "meta": meta.model_dump(mode="json"),
                }),
                ex=CACHE_TTL_SEC,
            )
        except Exception:
            log.exception("LLM cache set failed, ignoring")