# healer/scout/main.py
"""Точка входа out-of-cluster скаута.

Один инстанс на ноду кластера (NODE_NAME), N инстансов на хосте healer.
Цикл: collect → merge host metrics → validate → publish.
Graceful shutdown по SIGTERM/SIGINT. Prometheus на :METRICS_PORT (0 = off).
"""
from __future__ import annotations

import logging
import os
import signal
import threading
import time
from datetime import datetime, timezone

from prometheus_client import start_http_server
from pydantic import ValidationError

from healer.core.config import settings
from healer.core.schemas import Snapshot
from healer.scout import metrics
from healer.scout.collectors.host_metrics import HostMetricsScout
from healer.scout.collectors.k8s_api_scout import K8sApiScout
from healer.scout.publisher import Publisher

log = logging.getLogger(__name__)

_stop = threading.Event()


def _handle_signal(signum, _frame):
    log.info("received signal %s, shutting down", signum)
    _stop.set()


def _build_snapshot(k8s: K8sApiScout, host: HostMetricsScout) -> Snapshot | None:
    started = time.monotonic()
    node_label = getattr(k8s, "node_name", "unknown")
    try:
        snap = k8s.collect()
        snap = host.merge_into(snap)
        # финальная валидация — ловит расхождения до отправки в core
        snap = Snapshot.model_validate(snap.model_dump(mode="python"))
    except ValidationError:
        log.exception("snapshot failed schema validation, skipping cycle")
        metrics.collect_errors_total.labels(collector="schema", node=node_label).inc()
        return None
    except Exception:
        log.exception("snapshot build failed")
        metrics.collect_errors_total.labels(collector="build",node=node_label).inc()
        return None
    finally:
        metrics.snapshot_duration_seconds.labels(node=node_label).observe(time.monotonic() - started)

    for err in snap.agent.errors:
        metrics.collect_errors_total.labels(collector=err.collector, node=node_label).inc()
    return snap


def main() -> None:
    logging.basicConfig(
        level=os.getenv("LOG_LEVEL", "INFO"),
        format="%(asctime)s %(levelname)s %(name)s [%(process)d] %(message)s",
    )

    signal.signal(signal.SIGTERM, _handle_signal)
    signal.signal(signal.SIGINT, _handle_signal)

    # METRICS_PORT=0 — не поднимать сервер (для 2+ инстансов на одном хосте)
    metrics_port = int(os.getenv("METRICS_PORT", "0"))
    if metrics_port > 0:
        try:
            start_http_server(metrics_port)
            log.info("metrics on :%d", metrics_port)
        except OSError:
            log.exception("failed to start metrics server on :%d (continuing)", metrics_port)

    try:
        k8s = K8sApiScout()
    except RuntimeError as exc:
        log.error("scout init failed: %s", exc)
        raise SystemExit(1)

    host = HostMetricsScout()
    publisher = Publisher(
        os.getenv("CORE_URL", "http://127.0.0.1:8080"),
    )
    interval = int(os.getenv("INTERVAL_SEC", "30"))

    log.info(
        "scout started: node=%s cluster=%s core=%s interval=%ds pid=%d",
        k8s.node_name, settings.cluster_id, publisher.core_url, interval, os.getpid(),
    )

    try:
        while not _stop.is_set():
            snap = _build_snapshot(k8s, host)
            if snap is not None:
                metrics.last_success_timestamp.labels(node=k8s.node_name).set_to_current_time()
                publisher.publish(snap)
            _stop.wait(interval)
    finally:
        publisher.close()
        log.info("scout stopped: node=%s", k8s.node_name)


if __name__ == "__main__":
    main()