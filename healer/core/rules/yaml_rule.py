# healer/core/rules/yaml_rule.py
"""YamlRule — единственная реализация Rule в MVP.

Поддерживает 4 условия (по incident_type):
- node_not_ready:      node_condition=Ready, status=False, duration_sec
- node_disk_pressure:  node_condition=DiskPressure, status=True
- pod_crashloop:       pod_restarts_gt, window_sec
- pod_oomkilled:       last_terminated_reason=OOMKilled

Evidence нормализован: одинаковые поля для self_node и peer_nodes,
чтобы Deduplicator в core не создавал дубли (N скаутов × одна нода).
"""
from __future__ import annotations

import hashlib
import json
import logging
from datetime import datetime, timezone
from typing import Any, Callable

from healer.core.rules.base import Rule, RuleConfig
from healer.core.schemas import (
    Incident,
    NodeInfo,
    PodInfo,
    Snapshot,
)

log = logging.getLogger(__name__)

DEFAULT_WINDOW_SEC = 600
DEFAULT_DURATION_SEC = 300


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _incident_id(incident_type: str, target: str, evidence: dict[str, Any]) -> str:
    """Стабильный хеш — одинаков для self и peer, если evidence нормализован."""
    raw = json.dumps(
        {"type": incident_type, "target": target, "evidence": evidence},
        sort_keys=True, default=str,
    )
    return hashlib.sha256(raw.encode()).hexdigest()[:16]


def _node_by_name(snapshot: Snapshot, name: str) -> NodeInfo | None:
    if snapshot.self_node.name == name:
        return snapshot.self_node
    for n in snapshot.peer_nodes:
        if n.name == name:
            return n
    return None


def _iter_all_nodes(snapshot: Snapshot):
    """self + peers, без дублей (self_node может быть и в peer_nodes, если скаут так собрал)."""
    seen = {snapshot.self_node.name}
    yield snapshot.self_node
    for n in snapshot.peer_nodes:
        if n.name in seen:
            continue
        seen.add(n.name)
        yield n


def _node_condition(node: NodeInfo, ctype: str) -> tuple[str | None, datetime | None]:
    """Возвращает (status, last_transition) для condition type.

    Приоритет — conditions_index (быстрый доступ) + поиск в conditions
    для last_transition. Если conditions_index пуст, ищем в conditions.
    """
    status = (node.conditions_index or {}).get(ctype)
    last_transition = None
    for c in node.conditions:
        if c.type == ctype:
            if status is None:
                status = c.status
            last_transition = c.last_transition
            break
    return status, last_transition


def _pod_target(pod: PodInfo) -> str:
    return f"{pod.namespace}/{pod.name}"


