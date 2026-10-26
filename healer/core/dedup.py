# healer/core/dedup.py
from __future__ import annotations

import hashlib
import logging

import redis

from healer.core.schemas import Incident

log = logging.getLogger(__name__)

TTL_SEC = 600


def _incident_key(incident: Incident) -> str:
    raw = f"{incident.type}|{incident.target}|{sorted(incident.evidence.items())}"
    digest = hashlib.sha256(raw.encode()).hexdigest()[:16]
    return f"healer:incident:{digest}"


class Deduplicator:
    """Redis SETNX + TTL. Если инцидент уже в работе — не запускать пайплайн."""

    def __init__(self, redis_url: str, ttl_sec: int = TTL_SEC):
        self.client = redis.from_url(redis_url, decode_responses=True)
        self.ttl = ttl_sec

    def claim(self, incident: Incident) -> bool:
        """True — инцидент новый, обрабатываем. False — дубль."""
        key = _incident_key(incident)
        try:
            return bool(self.client.set(key, "1", nx=True, ex=self.ttl))
        except redis.RedisError:
            log.exception("Redis unavailable, allowing incident through")
            return True  # fail-open: лучше обработать, чем потерять