# tests/scout/conftest.py
"""Фикстуры для тестов скаута. Никакого реального k8s/SSH."""
from __future__ import annotations

from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from healer.core.schemas import (
    AgentMeta,
    NodeCondition,
    NodeInfo,
    Snapshot,
)

NOW = datetime(2025, 10, 15, 10, 0, 0, tzinfo=timezone.utc)


# ---------- фейковые k8s-объекты (упрощённые SimpleNamespace) ----------

def make_address(ip: str, type_: str = "InternalIP") -> SimpleNamespace:
    return SimpleNamespace(type=type_, address=ip)


def make_condition(type_: str, status: str, reason: str | None = None,
                   last_transition: datetime | None = None) -> SimpleNamespace:
    return SimpleNamespace(
        type=type_, status=status, reason=reason, message=None,
        last_transition_time=last_transition or NOW,
        last_heartbeat_time=last_transition or NOW,
    )


def make_node(
    name: str,
    ready: bool = True,
    internal_ip: str = "192.168.122.11",
    labels: dict | None = None,
    taints: list | None = None,
    unschedulable: bool = False,
    conditions_extra: list | None = None,
) -> SimpleNamespace:
    conds = [make_condition("Ready", "True" if ready else "False",
                            reason=None if ready else "KubeletNotReady")]
    if conditions_extra:
        conds.extend(conditions_extra)
    return SimpleNamespace(
        metadata=SimpleNamespace(
            name=name,
            labels=labels or {"kubernetes.io/hostname": name},
            annotations={},
        ),
        spec=SimpleNamespace(taints=taints or [], unschedulable=unschedulable),
        status=SimpleNamespace(
            addresses=[make_address(internal_ip)],
            conditions=conds,
            capacity={"cpu": "2", "memory": "4Gi", "pods": "110",
                      "ephemeral-storage": "20Gi"},
            allocatable={"cpu": "1900m", "memory": "3800Mi", "pods": "110"},
            node_info=SimpleNamespace(
                kubelet_version="v1.29.5",
                os_image="Debian GNU/Linux 12",
                kernel_version="6.1.0",
                container_runtime_version="containerd://1.7.18",
            ),
        ),
    )


def make_container_status(
    name: str = "app",
    ready: bool = True,
    restart_count: int = 0,
    state: str = "running",
    reason: str | None = None,
    exit_code: int | None = None,
    image: str = "nginx:1.25",
    last_finished_at: datetime | None = None,
) -> SimpleNamespace:
    running = SimpleNamespace(started_at=NOW) if state == "running" else None
    waiting = SimpleNamespace(reason=reason) if state == "waiting" else None
    terminated = (
        SimpleNamespace(reason=reason, exit_code=exit_code,
                        started_at=NOW, finished_at=NOW)
        if state == "terminated" else None
    )
    last_terminated = (
        SimpleNamespace(reason=reason, exit_code=exit_code,
                        finished_at=last_finished_at or NOW)
        if reason in ("OOMKilled", "CrashLoopBackOff") else None
    )
    return SimpleNamespace(
        name=name, ready=ready, restart_count=restart_count, image=image,
        state=SimpleNamespace(running=running, waiting=waiting, terminated=terminated),
        last_state=SimpleNamespace(terminated=last_terminated)
        if last_terminated else None,
    )


