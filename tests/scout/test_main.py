# tests/scout/test_main.py
"""main: _build_snapshot, обработка ошибок, отсутствие NODE_NAME, shutdown."""
from __future__ import annotations

import os
import signal
import threading
from unittest.mock import MagicMock, patch

import pytest

from healer.scout import main as scout_main


@pytest.fixture
def fake_k8s(minimal_snapshot):
    k = MagicMock()
    k.node_name = "k8s-worker-1"
    k.collect.return_value = minimal_snapshot
    return k


@pytest.fixture
def fake_host():
    h = MagicMock()
    h.merge_into.side_effect = lambda s: s
    return h


def test_build_snapshot_ok(fake_k8s, fake_host):
    snap = scout_main._build_snapshot(fake_k8s, fake_host)
    assert snap is not None
    assert snap.scout_node == "k8s-worker-1"
    fake_host.merge_into.assert_called_once()


def test_build_snapshot_validation_error(fake_k8s, fake_host):
    bad = MagicMock()
    bad.model_dump.return_value = {"broken": True}
    fake_host.merge_into.side_effect = None          # <-- сбросить side_effect
    fake_host.merge_into.return_value = bad
    assert scout_main._build_snapshot(fake_k8s, fake_host) is None


def test_build_snapshot_collect_exception(fake_k8s, fake_host):
    fake_k8s.collect.side_effect = Exception("boom")
    assert scout_main._build_snapshot(fake_k8s, fake_host) is None


def test_build_snapshot_increments_collect_errors(fake_k8s, fake_host, minimal_snapshot):
    from datetime import datetime, timezone
    from healer.core.schemas import CollectorError
    from healer.scout import metrics

    minimal_snapshot.agent.errors = [CollectorError(
        collector="test_x", message="m",
        occurred_at=datetime.now(timezone.utc),
    )]
    fake_k8s.collect.return_value = minimal_snapshot
    fake_k8s.node_name = "k8s-worker-1"

    before = metrics.collect_errors_total.labels(
        collector="test_x", node="k8s-worker-1",
    )._value.get()
    snap = scout_main._build_snapshot(fake_k8s, fake_host)
    after = metrics.collect_errors_total.labels(
        collector="test_x", node="k8s-worker-1",
    )._value.get()

    assert snap is not None
    assert after == before + 1

def test_main_exits_without_node_name(monkeypatch):
    monkeypatch.delenv("NODE_NAME", raising=False)
    monkeypatch.setenv("METRICS_PORT", "0")
    # если NODE_NAME нет — K8sApiScout бросит RuntimeError → SystemExit
    with patch("healer.scout.main.K8sApiScout") as cls:
        cls.side_effect = RuntimeError("NODE_NAME env var is required")
        with pytest.raises(SystemExit) as exc:
            scout_main.main()
        assert exc.value.code == 1


def test_main_metrics_port_zero_skips_server(monkeypatch):
    monkeypatch.setenv("METRICS_PORT", "0")
    monkeypatch.setenv("NODE_NAME", "k8s-worker-1")
    with patch("healer.scout.main.start_http_server") as srv, \
         patch("healer.scout.main.K8sApiScout") as k8s_cls, \
         patch("healer.scout.main.HostMetricsScout"), \
         patch("healer.scout.main.Publisher"):
        k8s_cls.return_value.node_name = "k8s-worker-1"
        # остановим цикл сразу, чтобы main завершился
        scout_main._stop.set()
        try:
            scout_main.main()
        finally:
            scout_main._stop.clear()
        srv.assert_not_called()


def test_main_loop_publishes_and_stops(monkeypatch, minimal_snapshot, fake_k8s, fake_host):
    monkeypatch.setenv("METRICS_PORT", "0")
    monkeypatch.setenv("NODE_NAME", "k8s-worker-1")
    monkeypatch.setenv("INTERVAL_SEC", "0")

    pub = MagicMock()
    pub.publish.return_value = True
    pub.core_url = "http://127.0.0.1:8080"

    with patch("healer.scout.main.start_http_server"), \
         patch("healer.scout.main.K8sApiScout", return_value=fake_k8s), \
         patch("healer.scout.main.HostMetricsScout", return_value=fake_host), \
         patch("healer.scout.main.Publisher", return_value=pub):
        # остановим после первого цикла
        def stop_after():
            scout_main._stop.set()
            return minimal_snapshot
        fake_k8s.collect.side_effect = stop_after
        try:
            scout_main.main()
        finally:
            scout_main._stop.clear()
        assert pub.publish.called
        pub.close.assert_called_once()


def test_signal_handler_sets_stop():
    scout_main._stop.clear()
    scout_main._handle_signal(signal.SIGTERM, None)
    assert scout_main._stop.is_set()
    scout_main._stop.clear()