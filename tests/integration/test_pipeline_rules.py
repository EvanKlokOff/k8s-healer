"""Интеграция: Snapshot → Pipeline._detect → incidents."""
from __future__ import annotations

from pathlib import Path

import pytest

from healer.core.rules.loader import load_rules
from tests.core.rules.conftest import make_node, make_pod, make_snapshot


@pytest.fixture
def rules():
    rules_dir = Path(__file__).resolve().parents[2] / "healer" / "rules"
    return load_rules(rules_dir)


def _detect(rules, snapshot):
    out = []
    for r in rules:
        out.extend(r.evaluate(snapshot))
    return out


def test_detect_not_ready_and_oom(rules):
    node = make_node("k8s-worker-1", ready=False)
    pod = make_pod("web-abc", last_terminated_reason="OOMKilled")
    snap = make_snapshot(node, pods=[pod])
    incidents = _detect(rules, snap)
    types = {i.type for i in incidents}
    assert "node_not_ready" in types
    assert "pod_oomkilled" in types


def test_healthy_snapshot_no_incidents(rules):
    snap = make_snapshot(make_node("k8s-worker-1"))
    assert _detect(rules, snap) == []