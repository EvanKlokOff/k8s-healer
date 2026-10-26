# healer/scout/metrics.py
"""Prometheus-метрики скаута."""
from prometheus_client import Counter, Gauge, Histogram

snapshots_sent_total = Counter(
    "scout_snapshots_sent_total", "Snapshots published to core",
    ["status", "node", "cluster"],
)
snapshot_duration_seconds = Histogram(
    "scout_snapshot_duration_seconds", "End-to-end collect+publish duration",
    ["node"],
)
collect_errors_total = Counter(
    "scout_collect_errors_total", "Collector errors", ["collector", "node"]
)
last_success_timestamp = Gauge(
    "scout_last_success_timestamp_seconds",
    "Unix timestamp of the last successful publish",
    ["node"],
)