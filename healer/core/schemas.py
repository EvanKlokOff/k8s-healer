# healer/core/schemas.py
from __future__ import annotations
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Literal
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field, model_validator


SCHEMA_VERSION = "1.1"


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)
# ---------- Общие ----------

class CollectorError(BaseModel):
    model_config = ConfigDict(extra="forbid")

    collector: str
    message: str
    occurred_at: datetime


class AgentMeta(BaseModel):
    model_config = ConfigDict(extra="forbid")

    scout_version: str = "0.1.0"
    schema_version: str = SCHEMA_VERSION
    collected_at: datetime
    duration_ms: int
    errors: list[CollectorError] = Field(default_factory=list)


# ---------- Node ----------

class NodeCondition(BaseModel):
    model_config = ConfigDict(extra="forbid")

    type: str                     # Ready, MemoryPressure, DiskPressure, PIDPressure, NetworkUnavailable
    status: str                   # "True" | "False" | "Unknown"
    reason: str | None = None
    message: str | None = None
    last_transition: datetime | None = None
    last_heartbeat: datetime | None = None


class NodeResources(BaseModel):
    model_config = ConfigDict(extra="forbid")

    cpu_capacity: float | None = None
    cpu_allocatable: float | None = None
    mem_capacity_mb: int | None = None
    mem_allocatable_mb: int | None = None
    pods_capacity: int | None = None
    ephemeral_storage_gb: float | None = None


