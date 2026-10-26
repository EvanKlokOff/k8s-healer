# tests/scout/test_k8s_api_scout.py
"""K8sApiScout: сбор self_node/peer_nodes/pods/events без реального кластера."""
from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest
from kubernetes.client.exceptions import ApiException

from healer.scout.collectors.k8s_api_scout import K8sApiScout


@pytest.fixture
def fake_core():
    return MagicMock()


@pytest.fixture
def scout(monkeypatch, fake_core):
    monkeypatch.setenv("NODE_NAME", "k8s-worker-1")
    with patch("healer.scout.collectors.k8s_api_scout.settings") as s, \
         patch("healer.scout.collectors.k8s_api_scout.config") as cfg, \
         patch("healer.scout.collectors.k8s_api_scout.client") as cli:
        s.kubeconfig_path = "/etc/healer/kubeconfig"
        s.cluster_id = "k8s-dev-1"
        cfg.load_kube_config = MagicMock()
        cli.CoreV1Api.return_value = fake_core
        yield K8sApiScout()


def _wire(scout, nodes, pods, node_events, pod_events):
    scout.core.read_node.return_value = nodes[0]
    scout.core.list_node.return_value.items = nodes
    scout.core.list_pod_for_all_namespaces.return_value.items = pods
    scout.core.list_event_for_all_namespaces.return_value.items = node_events
    scout.core.list_namespaced_event.return_value.items = pod_events


def test_requires_node_name(monkeypatch):
    monkeypatch.delenv("NODE_NAME", raising=False)
    with patch("healer.scout.collectors.k8s_api_scout.config"), \
         patch("healer.scout.collectors.k8s_api_scout.client"):
        with pytest.raises(RuntimeError, match="NODE_NAME"):
            K8sApiScout()


def test_loads_kubeconfig_from_settings(scout):
    from healer.scout.collectors import k8s_api_scout as m
    m.config.load_kube_config.assert_called_once_with(
        config_file="/etc/healer/kubeconfig",
    )


def test_collect_self_node_with_healer_ip(
    scout, fake_node, fake_worker2, fake_pod, fake_node_event,
):
    _wire(scout, [fake_node, fake_worker2], [fake_pod], [fake_node_event], [])
    snap = scout.collect()

    assert snap.scout_node == "k8s-worker-1"
    assert snap.cluster_id == "k8s-dev-1"
    assert snap.self_node.name == "k8s-worker-1"
    assert snap.self_node.labels["healer/ip"] == "192.168.122.11"
    assert snap.self_node.conditions_index["Ready"] == "True"
    assert snap.self_node.resources.cpu_capacity == 2.0
    assert snap.self_node.resources.mem_capacity_mb == 4096


def test_peer_nodes_keep_conditions_and_ip(
    scout, fake_node, fake_worker2, fake_pod,
):
    _wire(scout, [fake_node, fake_worker2], [fake_pod], [], [])
    snap = scout.collect()

    assert len(snap.peer_nodes) == 1
    peer = snap.peer_nodes[0]
    assert peer.name == "k8s-worker-2"
    assert peer.ready is False
    assert peer.conditions_index["DiskPressure"] == "True"
    # last_transition сохраняется — нужно правилу node_not_ready(duration_sec)
    assert peer.conditions[0].last_transition is not None
    assert peer.labels["healer/ip"] == "192.168.122.12"


def test_pods_filtered_by_self_node(scout, fake_node, fake_pod):
    _wire(scout, [fake_node], [fake_pod], [], [])
    snap = scout.collect()
    scout.core.list_pod_for_all_namespaces.assert_called_once_with(
        field_selector="spec.nodeName=k8s-worker-1",
    )
    assert len(snap.pods) == 1
    assert snap.pods[0].name == "web-7d9f8b-abc12"


def test_crashloop_pod_fields(scout, fake_node, fake_crashloop_pod):
    _wire(scout, [fake_node], [fake_crashloop_pod], [], [])
    snap = scout.collect()
    pod = snap.pods[0]
    assert pod.restarts == 6
    assert pod.last_terminated_reason == "CrashLoopBackOff"
    assert pod.containers[0].state == "waiting"
    assert pod.containers[0].reason == "CrashLoopBackOff"


def test_oomkilled_pod_fields(scout, fake_node, fake_oom_pod):
    _wire(scout, [fake_node], [fake_oom_pod], [], [])
    snap = scout.collect()
    pod = snap.pods[0]
    assert pod.last_terminated_reason == "OOMKilled"
    assert pod.containers[0].exit_code == 137
    assert pod.last_restart_at is not None                    # <-- новый assert
    assert pod.last_restart_at.tzinfo is not None             # UTC, aware

