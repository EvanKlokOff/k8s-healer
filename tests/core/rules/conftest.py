"""Фикстуры для тестов правил: snapshot-билдеры."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from healer.core.schemas import (
    AgentMeta,
    ContainerState,
    NodeCondition,
    NodeInfo,
    PodInfo,
    Snapshot,
)

NOW = datetime(2025, 10, 15, 10, 0, 0, tzinfo=timezone.utc)


def make_node(
    name: str,
    ready: bool = True,
    role: str = "worker",
    conditions: list[NodeCondition] | None = None,
    labels: dict | None = None,
) -> NodeInfo:
    conds = conditions or [
        NodeCondition(type="Ready", status="True" if ready else "False",
                      last_transition=NOW - timedelta(minutes=10)),
    ]
    return NodeInfo(
        name=name,
        role=role,  # type: ignore[arg-type]
        labels=labels or {},
        ready=ready,
        conditions=conds,
        conditions_index={c.type: c.status for c in conds},
    )


def make_pod(
    name: str,
    namespace: str = "default",
    node: str = "k8s-worker-1",
    restarts: int = 0,
    last_terminated_reason: str | None = None,
    last_restart_at: datetime | None = None,
    containers: list[ContainerState] | None = None,
    mem_limit_mb: int | None = 128,
) -> PodInfo:
    return PodInfo(
        namespace=namespace, name=name, node=node, phase="Running",
        restarts=restarts,
        last_terminated_reason=last_terminated_reason,
        last_restart_at=last_restart_at,
        containers=containers or [],
        owner_kind="ReplicaSet", owner_name="web-7d9f8b",
        mem_limit_mb=mem_limit_mb,
    )


def make_snapshot(
    self_node: NodeInfo,
    peer_nodes: list[NodeInfo] | None = None,
    pods: list[PodInfo] | None = None,
    cluster_id: str = "k8s-dev-1",
) -> Snapshot:
    return Snapshot(
        snapshot_id="snap-1",
        cluster_id=cluster_id,
        scout_node=self_node.name,
        timestamp=NOW,
        agent=AgentMeta(collected_at=NOW, duration_ms=10),
        self_node=self_node,
        peer_nodes=peer_nodes or [],
        pods=pods or [],
    )


@pytest.fixture
def healthy_snapshot() -> Snapshot:
    return make_snapshot(make_node("k8s-worker-1"))


@pytest.fixture
def not_ready_self_snapshot() -> Snapshot:
    node = make_node("k8s-worker-1", ready=False, conditions=[
        NodeCondition(type="Ready", status="False",
                      last_transition=NOW - timedelta(minutes=10)),
    ])
    return make_snapshot(node)


@pytest.fixture
def not_ready_peer_snapshot() -> Snapshot:
    self_n = make_node("k8s-worker-2")
    peer = make_node("k8s-worker-1", ready=False, conditions=[
        NodeCondition(type="Ready", status="False",
                      last_transition=NOW - timedelta(minutes=10)),
    ])
    return make_snapshot(self_n, peer_nodes=[peer])