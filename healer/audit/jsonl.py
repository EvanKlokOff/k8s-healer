# healer/audit/jsonl.py
from __future__ import annotations

import asyncio
import json
import logging
from pathlib import Path

from healer.audit.base import AuditSink
from healer.core.schemas import AuditRecord

log = logging.getLogger(__name__)


class JsonlAudit(AuditSink):
    def __init__(self, path: str = "decisions.jsonl"):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = asyncio.Lock()

    async def record(self, record: AuditRecord) -> None:
        # asyncio.Lock защищает от интерливинга двух корутин на одном файле.
        # Запись синхронная — файл локальный, буферизованный, < 1 мс.
        async with self._lock:
            line = json.dumps(
                record.model_dump(mode="json"), ensure_ascii=False,
            ) + "\n"
            try:
                with self.path.open("a", encoding="utf-8") as f:
                    f.write(line)
            except Exception:
                log.exception("jsonl audit write failed: %s", self.path)