def test_crashloop_pod_has_last_restart_at(scout, fake_node):
    from tests.scout.conftest import make_pod, make_container_status, NOW
    from datetime import timedelta

    earlier = NOW - timedelta(minutes=5)
    pod = make_pod(
        "web-7d9f8b-abc12",
        restart_count=6,
        last_reason="CrashLoopBackOff",
        last_finished_at=earlier,
    )
    _wire(scout, [fake_node], [pod], [], [])
    snap = scout.collect()
    p = snap.pods[0]
    assert p.restarts == 6
    assert p.last_terminated_reason == "CrashLoopBackOff"
    assert p.last_restart_at == earlier

def test_healthy_pod_has_no_last_restart_at(scout, fake_node):
    from tests.scout.conftest import make_pod

    pod = make_pod("web-7d9f8b-abc12")   # running, restart_count=0, no last_reason
    _wire(scout, [fake_node], [pod], [], [])
    snap = scout.collect()
    assert snap.pods[0].last_restart_at is None

def test_events_from_node_and_pods(
    scout, fake_node, fake_pod, fake_node_event, fake_pod_event,
):
    scout.core.read_node.return_value = fake_node
    scout.core.list_node.return_value.items = []
    scout.core.list_pod_for_all_namespaces.return_value.items = [fake_pod]

    def _events(field_selector: str):
        if "involvedObject.kind=Node" in field_selector:
            return MagicMock(items=[fake_node_event])
        if "involvedObject.kind=Pod" in field_selector:
            return MagicMock(items=[fake_pod_event])
        return MagicMock(items=[])

    scout.core.list_event_for_all_namespaces.side_effect = _events

    snap = scout.collect()
    reasons = {e.reason for e in snap.events}
    assert "NodeNotReady" in reasons
    assert "BackOff" in reasons
    assert len(snap.events) == 2

def test_events_filtered_by_pod_namespace(scout, fake_node):
    from tests.scout.conftest import make_pod, make_event
    pod_ns1 = make_pod("app-1", namespace="prod", node="k8s-worker-1")
    pod_ns2 = make_pod("app-2", namespace="staging", node="k8s-worker-1")
    ev_prod = make_event("BackOff", "Pod", "app-1", namespace="prod")
    ev_other = make_event("BackOff", "Pod", "app-999", namespace="prod")  # чужой под

    scout.core.read_node.return_value = fake_node
    scout.core.list_node.return_value.items = []
    scout.core.list_pod_for_all_namespaces.return_value.items = [pod_ns1, pod_ns2]

    def _events(field_selector: str):
        if "involvedObject.kind=Node" in field_selector:
            return MagicMock(items=[])
        return MagicMock(items=[ev_prod, ev_other])

    scout.core.list_event_for_all_namespaces.side_effect = _events
    snap = scout.collect()
    names = {e.involved_name for e in snap.events}
    assert "app-1" in names
    assert "app-999" not in names   # чужой под отфильтрован

def test_read_node_api_error_falls_back(scout, fake_node):
    scout.core.read_node.side_effect = ApiException(status=500, reason="boom")
    scout.core.list_node.return_value.items = []
    scout.core.list_pod_for_all_namespaces.return_value.items = []
    scout.core.list_event_for_all_namespaces.return_value.items = []
    snap = scout.collect()
    assert snap.self_node.name == "k8s-worker-1"
    assert snap.self_node.ready is False
    assert any(e.collector == "k8s_api.read_node" for e in snap.agent.errors)


def test_list_node_error_recorded(scout, fake_node):
    scout.core.read_node.return_value = fake_node
    scout.core.list_node.side_effect = Exception("api down")
    scout.core.list_pod_for_all_namespaces.return_value.items = []
    scout.core.list_event_for_all_namespaces.return_value.items = []
    snap = scout.collect()
    assert snap.peer_nodes == []
    assert any(e.collector == "k8s_api.list_node" for e in snap.agent.errors)


def test_list_pods_error_recorded(scout, fake_node):
    scout.core.read_node.return_value = fake_node
    scout.core.list_node.return_value.items = []
    scout.core.list_pod_for_all_namespaces.side_effect = Exception("boom")
    scout.core.list_event_for_all_namespaces.return_value.items = []
    snap = scout.collect()
    assert snap.pods == []
    assert any("list_pods" in e.collector for e in snap.agent.errors)


def test_snapshot_validates_against_schema(scout, fake_node, fake_pod):
    _wire(scout, [fake_node], [fake_pod], [], [])
    snap = scout.collect()
    # повторная валидация — гарантия контракта
    from healer.core.schemas import Snapshot
    Snapshot.model_validate(snap.model_dump(mode="python"))


@pytest.mark.parametrize("raw,expected", [
    ("100m", 0.1),
    ("1", 1.0),
    ("0", 0.0),
    (None, None),
    ("garbage", None),
])
def test_parse_cpu(scout, raw, expected):
    assert K8sApiScout._parse_cpu(raw) == expected


@pytest.mark.parametrize("raw,expected", [
    ("512Mi", 512),
    ("1Gi", 1024),
    ("4Gi", 4096),
    ("1024Ki", 1),
    (None, None),
])
def test_parse_mem_mb(scout, raw, expected):
    assert K8sApiScout._parse_mem_mb(raw) == expected