class YamlRule(Rule):
    """Правило, параметризованное YAML-конфигом."""

    def __init__(self, config: RuleConfig, now_fn: Callable[[], datetime] | None = None):
        self.config = config
        self.rule_id = config.id
        self.version = config.version
        self.incident_type = config.incident_type
        self.priority = config.priority
        self.severity = config.severity
        self._now = now_fn or _now        # <-- инжект
    # ---------- public ----------

    def evaluate(self, snapshot: Snapshot) -> list[Incident]:
        if not self.config.enabled:
            return []
        handler = getattr(self, f"_eval_{self.incident_type}", None)
        if handler is None:
            log.warning(
                "rule %s: unsupported incident_type %r, skipping",
                self.rule_id, self.incident_type,
            )
            return []
        try:
            return handler(snapshot)
        except Exception:
            log.exception("rule %s failed on snapshot %s", self.rule_id, snapshot.snapshot_id)
            return []

    # ---------- node_not_ready ----------

    def _eval_node_not_ready(self, snapshot: Snapshot) -> list[Incident]:
        cfg = self.config.condition
        ctype = cfg.get("node_condition", "Ready")
        wanted_status = str(cfg.get("status", "False"))
        min_duration = int(cfg.get("duration_sec", DEFAULT_DURATION_SEC))
        now = self._now()

        incidents: list[Incident] = []
        for node in _iter_all_nodes(snapshot):
            status, last_transition = _node_condition(node, ctype)
            if status != wanted_status:
                continue

            # duration: если last_transition неизвестен — не можем посчитать,
            # считаем «только что» и пропускаем (лучше пропустить, чем ложно сработать)
            if last_transition is None:
                continue
            age_sec = (now - last_transition).total_seconds()
            if age_sec < min_duration:
                continue

            # НОРМАЛИЗОВАННЫЙ evidence: одинаковый для self и peer.
            # НЕ включаем kubelet_up/cpu_usage_pct — они есть только у self.
            evidence = {
                "node": node.name,
                "condition": ctype,
                "status": wanted_status,
                "last_transition": last_transition.isoformat(),
                "age_sec": int(age_sec),
            }
            if node.role:
                evidence["role"] = node.role

            incidents.append(self._make_incident(
                snapshot=snapshot,
                target=node.name,
                evidence=evidence,
                detected_at=now,
            ))
        return incidents

    # ---------- node_disk_pressure ----------

    def _eval_node_disk_pressure(self, snapshot: Snapshot) -> list[Incident]:
        cfg = self.config.condition
        ctype = cfg.get("node_condition", "DiskPressure")
        wanted_status = str(cfg.get("status", "True"))
        min_usage = cfg.get("min_disk_usage_pct")   # опционально
        now = self._now()

        incidents: list[Incident] = []
        for node in _iter_all_nodes(snapshot):
            status, last_transition = _node_condition(node, ctype)
            if status != wanted_status:
                continue

            # если правило требует min_usage, а у peer-ноды нет метрики — пропускаем,
            # но не падаем: DiskPressure уже сам по себе инцидент
            if min_usage is not None and node.disk_usage_pct is not None:
                if node.disk_usage_pct < float(min_usage):
                    continue

            evidence = {
                "node": node.name,
                "condition": ctype,
                "status": wanted_status,
            }
            # disk_usage_pct есть только у self_node (SSH), у peer — None.
            # Включаем, только если есть — иначе evidence будет разным у self/peer
            # и дедуп не сработает. Поэтому НЕ включаем в evidence.
            if last_transition is not None:
                evidence["last_transition"] = last_transition.isoformat()
            if node.role:
                evidence["role"] = node.role

            incidents.append(self._make_incident(
                snapshot=snapshot,
                target=node.name,
                evidence=evidence,
                detected_at=now,
            ))
        return incidents

    # ---------- pod_crashloop ----------

    def _eval_pod_crashloop(self, snapshot: Snapshot) -> list[Incident]:
        cfg = self.config.condition
        restarts_gt = int(cfg.get("pod_restarts_gt", 5))
        window_sec = int(cfg.get("window_sec", DEFAULT_WINDOW_SEC))
        now = self._now()

        incidents: list[Incident] = []
        for pod in snapshot.pods:
            if pod.restarts <= restarts_gt:
                continue
            # окно: если есть last_restart_at — фильтруем старые рестарты
            if pod.last_restart_at is not None:
                age_sec = (now - pod.last_restart_at).total_seconds()
                if age_sec > window_sec:
                    continue
            else:
                # без timestamp не можем применить окно —
                # для MVP считаем инцидентом (лучше ложный, чем пропуск)
                age_sec = None

            evidence = {
                "namespace": pod.namespace,
                "pod": pod.name,
                "node": pod.node,
                "restarts": pod.restarts,
                "last_terminated_reason": pod.last_terminated_reason,
                "owner_kind": pod.owner_kind,
                "owner_name": pod.owner_name,
            }
            if pod.last_restart_at is not None:
                evidence["last_restart_at"] = pod.last_restart_at.isoformat()
                evidence["age_sec"] = int(age_sec) if age_sec is not None else None

            incidents.append(self._make_incident(
                snapshot=snapshot,
                target=_pod_target(pod),
                evidence=evidence,
                detected_at=now,
            ))
        return incidents

    # ---------- pod_oomkilled ----------

    def _eval_pod_oomkilled(self, snapshot: Snapshot) -> list[Incident]:
        cfg = self.config.condition
        wanted_reason = str(cfg.get("last_terminated_reason", "OOMKilled"))
        now = self._now()

        incidents: list[Incident] = []
        for pod in snapshot.pods:
            if pod.last_terminated_reason != wanted_reason:
                continue

            evidence = {
                "namespace": pod.namespace,
                "pod": pod.name,
                "node": pod.node,
                "last_terminated_reason": pod.last_terminated_reason,
                "owner_kind": pod.owner_kind,
                "owner_name": pod.owner_name,
                "mem_limit_mb": pod.mem_limit_mb,
            }
            # exit_code контейнера с OOMKilled — из containers[]
            for c in pod.containers:
                if c.reason == wanted_reason:
                    evidence["container"] = c.name
                    evidence["exit_code"] = c.exit_code
                    evidence["image"] = c.image
                    break
            if pod.last_restart_at is not None:
                evidence["last_restart_at"] = pod.last_restart_at.isoformat()

            incidents.append(self._make_incident(
                snapshot=snapshot,
                target=_pod_target(pod),
                evidence=evidence,
                detected_at=now,
            ))
        return incidents

    # ---------- helpers ----------

    def _make_incident(
        self,
        snapshot: Snapshot,
        target: str,
        evidence: dict[str, Any],
        detected_at: datetime,
    ) -> Incident:
        return Incident(
            id=_incident_id(self.incident_type, target, evidence),
            type=self.incident_type,
            target=target,
            severity=self.severity,
            priority=self.priority,
            evidence=evidence,
            detected_at=detected_at,
            cluster_id=snapshot.cluster_id,
            rule_id=self.rule_id,
            rule_version=self.version,
            scenario_version=self.config.scenario_version,
        )