class NodeInfo(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str
    role: Literal["control_plane", "worker", "unknown"] = "unknown"
    labels: dict[str, str] = Field(default_factory=dict)
    annotations: dict[str, str] = Field(default_factory=dict)
    ready: bool
    conditions: list[NodeCondition] = Field(default_factory=list)
    conditions_index: dict[str, str] = Field(default_factory=dict)   # быстрый доступ: {"Ready": "False", ...}
    unschedulable: bool = False             # cordoned?
    taints: list[dict[str, Any]] = Field(default_factory=list)

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

    @model_validator(mode="after")
    def _fill_conditions_index(self) -> "NodeInfo":
        if not self.conditions_index and self.conditions:
            self.conditions_index = {c.type: c.status for c in self.conditions}
        # сверка ready с conditions_index["Ready"]
        idx_ready = self.conditions_index.get("Ready")
        if idx_ready is not None and bool(self.ready) != (idx_ready == "True"):
            log.warning(
                "node %s: ready=%s inconsistent with Ready=%s",
                self.name, self.ready, idx_ready,
            )
        return self

    @model_validator(mode="after")
    def _infer_role(self) -> "NodeInfo":
        if self.role == "unknown":
            labels = self.labels or {}
            if (
                "node-role.kubernetes.io/control-plane" in labels
                or "node-role.kubernetes.io/master" in labels
            ):
                self.role = "control_plane"
            elif "node-role.kubernetes.io/worker" in labels:
                self.role = "worker"
        return self

# ---------- Pod ----------

class ContainerState(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str
    ready: bool = False
    restart_count: int = 0
    state: Literal["running", "waiting", "terminated"] | None = None
    reason: str | None = None            # CrashLoopBackOff, ImagePullBackOff, OOMKilled, ...
    message: str | None = None
    started_at: datetime | None = None
    finished_at: datetime | None = None
    exit_code: int | None = None
    image: str | None = None


class PodInfo(BaseModel):
    model_config = ConfigDict(extra="forbid")

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

    labels: dict[str, str] = Field(default_factory=dict)
    annotations: dict[str, str] = Field(default_factory=dict)

    restarts: int = 0
    last_restart_at: datetime | None = None
    last_terminated_reason: str | None = None
    containers: list[ContainerState] = Field(default_factory=list)

    # ресурсы
    cpu_request: float | None = None
    cpu_limit: float | None = None
    mem_request_mb: int | None = None
    mem_limit_mb: int | None = None

    created_at: datetime | None = None


# ---------- Event ----------

class EventInfo(BaseModel):
    model_config = ConfigDict(extra="forbid")

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
    model_config = ConfigDict(extra="forbid")

    schema_version: Literal["1.1"] = SCHEMA_VERSION
    snapshot_id: str = Field(default_factory=lambda: str(uuid4()),description="UUID")                      # UUID
    cluster_id: str                        # напр. "k8s-prod-1"
    scout_node: str                        # где живёт скаут
    timestamp: datetime

    agent: AgentMeta

    # Скаут шлёт СВОЮ ноду в self_node.
    # Полную картину кластера core собирает через ClusterScout (или peer_nodes).
    self_node: NodeInfo
    peer_nodes: list[NodeInfo] = Field(default_factory=list)     # краткая сводка других нод (опционально)

    # Поды на этой ноде
    pods: list[PodInfo] = Field(default_factory=list)

    # События по этой ноде/подам (последние N)
    events: list[EventInfo] = Field(default_factory=list)

    # Опционально: временные ряды для ML в roadmap
    metrics: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def _check_scout_node(self) -> "Snapshot":
        if self.self_node.name != self.scout_node:
            raise ValueError(
                f"scout_node={self.scout_node!r} != self_node.name={self.self_node.name!r}"
            )
        return self

class Incident(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str                                       # hash(type + target + evidence)
    type: str                                     # ← строка, не enum
    target: str
    severity: Literal["low", "medium", "high", "critical"] = "medium"
    priority: int = 100                           # больше = важнее
    evidence: dict[str, Any] = Field(default_factory=dict)
    detected_at: datetime
    cluster_id: str
    rule_id: str | None = None
    rule_version: str = "0.1.0"
    scenario_version: str = "0.1.0"

class ActionRisk(str, Enum):
    NONE = "none"
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


class RollbackSpec(BaseModel):
    model_config = ConfigDict(extra="forbid")

    on_failure: str                               # action_id
    timeout_sec: int = 300
    health_check: str | None = None               # выражение


class Decision(BaseModel):
    model_config = ConfigDict(extra="forbid")

    decision_id: str = Field(default_factory=lambda: str(uuid4()))
    incident_id: str
    cluster_id: str
    diagnosis: str = Field(..., max_length=500)
    confidence: float = Field(..., ge=0.0, le=1.0)
    action_id: str                                # ← строка, валидируется по allowlist
    action_params: dict[str, Any] = Field(default_factory=dict)
    reason: str = Field(..., max_length=500)
    escalate: bool = False                        # True = только алерт
    risk: ActionRisk = ActionRisk.MEDIUM
    rollback: RollbackSpec | None = None

class ActionResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    decision_id: str
    action_id: str
    status: Literal["success", "failed", "skipped", "dry_run", "pending_approval"]
    message: str
    started_at: datetime
    finished_at: datetime


# ---------- Guardrails ----------

class GuardrailResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str
    allowed: bool
    reason: str = ""


# ---------- LLM meta ----------

class LLMMeta(BaseModel):
    model_config = ConfigDict(extra="forbid")

    provider: str
    model: str
    prompt_version: str = "0.1.0"
    prompt_tokens: int = 0
    completion_tokens: int = 0
    latency_ms: int = 0
    cached: bool = False


# ---------- Audit ----------

class AuditRecord(BaseModel):
    model_config = ConfigDict(extra="forbid")

    record_id: str = Field(default_factory=lambda: str(uuid4()))
    timestamp: datetime = Field(default_factory=datetime.utcnow)
    trace_id: str = Field(default_factory=lambda: str(uuid4()))
    cluster_id: str
    snapshot_id: str | None = None
    incident: Incident | None = None
    decision: Decision | None = None
    action_result: ActionResult | None = None
    guardrails: list[GuardrailResult] = Field(default_factory=list)
    llm_meta: LLMMeta | None = None
    versions: dict[str, str] = Field(default_factory=dict)