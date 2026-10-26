# healer/scout/collectors/k8s_api_scout.py
"""Собирает k8s-часть снапшота: self_node, peer_nodes, pods, events.

Scout работает ВНЕ кластера (на хосте healer), один инстанс на ноду.
Kubeconfig берётся из settings.kubeconfig_path (/etc/healer/kubeconfig).

Поды собираются только со своей ноды (field_selector spec.nodeName),
иначе N скаутов пришлют N² дубликатов.
"""
from __future__ import annotations

import logging
import os
import time
from datetime import datetime, timezone

from kubernetes import client, config
from kubernetes.client.exceptions import ApiException

from healer.core.config import settings
from healer.core.schemas import (
    AgentMeta,
    CollectorError,
    ContainerState,
    EventInfo,
    NodeCondition,
    NodeInfo,
    NodeResources,
    PodInfo,
    Snapshot,
)
from healer.scout.collectors.base import Scout

log = logging.getLogger(__name__)

MAX_EVENTS = 50


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _role_from_labels(labels: dict[str, str]) -> str:
    if (
        "node-role.kubernetes.io/control-plane" in labels
        or "node-role.kubernetes.io/master" in labels
    ):
        return "control_plane"
    if "node-role.kubernetes.io/worker" in labels:
        return "worker"
    return "unknown"


def _internal_ip(status) -> str | None:
    for addr in status.addresses or []:
        if addr.type == "InternalIP":
            return addr.address
    return None


