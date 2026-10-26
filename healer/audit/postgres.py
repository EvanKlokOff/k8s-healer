from __future__ import annotations

import json
import logging

import asyncpg

from healer.audit.base import AuditSink
from healer.core.schemas import AuditRecord

log = logging.getLogger(__name__)

SCHEMA = """
CREATE TABLE IF NOT EXISTS audit_records (
    record_id     TEXT PRIMARY KEY,
    timestamp     TIMESTAMPTZ NOT NULL,
    trace_id      TEXT NOT NULL,
    cluster_id    TEXT NOT NULL,
    snapshot_id   TEXT,
    incident      JSONB,
    decision      JSONB,
    action_result JSONB,
    guardrails    JSONB,
    llm_meta      JSONB,
    versions      JSONB
);
"""


class PostgresAudit(AuditSink):
    def __init__(self, dsn: str):
        self.dsn = dsn
        self._pool: asyncpg.Pool | None = None

    async def _ensure_pool(self):
        if self._pool is None:
            self._pool = await asyncpg.create_pool(self.dsn)
            async with self._pool.acquire() as conn:
                await conn.execute(SCHEMA)
        return self._pool

    def record(self, record: AuditRecord) -> None:
        # MVP: синхронная обёртка. В реальности — async в pipeline.
        import asyncio
        try:
            asyncio.get_event_loop().run_until_complete(self._record_async(record))
        except RuntimeError:
            log.exception("PostgresAudit.record called outside event loop")

    async def _record_async(self, record: AuditRecord) -> None:
        pool = await self._ensure_pool()
        async with pool.acquire() as conn:
            await conn.execute(
                """INSERT INTO audit_records
                (record_id, timestamp, trace_id, cluster_id, snapshot_id,
                 incident, decision, action_result, guardrails, llm_meta, versions)
                VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11)""",
                record.record_id, record.timestamp, record.trace_id,
                record.cluster_id, record.snapshot_id,
                json.dumps(record.incident.model_dump(mode="json") if record.incident else None),
                json.dumps(record.decision.model_dump(mode="json") if record.decision else None),
                json.dumps(record.action_result.model_dump(mode="json") if record.action_result else None),
                json.dumps([g.model_dump(mode="json") for g in record.guardrails]),
                json.dumps(record.llm_meta.model_dump(mode="json") if record.llm_meta else None),
                json.dumps(record.versions),
            )