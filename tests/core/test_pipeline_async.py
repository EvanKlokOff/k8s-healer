from __future__ import annotations

import pytest

from healer.core.pipeline import Pipeline
from healer.core.schemas import (
    AuditRecord, Decision, Incident, Snapshot, AgentMeta, NodeInfo,
)


class _FakeAudit:
    def __init__(self):
        self.records: list[AuditRecord] = []

    async def record(self, rec: AuditRecord) -> None:
        self.records.append(rec)

    async def close(self) -> None:
        pass


class _FakeDiagnoser:
    def __init__(self, decision: Decision):
        self._decision = decision

    def diagnose(self, incident: Incident) -> Decision:
        return self._decision


class _FakeValidator:
    def validate(self, decision):
        return True, ""


@pytest.mark.asyncio
async def test_process_skips_when_disabled(monkeypatch):
    monkeypatch.setattr("healer.core.pipeline.settings.healer_enabled", False)
    audit = _FakeAudit()
    p = Pipeline([], _FakeDiagnoser(None), _FakeValidator(), [], audit, dedup=None)
    snap = Snapshot(
        snapshot_id="s", cluster_id="c", scout_node="k8s-worker-1",  # <-- совпадает с self_node.name,
        timestamp=__import__("datetime").datetime.now(__import__("datetime").timezone.utc),
        agent=AgentMeta(collected_at=__import__("datetime").datetime.now(__import__("datetime").timezone.utc),
                        duration_ms=1),
        self_node=NodeInfo(name="k8s-worker-1", ready=True),
    )
    assert await p.process(snap) == []
    assert audit.records == []


@pytest.mark.asyncio
async def test_enrich_node_ip_for_restart_kubelet(monkeypatch):
    monkeypatch.setattr("healer.core.pipeline.settings.healer_enabled", True)
    from datetime import datetime, timezone
    now = datetime.now(timezone.utc)
    snap = Snapshot(
        snapshot_id="s", cluster_id="c", scout_node="k8s-worker-1",  # <-- совпадает с self_node.name,
        timestamp=now,
        agent=AgentMeta(collected_at=now, duration_ms=1),
        self_node=NodeInfo(
            name="k8s-worker-1", ready=False,
            labels={"healer/ip": "192.168.122.11"},
        ),
    )
    inc = Incident(
        id="i1", type="node_not_ready", target="k8s-worker-1",
        detected_at=now, cluster_id="c",
    )
    decision = Decision(
        incident_id="i1", cluster_id="c",
        diagnosis="kubelet down", confidence=0.9,
        action_id="restart_kubelet", action_params={"node": "k8s-worker-1"},
        reason="test",
    )
    audit = _FakeAudit()
    p = Pipeline([], _FakeDiagnoser(decision), _FakeValidator(), [], audit, dedup=None)
    # обходим rule.evaluate — подаём инцидент напрямую через _handle
    rec = await p._handle(inc, snap)
    assert rec.decision.action_params.get("node_ip") == "192.168.122.11"
    assert rec.snapshot_id == "s"
