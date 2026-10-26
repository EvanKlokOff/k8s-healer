from __future__ import annotations

import json

import pytest

from healer.core.diagnosers.llm import LLMDiagnoser
from tests.core.diagnosers.conftest import MockProvider, _valid_decision_json


def _diag(responses: list[str], threshold: float = 0.7) -> LLMDiagnoser:
    return LLMDiagnoser(
        provider=MockProvider(responses),
        redis_url=False,
        confidence_threshold=threshold,
    )


def test_valid_json(nr_incident):
    d = _diag([_valid_decision_json()])
    decision, meta = d.diagnose(nr_incident)
    assert decision.action_id == "restart_kubelet"
    assert decision.action_params["node"] == "k8s-worker-1"
    assert decision.confidence == 0.9
    assert meta is not None
    assert meta.prompt_tokens == 100
    assert meta.completion_tokens == 50
    assert meta.prompt_version == "0.1.0"
    assert meta.cached is False


def test_markdown_json(nr_incident):
    wrapped = f"Here you go:\n```json\n{_valid_decision_json()}\n```\n"
    d = _diag([wrapped])
    decision, _ = d.diagnose(nr_incident)
    assert decision.action_id == "restart_kubelet"


def test_invalid_json_retry_then_ok(nr_incident):
    d = _diag(["not json at all", _valid_decision_json()])
    decision, meta = d.diagnose(nr_incident)
    assert decision.action_id == "restart_kubelet"
    assert len(d.provider.calls) == 2
    # retry_hint попал в user message
    assert "not valid JSON" in d.provider.calls[1][-1]["content"]


def test_invalid_json_twice_fallback(nr_incident):
    d = _diag(["garbage", "still garbage"])
    decision, meta = d.diagnose(nr_incident)
    assert decision.action_id == "raise_alert"
    assert decision.escalate is True
    assert decision.confidence == 0.0
    assert meta is not None                 # <-- LLMMeta есть (попытка была)
    assert meta.prompt_version == "0.1.0"
    assert meta.latency_ms == 0             # fallback: реального вызова не было
    assert meta.cached is False


def test_low_confidence_forced_to_raise_alert(nr_incident):
    d = _diag([_valid_decision_json(confidence=0.5)], threshold=0.7)
    decision, _ = d.diagnose(nr_incident)
    assert decision.action_id == "raise_alert"
    assert decision.escalate is True
    assert "threshold" in decision.reason.lower() or "confidence" in decision.reason.lower()


def test_low_confidence_already_escalate_kept(nr_incident):
    d = _diag([_valid_decision_json(
        confidence=0.4, action_id="raise_alert", escalate=True,
    )], threshold=0.7)
    decision, _ = d.diagnose(nr_incident)
    assert decision.action_id == "raise_alert"
    assert decision.escalate is True


def test_provider_exception_fallback(nr_incident):
    d = _diag([])                    # MockProvider бросит RuntimeError
    decision, meta = d.diagnose(nr_incident)
    assert decision.action_id == "raise_alert"
    assert decision.escalate is True
    # meta всё равно строится (латентность, версия)
    assert meta is not None
    assert meta.prompt_version == "0.1.0"


def test_invalid_decision_fields_fallback(nr_incident):
    """action_id не из allow-list, confidence > 1.0 → Decision validation падает."""
    d = _diag([
        json.dumps({"diagnosis": "x", "confidence": 2.0,
                    "action_id": "restart_kubelet", "action_params": {},
                    "reason": "x", "escalate": False}),
        "still garbage",
    ])
    decision, _ = d.diagnose(nr_incident)
    assert decision.action_id == "raise_alert"