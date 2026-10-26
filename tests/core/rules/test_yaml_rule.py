"""Тесты YamlRule: 4 условия + нормализация evidence."""
from __future__ import annotations

from datetime import timedelta

import pytest

from healer.core.rules.base import RuleConfig
from healer.core.rules.yaml_rule import YamlRule
from healer.core.schemas import ContainerState, NodeCondition
from tests.core.rules.conftest import (
    NOW, make_node, make_pod, make_snapshot,
)


# ---------- node_not_ready ----------

CFG_NR = RuleConfig(
    id="node_not_ready", incident_type="node_not_ready",
    priority=200, severity="high",
    condition={"node_condition": "Ready", "status": "False", "duration_sec": 300},
)

def _rule(cfg):
    return YamlRule(cfg, now_fn=lambda: NOW)

def test_node_not_ready_self(not_ready_self_snapshot):
    rule = _rule(CFG_NR)
    incidents = rule.evaluate(not_ready_self_snapshot)
    assert len(incidents) == 1
    inc = incidents[0]
    assert inc.type == "node_not_ready"
    assert inc.target == "k8s-worker-1"
    assert inc.severity == "high"
    assert inc.priority == 200
    assert inc.evidence["condition"] == "Ready"
    assert inc.evidence["status"] == "False"
    assert inc.evidence["age_sec"] >= 300


def test_node_not_ready_peer(not_ready_peer_snapshot):
    rule = _rule(CFG_NR)
    incidents = rule.evaluate(not_ready_peer_snapshot)
    assert len(incidents) == 1
    assert incidents[0].target == "k8s-worker-1"


def test_node_not_ready_evidence_normalized_self_and_peer(
    not_ready_self_snapshot, not_ready_peer_snapshot,
):
    """Ключевой тест: evidence одинаков для self и peer → дедуп сработает."""
    rule = _rule(CFG_NR)
    self_inc = rule.evaluate(not_ready_self_snapshot)[0]
    peer_inc = rule.evaluate(not_ready_peer_snapshot)[0]
    assert self_inc.id == peer_inc.id                # <-- одинаковый incident id
    assert self_inc.target == peer_inc.target
    assert self_inc.evidence.keys() == peer_inc.evidence.keys()


def test_node_not_ready_skips_below_duration():
    from datetime import datetime, timezone
    now = datetime.now(timezone.utc)
    node = make_node("k8s-worker-1", ready=False, conditions=[
        NodeCondition(type="Ready", status="False",
                      last_transition=now - timedelta(seconds=60)),
    ])
    inc = _rule(CFG_NR).evaluate(make_snapshot(node))
    assert inc == []


def test_node_not_ready_skips_ready():
    node = make_node("k8s-worker-1", ready=True)
    inc = _rule(CFG_NR).evaluate(make_snapshot(node))
    assert inc == []


def test_node_not_ready_no_transition_skips():
    """Без last_transition не можем посчитать duration — пропускаем."""
    node = make_node("k8s-worker-1", ready=False, conditions=[
        NodeCondition(type="Ready", status="False", last_transition=None),
    ])
    inc = _rule(CFG_NR).evaluate(make_snapshot(node))
    assert inc == []


# ---------- node_disk_pressure ----------

CFG_DP = RuleConfig(
    id="node_disk_pressure", incident_type="node_disk_pressure",
    priority=180, severity="high",
    condition={"node_condition": "DiskPressure", "status": "True"},
)


def test_disk_pressure_self():
    node = make_node("k8s-worker-1", conditions=[
        NodeCondition(type="Ready", status="True", last_transition=NOW),
        NodeCondition(type="DiskPressure", status="True", last_transition=NOW),
    ])
    inc = _rule(CFG_DP).evaluate(make_snapshot(node))
    assert len(inc) == 1
    assert inc[0].target == "k8s-worker-1"
    assert inc[0].evidence["condition"] == "DiskPressure"


def test_disk_pressure_skips_when_false():
    node = make_node("k8s-worker-1", conditions=[
        NodeCondition(type="Ready", status="True", last_transition=NOW),
        NodeCondition(type="DiskPressure", status="False", last_transition=NOW),
    ])
    assert _rule(CFG_DP).evaluate(make_snapshot(node)) == []


# ---------- pod_crashloop ----------

CFG_CL = RuleConfig(
    id="pod_crashloop", incident_type="pod_crashloop",
    priority=150, severity="medium",
    condition={"pod_restarts_gt": 5, "window_sec": 600},
)


def test_crashloop_detected():
    pod = make_pod("web-abc", restarts=6,
                   last_terminated_reason="CrashLoopBackOff",
                   last_restart_at=NOW - timedelta(minutes=2))
    inc = _rule(CFG_CL).evaluate(make_snapshot(make_node("n"), pods=[pod]))
    assert len(inc) == 1
    assert inc[0].target == "default/web-abc"
    assert inc[0].evidence["restarts"] == 6


def test_crashloop_skips_below_threshold():
    pod = make_pod("web-abc", restarts=3,
                   last_restart_at=NOW - timedelta(minutes=2))
    assert _rule(CFG_CL).evaluate(make_snapshot(make_node("n"), pods=[pod])) == []


def test_crashloop_skips_old_restarts():
    """last_restart_at старше window_sec → не инцидент."""
    pod = make_pod("web-abc", restarts=10,
                   last_terminated_reason="CrashLoopBackOff",
                   last_restart_at=NOW - timedelta(minutes=30))
    assert _rule(CFG_CL).evaluate(make_snapshot(make_node("n"), pods=[pod])) == []


def test_crashloop_without_timestamp_triggers():
    """Без timestamp — срабатываем (лучше ложный, чем пропуск)."""
    pod = make_pod("web-abc", restarts=10,
                   last_terminated_reason="CrashLoopBackOff",
                   last_restart_at=None)
    inc = _rule(CFG_CL).evaluate(make_snapshot(make_node("n"), pods=[pod]))
    assert len(inc) == 1


# ---------- pod_oomkilled ----------

CFG_OOM = RuleConfig(
    id="pod_oomkilled", incident_type="pod_oomkilled",
    priority=160, severity="medium",
    condition={"last_terminated_reason": "OOMKilled"},
)


def test_oomkilled_detected():
    pod = make_pod(
        "web-abc", last_terminated_reason="OOMKilled",
        containers=[ContainerState(
            name="app", ready=False, restart_count=1,
            state="running", reason="OOMKilled", exit_code=137,
            image="nginx:1.25",
        )],
    )
    inc = _rule(CFG_OOM).evaluate(make_snapshot(make_node("n"), pods=[pod]))
    assert len(inc) == 1
    assert inc[0].evidence["container"] == "app"
    assert inc[0].evidence["exit_code"] == 137


def test_oomkilled_skips_other_reason():
    pod = make_pod("web-abc", last_terminated_reason="Error")
    assert _rule(CFG_OOM).evaluate(make_snapshot(make_node("n"), pods=[pod])) == []


# ---------- helpers ----------

def test_disabled_rule_returns_empty():
    cfg = RuleConfig(
        id="x", incident_type="node_not_ready", enabled=False,
        condition={"node_condition": "Ready", "status": "False", "duration_sec": 0},
    )
    node = make_node("n", ready=False)
    assert _rule(cfg).evaluate(make_snapshot(node)) == []


def test_unknown_incident_type_returns_empty():
    cfg = RuleConfig(id="x", incident_type="unknown_type", condition={})
    assert _rule(cfg).evaluate(make_snapshot(make_node("n"))) == []