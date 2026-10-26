"""Mock LLMProvider для тестов."""
from __future__ import annotations

import json

import pytest

from healer.core.diagnosers.providers.base import LLMProvider


class MockProvider(LLMProvider):
    def __init__(self, responses: list[str]):
        self.responses = list(responses)
        self.calls: list[list[dict]] = []

    def chat(self, messages, tools=None, response_schema=None):
        self.calls.append(messages)
        if not self.responses:
            raise RuntimeError("MockProvider exhausted")
        content = self.responses.pop(0)
        return {
            "choices": [{"message": {"content": content}}],
            "usage": {"prompt_tokens": 100, "completion_tokens": 50},
        }


def _valid_decision_json(**overrides) -> str:
    base = {
        "diagnosis": "kubelet down", "confidence": 0.9,
        "action_id": "restart_kubelet",
        "action_params": {"node": "k8s-worker-1"},
        "reason": "kubelet_up=false", "escalate": False,
    }
    base.update(overrides)
    return json.dumps(base)


@pytest.fixture
def nr_incident():
    from datetime import datetime, timezone
    from healer.core.schemas import Incident
    return Incident(
        id="inc-nr", type="node_not_ready", target="k8s-worker-1",
        severity="high", priority=200, evidence={"node": "k8s-worker-1"},
        detected_at=datetime.now(timezone.utc), cluster_id="k8s-dev-1",
    )