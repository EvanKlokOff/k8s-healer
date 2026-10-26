from __future__ import annotations

import redis

from healer.core.config import settings
from healer.core.guardrails.base import Guardrail
from healer.core.schemas import Decision, GuardrailResult


class RateLimitGuardrail(Guardrail):
    name = "rate_limit"

    def __init__(self, redis_url: str | None = None):
        self.client = redis.from_url(redis_url or settings.redis_url, decode_responses=True)

    def check(self, decision: Decision) -> GuardrailResult:
        if decision.escalate:
            return GuardrailResult(name=self.name, allowed=True)

        target = decision.action_params.get("node") or decision.action_params.get("deployment") or "unknown"
        key = f"healer:rl:{decision.action_id}:{target}"
        limit = settings.rate_limit_per_node_per_hour
        try:
            count = self.client.incr(key)
            if count == 1:
                self.client.expire(key, 3600)
            if count > limit:
                return GuardrailResult(
                    name=self.name,
                    allowed=False,
                    reason=f"rate limit {limit}/h exceeded for {target}",
                )
        except redis.RedisError:
            return GuardrailResult(name=self.name, allowed=True, reason="redis down, fail-open")
        return GuardrailResult(name=self.name, allowed=True)