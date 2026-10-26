from __future__ import annotations

import httpx
import pytest
from fastapi.testclient import TestClient

from healer.core.api import app


def test_health():
    with TestClient(app) as client:
        r = client.get("/health")
        assert r.status_code == 200
        assert r.json()["status"] == "ok"


def test_metrics():
    with TestClient(app) as client:
        r = client.get("/metrics")
        assert r.status_code == 200
        assert b"# HELP" in r.content


def test_snapshot_with_healer_disabled():
    """healer_enabled=false → 0 инцидентов, 200."""
    payload = {
        "schema_version": "1.1",
        "snapshot_id": "s1",
        "cluster_id": "k8s-dev-1",
        "scout_node": "k8s-worker-1",
        "timestamp": "2025-10-15T10:00:00Z",
        "agent": {
            "scout_version": "0.1.0", "schema_version": "1.1",
            "collected_at": "2025-10-15T10:00:00Z",
            "duration_ms": 10, "errors": [],
        },
        "self_node": {
            "name": "k8s-worker-1", "role": "worker", "ready": True,
            "labels": {}, "annotations": {}, "conditions": [],
            "conditions_index": {}, "unschedulable": False, "taints": [],
        },
        "peer_nodes": [], "pods": [], "events": [], "metrics": {},
    }
    with TestClient(app) as client:
        r = client.post("/snapshot", json=payload)
        assert r.status_code == 200
        body = r.json()
        assert body["received"] is True
        assert body["incidents"] == 0       # healer_enabled=false