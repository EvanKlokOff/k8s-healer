# tests/scout/test_host_metrics.py
"""HostMetricsScout: SSH-парсинг и merge в Snapshot."""
from __future__ import annotations

import subprocess
from unittest.mock import MagicMock, patch

import pytest

from healer.scout.collectors.host_metrics import HostMetricsScout


@pytest.fixture
def scout():
    with patch("healer.scout.collectors.host_metrics.settings") as s:
        s.ssh_user = "debian"
        s.ssh_key_path = "/etc/healer/ssh/k8s_debian"
        s.ssh_connect_timeout_sec = 5
        yield HostMetricsScout()


def test_merge_into_parses_healthy_ssh(scout, minimal_snapshot, ssh_output_healthy):
    with patch("subprocess.run") as run:
        run.return_value = MagicMock(
            returncode=0, stdout=ssh_output_healthy, stderr="",
        )
        out = scout.merge_into(minimal_snapshot)

    node = out.self_node
    assert node.load_1m == 0.8
    assert node.load_5m == 0.6
    assert node.load_15m == 0.5
    assert node.cpu_usage_pct == pytest.approx(100 * 12 / 512, rel=1e-2)   # 2.34
    assert node.uptime_sec == 86400
    assert node.mem_usage_pct == pytest.approx(25.0)
    assert node.disk_usage_pct == pytest.approx(45.0)
    assert node.disk_inodes_pct == pytest.approx(8.0)
    assert node.kubelet_up is True
    assert node.containerd_up is True
    assert node.kube_proxy_up is True


def test_merge_into_kubelet_down(scout, minimal_snapshot, ssh_output_kubelet_down):
    with patch("subprocess.run") as run:
        run.return_value = MagicMock(
            returncode=0, stdout=ssh_output_kubelet_down, stderr="",
        )
        out = scout.merge_into(minimal_snapshot)

    assert out.self_node.kubelet_up is False
    assert out.self_node.containerd_up is True
    assert out.self_node.kube_proxy_up is None  # "unknown" → None


def test_merge_into_ssh_failure_keeps_fields(scout, minimal_snapshot):
    with patch("subprocess.run") as run:
        run.return_value = MagicMock(
            returncode=255, stdout="", stderr="Permission denied",
        )
        out = scout.merge_into(minimal_snapshot)

    # SSH упал — поля не затёрты
    node = out.self_node
    assert node.cpu_usage_pct is None
    assert node.kubelet_up is None


def test_merge_into_no_ip_falls_back_to_name(scout, minimal_snapshot):
    minimal_snapshot.self_node.labels.pop("healer/ip")
    with patch("subprocess.run") as run:
        run.return_value = MagicMock(returncode=0, stdout="", stderr="")
        scout.merge_into(minimal_snapshot)
        cmd = run.call_args.args[0]
        assert "debian@k8s-worker-1" in cmd


def test_merge_into_uses_healer_ip(scout, minimal_snapshot, ssh_output_healthy):
    with patch("subprocess.run") as run:
        run.return_value = MagicMock(
            returncode=0, stdout=ssh_output_healthy, stderr="",
        )
        scout.merge_into(minimal_snapshot)
        cmd = run.call_args.args[0]
        assert "debian@192.168.122.11" in cmd


def test_merge_into_short_output_returns_unchanged(scout, minimal_snapshot):
    with patch("subprocess.run") as run:
        run.return_value = MagicMock(returncode=0, stdout="garbage\n", stderr="")
        out = scout.merge_into(minimal_snapshot)
    assert out.self_node.cpu_usage_pct is None
    assert out.self_node.load_1m is None


def test_merge_into_ssh_timeout(scout, minimal_snapshot):
    with patch("subprocess.run", side_effect=subprocess.TimeoutExpired("ssh", 15)):
        out = scout.merge_into(minimal_snapshot)
    assert out.self_node.cpu_usage_pct is None


def test_ssh_cmd_includes_safety_opts(scout, minimal_snapshot, ssh_output_healthy):
    with patch("subprocess.run") as run:
        run.return_value = MagicMock(returncode=0, stdout=ssh_output_healthy)
        scout.merge_into(minimal_snapshot)
    cmd = run.call_args.args[0]
    assert "-o" in cmd
    assert "BatchMode=yes" in cmd
    assert "StrictHostKeyChecking=no" in cmd
    assert "ConnectTimeout=5" in cmd


def test_collect_raises(scout):
    with pytest.raises(NotImplementedError):
        scout.collect()