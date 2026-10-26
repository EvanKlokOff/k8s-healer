# healer/audit/factory.py
"""Фабрика audit-sinks из settings.audit_sinks (csv: jsonl,postgres)."""
from __future__ import annotations

import logging

from healer.audit.base import AuditSink
from healer.audit.jsonl import JsonlAudit
from healer.audit.postgres import PostgresAudit
from healer.core.config import Settings

log = logging.getLogger(__name__)


class CompositeAudit(AuditSink):
    """Пишет во все sinks. Ошибка одного не мешает другим."""

    def __init__(self, sinks: list[AuditSink]):
        self.sinks = sinks

    async def record(self, record) -> None:
        for s in self.sinks:
            try:
                await s.record(record)
            except Exception:
                log.exception("audit sink %s failed", type(s).__name__)

    async def close(self) -> None:
        for s in self.sinks:
            try:
                await s.close()
            except Exception:
                log.exception("audit sink %s close failed", type(s).__name__)


def build_audit(settings: Settings) -> AuditSink:
    names = [x.strip() for x in settings.audit_sinks.split(",") if x.strip()]
    sinks: list[AuditSink] = []
    for name in names:
        if name == "jsonl":
            sinks.append(JsonlAudit(settings.audit_jsonl_path))
            log.info("audit sink: jsonl -> %s", settings.audit_jsonl_path)
        elif name == "postgres":
            sinks.append(PostgresAudit(settings.postgres_dsn))
            log.info("audit sink: postgres")
        else:
            log.warning("unknown audit sink %r, skipping", name)
    if not sinks:
        raise ValueError(f"no audit sinks configured: {settings.audit_sinks!r}")
    if len(sinks) == 1:
        return sinks[0]
    return CompositeAudit(sinks)