class K8sApiScout(Scout):
    def __init__(self) -> None:
        # out-of-cluster: всегда kubeconfig из settings, in-cluster fallback не нужен
        if settings.kubeconfig_path:
            config.load_kube_config(config_file=settings.kubeconfig_path)
            log.info("k8s client loaded from %s", settings.kubeconfig_path)
        else:
            try:
                config.load_incluster_config()
                log.info("k8s client loaded in-cluster")
            except Exception:
                config.load_kube_config()
                log.info("k8s client loaded from default kubeconfig")
        self.core = client.CoreV1Api()
        self.node_name = os.getenv("NODE_NAME", "")
        if not self.node_name:
            raise RuntimeError(
                "NODE_NAME env var is required (one scout instance per node). "
                "Set it in systemd unit: Environment=NODE_NAME=k8s-worker-1"
            )

    # ---------- public ----------

    def collect(self) -> Snapshot:
        started = time.monotonic()
        errors: list[CollectorError] = []

        self_node = self._collect_self_node(errors)
        peer_nodes = self._collect_peer_nodes(errors)
        pods = self._collect_pods(errors)
        events = self._collect_events(errors, pods)

        duration_ms = int((time.monotonic() - started) * 1000)
        return Snapshot(
            cluster_id=settings.cluster_id,
            scout_node=self.node_name,
            timestamp=_now(),
            agent=AgentMeta(
                collected_at=_now(),
                duration_ms=duration_ms,
                errors=errors,
            ),
            self_node=self_node,
            peer_nodes=peer_nodes,
            pods=pods,
            events=events,
        )

    # ---------- nodes ----------

    def _collect_self_node(self, errors: list[CollectorError]) -> NodeInfo:
        try:
            node = self.core.read_node(self.node_name)
        except ApiException as exc:
            self._err(errors, "k8s_api.read_node", exc)
            return NodeInfo(name=self.node_name, ready=False)
        except Exception as exc:
            self._err(errors, "k8s_api.read_node", exc)
            return NodeInfo(name=self.node_name, ready=False)
        return self._node_to_info(node)

    def _collect_peer_nodes(self, errors: list[CollectorError]) -> list[NodeInfo]:
        try:
            items = self.core.list_node().items
        except Exception as exc:
            self._err(errors, "k8s_api.list_node", exc)
            return []

        peers: list[NodeInfo] = []
        for n in items:
            if n.metadata.name == self.node_name:
                continue
            full = self._node_to_info(n)
            # краткая сводка, но С last_transition в conditions — нужно правилу
            # node_not_ready(duration_sec=300) для peer-нод
            peers.append(NodeInfo(
                name=full.name,
                role=full.role,
                labels=full.labels,              # содержит healer/ip
                annotations={},
                ready=full.ready,
                conditions=full.conditions,      # <-- с last_transition
                conditions_index=full.conditions_index,
                unschedulable=full.unschedulable,
                taints=full.taints,
            ))
        return peers

    def _node_to_info(self, n) -> NodeInfo:
        spec = n.spec
        status = n.status
        meta = n.metadata
        labels = dict(meta.labels or {})
        annotations = dict(meta.annotations or {})

        # сохраняем InternalIP для SSH-доступа к ноде (host_metrics)
        ip = _internal_ip(status)
        if ip:
            labels["healer/ip"] = ip

        conditions: list[NodeCondition] = []
        ready = False
        for c in status.conditions or []:
            conditions.append(NodeCondition(
                type=c.type,
                status=c.status,
                reason=c.reason,
                message=c.message,
                last_transition=c.last_transition_time,
                last_heartbeat=c.last_heartbeat_time,
            ))
            if c.type == "Ready" and c.status == "True":
                ready = True

        taints = [
            {"key": t.key, "value": t.value, "effect": t.effect}
            for t in (spec.taints or [])
        ]

        resources = None
        if status.capacity or status.allocatable:
            cap = status.capacity or {}
            alloc = status.allocatable or {}
            resources = NodeResources(
                cpu_capacity=self._parse_cpu(cap.get("cpu")),
                cpu_allocatable=self._parse_cpu(alloc.get("cpu")),
                mem_capacity_mb=self._parse_mem_mb(cap.get("memory")),
                mem_allocatable_mb=self._parse_mem_mb(alloc.get("memory")),
                pods_capacity=self._parse_int(cap.get("pods")),
                ephemeral_storage_gb=self._parse_storage_gb(
                    cap.get("ephemeral-storage")
                ),
            )

        return NodeInfo(
            name=meta.name,
            role=_role_from_labels(labels),  # type: ignore[arg-type]
            labels=labels,
            annotations=annotations,
            ready=ready,
            conditions=conditions,
            conditions_index={c.type: c.status for c in conditions},
            unschedulable=bool(spec.unschedulable),
            taints=taints,
            kubelet_version=status.node_info.kubelet_version if status.node_info else None,
            os_image=status.node_info.os_image if status.node_info else None,
            kernel_version=status.node_info.kernel_version if status.node_info else None,
            container_runtime=status.node_info.container_runtime_version if status.node_info else None,
            resources=resources,
        )

    # ---------- pods ----------

    def _collect_pods(self, errors: list[CollectorError]) -> list[PodInfo]:
        try:
            items = self.core.list_pod_for_all_namespaces(
                field_selector=f"spec.nodeName={self.node_name}",
            ).items
        except Exception as exc:
            self._err(errors, "k8s_api.list_pods", exc)
            return []

        pods: list[PodInfo] = []
        for p in items:
            containers: list[ContainerState] = []
            restarts = 0
            last_reason = None
            last_finished = None

            for cs in p.status.container_statuses or []:
                restarts += cs.restart_count
                state, reason, exit_code, started_at, finished_at = (
                    self._container_state(cs)
                )
                # если контейнер уже перезапустился — exit_code/reason из last_state
                if cs.last_state and cs.last_state.terminated and exit_code is None:
                    term = cs.last_state.terminated
                    exit_code = term.exit_code
                    finished_at = term.finished_at

                containers.append(ContainerState(
                    name=cs.name,
                    ready=bool(cs.ready),
                    restart_count=cs.restart_count,
                    state=state,
                    reason=reason,
                    exit_code=exit_code,
                    started_at=started_at,
                    finished_at=finished_at,
                    image=cs.image,
                ))
                if cs.last_state and cs.last_state.terminated:
                    term = cs.last_state.terminated
                    last_reason = term.reason or last_reason
                    if term.finished_at and (
                        last_finished is None or term.finished_at > last_finished
                    ):
                        last_finished = term.finished_at

            owner_kind = owner_name = owner_uid = None
            if p.metadata.owner_references:
                ref = p.metadata.owner_references[0]
                owner_kind, owner_name, owner_uid = ref.kind, ref.name, ref.uid

            req_cpu, lim_cpu, req_mem, lim_mem = self._pod_resources(p)

            pods.append(PodInfo(
                namespace=p.metadata.namespace,
                name=p.metadata.name,
                uid=p.metadata.uid,
                node=p.spec.node_name,
                phase=p.status.phase or "Unknown",
                phase_reason=p.status.reason,
                qos_class=p.status.qos_class,
                owner_kind=owner_kind,
                owner_name=owner_name,
                owner_uid=owner_uid,
                labels=dict(p.metadata.labels or {}),
                annotations=dict(p.metadata.annotations or {}),
                restarts=restarts,
                last_restart_at=last_finished,  # <-- новая строка
                last_terminated_reason=last_reason,
                containers=containers,
                cpu_request=req_cpu,
                cpu_limit=lim_cpu,
                mem_request_mb=req_mem,
                mem_limit_mb=lim_mem,
                created_at=p.metadata.creation_timestamp,
            ))
        return pods

    @staticmethod
    def _container_state(cs):
        if cs.state:
            if cs.state.running:
                r = cs.state.running
                return "running", None, None, r.started_at, None
            if cs.state.waiting:
                w = cs.state.waiting
                return "waiting", w.reason, None, None, None
            if cs.state.terminated:
                t = cs.state.terminated
                return "terminated", t.reason, t.exit_code, t.started_at, t.finished_at
        return None, None, None, None, None

    @staticmethod
    def _pod_resources(p) -> tuple[float | None, float | None, int | None, int | None]:
        req_cpu = lim_cpu = None
        req_mem = lim_mem = None
        for c in p.spec.containers or []:
            res = c.resources
            if not res:
                continue
            if res.requests:
                req_cpu = (req_cpu or 0.0) + (K8sApiScout._parse_cpu(res.requests.get("cpu")) or 0.0)
                req_mem = (req_mem or 0) + (K8sApiScout._parse_mem_mb(res.requests.get("memory")) or 0)
            if res.limits:
                lim_cpu = (lim_cpu or 0.0) + (K8sApiScout._parse_cpu(res.limits.get("cpu")) or 0.0)
                lim_mem = (lim_mem or 0) + (K8sApiScout._parse_mem_mb(res.limits.get("memory")) or 0)
        return req_cpu, lim_cpu, req_mem, lim_mem

    # ---------- events ----------

    def _collect_events(
            self, errors: list[CollectorError], pods: list[PodInfo],
    ) -> list[EventInfo]:
        """События по ноде И по подам на этой ноде.

        Почему так:
        - k8s field_selector НЕ поддерживает OR / IN по involvedObject.name,
          поэтому нельзя одним запросом получить "события по ноде + по её подам".
        - N+1 запросов (по одному list_namespaced_event на под) — плохо:
          на ноде может быть 100+ подов → 100 API-вызовов за цикл × N скаутов.
        - Поэтому делаем 2 запроса ко всему кластеру:
            1) involvedObject.kind=Node  → фильтр по имени ноды на клиенте
            2) involvedObject.kind=Pod   → фильтр по именам подов этой ноды
          Это 2 вызова независимо от числа подов. Ответ ограничен event-ttl
          (по умолчанию 1 час) на стороне apiserver.
        - Поды переданы извне (уже собраны в _collect_pods), чтобы не делать
          повторный list_pod_for_all_namespaces.
        """
        raw: list = []
        pod_names = {p.name for p in pods}
        pod_namespaces = {p.namespace for p in pods}

        # 1) события по ноде (фильтр на сервере — точный, не нужен клиентский)
        try:
            raw.extend(self.core.list_event_for_all_namespaces(
                field_selector=(
                    f"involvedObject.kind=Node,"
                    f"involvedObject.name={self.node_name}"
                ),
            ).items)
        except Exception as exc:
            self._err(errors, "k8s_api.list_events.node", exc)

        # 2) события по подам — один запрос на все pod-события кластера,
        #    фильтр по именам/namespace'ам нашей ноды — на клиенте.
        try:
            all_pod_events = self.core.list_event_for_all_namespaces(
                field_selector="involvedObject.kind=Pod",
            ).items
            raw.extend(
                e for e in all_pod_events
                if e.involved_object.name in pod_names
                and (e.metadata.namespace or "default") in pod_namespaces
            )
        except Exception as exc:
            self._err(errors, "k8s_api.list_events.pods", exc)

        # нормализация + дедуп (одно и то же событие могло прийти из обоих запросов,
        # если involvedObject.kind=Pod, а имя совпало с именем ноды — маловероятно,
        # но защищаемся)
        seen: set[tuple[str, str, str, str]] = set()
        events: list[EventInfo] = []
        for e in raw:
            key = (
                e.metadata.namespace or "default",
                e.involved_object.kind or "",
                e.involved_object.name or "",
                e.reason or "",
            )
            if key in seen:
                continue
            seen.add(key)
            events.append(EventInfo(
                namespace=e.metadata.namespace or "default",
                reason=e.reason or "",
                message=e.message or "",
                type=e.type or "Normal",  # type: ignore[arg-type]
                involved_kind=e.involved_object.kind or "",
                involved_name=e.involved_object.name or "",
                involved_uid=e.involved_object.uid,
                count=e.count or 1,
                first_timestamp=e.first_timestamp,
                last_timestamp=e.last_timestamp,
            ))

        events.sort(
            key=lambda ev: ev.last_timestamp
                           or datetime.min.replace(tzinfo=timezone.utc),
        )
        return events[-MAX_EVENTS:]
    # ---------- helpers ----------

    @staticmethod
    def _err(errors: list[CollectorError], collector: str, exc: Exception) -> None:
        log.warning("collector %s failed: %s", collector, exc)
        errors.append(CollectorError(
            collector=collector,
            message=str(exc),
            occurred_at=_now(),
        ))

    @staticmethod
    def _parse_cpu(v: str | None) -> float | None:
        if not v:
            return None
        v = v.strip()
        try:
            if v.endswith("m"):
                return float(v[:-1]) / 1000.0
            return float(v)
        except ValueError:
            return None

    @staticmethod
    def _parse_mem_mb(v: str | None) -> int | None:
        if not v:
            return None
        v = v.strip()
        units = {"Ki": 1 / 1024, "Mi": 1, "Gi": 1024, "Ti": 1024 * 1024,
                 "K": 1 / 1000 / 1024, "M": 1 / 1000 * 1000 / 1024, "G": 1000 * 1000 / 1024}
        for suf, mul in units.items():
            if v.endswith(suf):
                try:
                    return int(float(v[:-len(suf)]) * mul)
                except ValueError:
                    return None
        try:
            return int(float(v) / (1024 * 1024))
        except ValueError:
            return None

    @staticmethod
    def _parse_int(v: str | None) -> int | None:
        try:
            return int(v) if v else None
        except ValueError:
            return None

    @staticmethod
    def _parse_storage_gb(v: str | None) -> float | None:
        if not v:
            return None
        v = v.strip()
        units = {"Ki": 1 / 1024 / 1024, "Mi": 1 / 1024, "Gi": 1, "Ti": 1024}
        for suf, mul in units.items():
            if v.endswith(suf):
                try:
                    return float(v[:-len(suf)]) * mul
                except ValueError:
                    return None
        return None