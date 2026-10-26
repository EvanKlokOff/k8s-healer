# tests/scout/test_publisher.py
"""Publisher: retry, статусы, метрики. Без реального core (respx)."""
from __future__ import annotations

import httpx
import pytest
import respx

from healer.scout import metrics
from healer.scout.publisher import Publisher


@pytest.fixture
def publisher():
    p = Publisher("http://core.test:8080")
    yield p
    p.close()


def _counter_value(node: str, status: str) -> float:
    return metrics.snapshots_sent_total.labels(
        status=status, node=node, cluster="k8s-dev-1",
    )._value.get()


def test_publish_ok(publisher, minimal_snapshot):
    with respx.mock(assert_all_called=True) as mock:
        route = mock.post("http://core.test:8080/snapshot").mock(
            return_value=httpx.Response(200, json={"incidents": 2}),
        )
        assert publisher.publish(minimal_snapshot) is True
        assert route.called
        assert _counter_value("k8s-worker-1", "ok") >= 1


def test_publish_4xx_no_retry(publisher, minimal_snapshot):
    with respx.mock(assert_all_called=True) as mock:
        route = mock.post("http://core.test:8080/snapshot").mock(
            return_value=httpx.Response(422, text="schema mismatch"),
        )
        assert publisher.publish(minimal_snapshot) is False
        assert route.call_count == 1  # без retry
        assert _counter_value("k8s-worker-1", "rejected") >= 1


def test_publish_5xx_retries(publisher, minimal_snapshot, monkeypatch):
    monkeypatch.setattr(
        "healer.scout.publisher.RETRY_DELAYS", (0.0, 0.0, 0.0),
    )
    with respx.mock(assert_all_called=True) as mock:
        route = mock.post("http://core.test:8080/snapshot").mock(
            return_value=httpx.Response(503),
        )
        assert publisher.publish(minimal_snapshot) is False
        assert route.call_count == 4  # 1 + 3 retry
        assert _counter_value("k8s-worker-1", "failed") >= 1


def test_publish_transport_error_retries(publisher, minimal_snapshot, monkeypatch):
    monkeypatch.setattr(
        "healer.scout.publisher.RETRY_DELAYS", (0.0, 0.0, 0.0),
    )
    with respx.mock(assert_all_called=True) as mock:
        route = mock.post("http://core.test:8080/snapshot").mock(
            side_effect=httpx.ConnectError("refused"),
        )
        assert publisher.publish(minimal_snapshot) is False
        assert route.call_count == 4


def test_publish_timeout_retries(publisher, minimal_snapshot, monkeypatch):
    monkeypatch.setattr(
        "healer.scout.publisher.RETRY_DELAYS", (0.0, 0.0, 0.0),
    )
    with respx.mock(assert_all_called=True) as mock:
        route = mock.post("http://core.test:8080/snapshot").mock(
            side_effect=httpx.ReadTimeout("slow"),
        )
        assert publisher.publish(minimal_snapshot) is False
        assert route.call_count == 4


def test_publish_5xx_then_ok(publisher, minimal_snapshot, monkeypatch):
    monkeypatch.setattr(
        "healer.scout.publisher.RETRY_DELAYS", (0.0, 0.0, 0.0),
    )
    with respx.mock(assert_all_called=True) as mock:
        route = mock.post("http://core.test:8080/snapshot").mock(
            side_effect=[httpx.Response(503), httpx.Response(200, json={})],
        )
        assert publisher.publish(minimal_snapshot) is True
        assert route.call_count == 2


def test_publish_non_json_response_ok(publisher, minimal_snapshot):
    with respx.mock(assert_all_called=True) as mock:
        mock.post("http://core.test:8080/snapshot").mock(
            return_value=httpx.Response(200, text="OK"),
        )
        # не падаем на resp.json()
        assert publisher.publish(minimal_snapshot) is True