# healer/core/schemas.py
from __future__ import annotations
from datetime import datetime
from enum import Enum
from typing import Any, Literal
from pydantic import BaseModel, Field


SCHEMA_VERSION = "1.1"


# ---------- Общие ----------

class CollectorError(BaseModel):
    collector: str
    message: str
    occurred_at: datetime


class AgentMeta(BaseModel):
    scout_version: str = "0.1.0"
    schema_version: str = SCHEMA_VERSION
    collected_at: datetime
    duration_ms: int
    errors: list[CollectorError] = []


# ---------- Node ----------

class NodeCondition(BaseModel):
    type: str                     # Ready, MemoryPressure, DiskPressure, PIDPressure, NetworkUnavailable
    status: str                   # "True" | "False" | "Unknown"
    reason: str | None = None
    message: str | None = None
    last_transition: datetime | None = None
    last_heartbeat: datetime | None = None


class NodeResources(BaseModel):
    cpu_capacity: float | None = None
    cpu_allocatable: float | None = None
    mem_capacity_mb: int | None = None
    mem_allocatable_mb: int | None = None
    pods_capacity: int | None = None
    ephemeral_storage_gb: float | None = None


class NodeInfo(BaseModel):
    name: str
    role: Literal["control_plane", "worker", "unknown"] = "unknown"
    labels: dict[str, str] = {}
    annotations: dict[str, str] = {}
    ready: bool
    conditions: list[NodeCondition] = []
    conditions_index: dict[str, str] = {}   # быстрый доступ: {"Ready": "False", ...}
    unschedulable: bool = False             # cordoned?
    taints: list[dict[str, Any]] = []

    # runtime
    kubelet_version: str | None = None
    os_image: str | None = None
    kernel_version: str | None = None
    container_runtime: str | None = None
    uptime_sec: int | None = None

    # процессы
    kubelet_up: bool | None = None
    containerd_up: bool | None = None
    kube_proxy_up: bool | None = None

    # метрики хоста
    cpu_usage_pct: float | None = None
    mem_usage_pct: float | None = None
    disk_usage_pct: float | None = None
    disk_inodes_pct: float | None = None
    load_1m: float | None = None
    load_5m: float | None = None
    load_15m: float | None = None

    # сеть
    net_rx_errors: int | None = None
    net_tx_errors: int | None = None
    conntrack_count: int | None = None

    resources: NodeResources | None = None


# ---------- Pod ----------

class ContainerState(BaseModel):
    name: str
    ready: bool
    restart_count: int
    state: Literal["running", "waiting", "terminated"] | None = None
    reason: str | None = None            # CrashLoopBackOff, ImagePullBackOff, OOMKilled, ...
    message: str | None = None
    started_at: datetime | None = None
    finished_at: datetime | None = None
    exit_code: int | None = None
    image: str | None = None


class PodInfo(BaseModel):
    namespace: str
    name: str
    uid: str | None = None
    node: str | None = None
    phase: str                            # Pending, Running, Succeeded, Failed, Unknown
    phase_reason: str | None = None       # почему Pending (Unschedulable, ImagePullBackOff, ...)
    qos_class: str | None = None          # Guaranteed, Burstable, BestEffort

    owner_kind: str | None = None         # Deployment, StatefulSet, DaemonSet, Job, ...
    owner_name: str | None = None
    owner_uid: str | None = None

    labels: dict[str, str] = {}
    annotations: dict[str, str] = {}

    restarts: int = 0
    last_terminated_reason: str | None = None
    containers: list[ContainerState] = []

    # ресурсы
    cpu_request: float | None = None
    cpu_limit: float | None = None
    mem_request_mb: int | None = None
    mem_limit_mb: int | None = None

    created_at: datetime | None = None


# ---------- Event ----------

class EventInfo(BaseModel):
    namespace: str
    reason: str
    message: str
    type: Literal["Normal", "Warning"] = "Normal"
    involved_kind: str
    involved_name: str
    involved_uid: str | None = None
    count: int = 1
    first_timestamp: datetime | None = None
    last_timestamp: datetime | None = None


# ---------- Snapshot ----------

class Snapshot(BaseModel):
    schema_version: Literal["1.1"] = SCHEMA_VERSION
    snapshot_id: str                       # UUID
    cluster_id: str                        # напр. "k8s-prod-1"
    scout_node: str                        # где живёт скаут
    timestamp: datetime

    agent: AgentMeta

    # Скаут шлёт СВОЮ ноду в self_node.
    # Полную картину кластера core собирает через ClusterScout (или peer_nodes).
    self_node: NodeInfo
    peer_nodes: list[NodeInfo] = []        # краткая сводка других нод (опционально)

    # Поды на этой ноде
    pods: list[PodInfo] = []

    # События по этой ноде/подам (последние N)
    events: list[EventInfo] = []

    # Опционально: временные ряды для ML в roadmap
    metrics: dict[str, Any] = {}