def make_pod(
    name: str,
    namespace: str = "default",
    node: str = "k8s-worker-1",
    phase: str = "Running",
    restart_count: int = 0,
    last_reason: str | None = None,
    owner_kind: str = "ReplicaSet",
    owner_name: str = "web-7d9f8b",
        last_finished_at: datetime | None = None,
) -> SimpleNamespace:
    containers = [
        make_container_status(
            name="app",
            restart_count=restart_count,
            state="waiting" if last_reason == "CrashLoopBackOff" else "running",
            reason=last_reason,
            exit_code=137 if last_reason == "OOMKilled" else None,
            last_finished_at=last_finished_at,
        )
    ]
    return SimpleNamespace(
        metadata=SimpleNamespace(
            namespace=namespace, name=name, uid=f"uid-{name}",
            labels={"app": "web"}, annotations={},
            creation_timestamp=NOW,
            owner_references=[SimpleNamespace(
                kind=owner_kind, name=owner_name, uid=f"uid-{owner_name}",
            )],
        ),
        spec=SimpleNamespace(
            node_name=node,
            containers=[SimpleNamespace(resources=SimpleNamespace(
                requests={"cpu": "100m", "memory": "64Mi"},
                limits={"cpu": "500m", "memory": "128Mi"},
            ))],
        ),
        status=SimpleNamespace(
            phase=phase, reason=None, qos_class="Burstable",
            container_statuses=containers,
        ),
    )


def make_event(
    reason: str,
    involved_kind: str,
    involved_name: str,
    namespace: str = "default",
    type_: str = "Warning",
    count: int = 1,
) -> SimpleNamespace:
    return SimpleNamespace(
        metadata=SimpleNamespace(namespace=namespace),
        reason=reason, message=f"{reason} on {involved_name}", type=type_,
        involved_object=SimpleNamespace(
            kind=involved_kind, name=involved_name, uid=f"uid-{involved_name}",
        ),
        count=count,
        first_timestamp=NOW, last_timestamp=NOW,
    )


# ---------- фикстуры ----------

@pytest.fixture
def fake_node():
    return make_node("k8s-worker-1", ready=True, internal_ip="192.168.122.11")


@pytest.fixture
def fake_worker2():
    return make_node(
        "k8s-worker-2", ready=False, internal_ip="192.168.122.12",
        conditions_extra=[make_condition(
            "DiskPressure", "True", reason="KubeletHasDiskPressure",
        )],
    )


@pytest.fixture
def fake_pod():
    return make_pod("web-7d9f8b-abc12")


@pytest.fixture
def fake_crashloop_pod():
    return make_pod(
        "web-7d9f8b-abc12", restart_count=6, last_reason="CrashLoopBackOff",
    )


@pytest.fixture
def fake_oom_pod():
    return make_pod(
        "web-7d9f8b-abc12", last_reason="OOMKilled",
    )


@pytest.fixture
def fake_node_event():
    return make_event("NodeNotReady", "Node", "k8s-worker-1")


@pytest.fixture
def fake_pod_event():
    return make_event("BackOff", "Pod", "web-7d9f8b-abc12")


@pytest.fixture
def minimal_snapshot() -> Snapshot:
    return Snapshot(
        snapshot_id="9f1c2e4a-7b3d-4e8f-9a1b-2c3d4e5f6a7b",
        cluster_id="k8s-dev-1",
        scout_node="k8s-worker-1",
        timestamp=NOW,
        agent=AgentMeta(collected_at=NOW, duration_ms=100),
        self_node=NodeInfo(
            name="k8s-worker-1",
            role="worker",
            labels={"kubernetes.io/hostname": "k8s-worker-1",
                    "healer/ip": "192.168.122.11"},
            ready=True,
            conditions=[NodeCondition(type="Ready", status="True",
                                      last_transition=NOW)],
            conditions_index={"Ready": "True"},
        ),
    )


@pytest.fixture
def ssh_output_healthy() -> str:
    # busy=12, idle=500, total=512 (busy+idle, остальные поля 0)
    return (
        "0.8 0.6 0.5\n"
        "12 500 512\n"
        "86400.00\n"
        "1024 4096\n"
        "450000 1000000\n"
        "800 10000\n"
        "active\n"
        "active\n"
        "active\n"
    )


@pytest.fixture
def ssh_output_kubelet_down() -> str:
    return (
        "0.8 0.6 0.5\n"
        "12 500 1000\n"
        "86400.00\n"
        "1024 4096\n"
        "450000 1000000\n"
        "800 10000\n"
        "inactive\n"
        "active\n"
        "unknown\n"
    )