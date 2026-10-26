# healer/scout/prometheus.py
"""Prometheus-scraper — roadmap, не входит в MVP.

Позже: pull метрик с node-exporter/cAdvisor, дополнять Snapshot.metrics.
"""
from __future__ import annotations

from healer.core.schemas import Snapshot
from healer.scout.collectors.base import Scout


class PrometheusScout(Scout):
    def collect(self) -> Snapshot:  # pragma: no cover
        raise NotImplementedError("PrometheusScout is on the roadmap")