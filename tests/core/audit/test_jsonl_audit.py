from __future__ import annotations

import json

import pytest

from healer.audit.jsonl import JsonlAudit
from healer.core.schemas import AuditRecord


@pytest.mark.asyncio
async def test_jsonl_record(tmp_path):
    path = tmp_path / "audit.jsonl"
    sink = JsonlAudit(str(path))
    rec = AuditRecord(cluster_id="c1")
    await sink.record(rec)
    await sink.record(rec)
    lines = path.read_text(encoding="utf-8").strip().splitlines()
    assert len(lines) == 2
    data = json.loads(lines[0])
    assert data["cluster_id"] == "c1"
    assert data["record_id"] == rec.record_id