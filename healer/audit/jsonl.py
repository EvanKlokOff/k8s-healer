from __future__ import annotations

import json
from pathlib import Path

from healer.audit.base import AuditSink
from healer.core.schemas import AuditRecord


class JsonlAudit(AuditSink):
    def __init__(self, path: str = "decisions.jsonl"):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def record(self, record: AuditRecord) -> None:
        with self.path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(record.model_dump(mode="json"), ensure_ascii=False) + "\n")