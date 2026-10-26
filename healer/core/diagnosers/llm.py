from __future__ import annotations

import json
import logging
from datetime import datetime, timezone

from healer.core.config import settings
from healer.core.diagnosers.base import Diagnoser
from healer.core.diagnosers.providers.base import LLMProvider
from healer.core.diagnosers.providers.factory import get_provider
from healer.core.schemas import Decision, Incident

log = logging.getLogger(__name__)

SYSTEM_PROMPT = """You are a Kubernetes healer agent.
Given an incident, choose exactly ONE action from the allow-list below.
Reply ONLY with JSON matching this schema:
{
  "diagnosis": "short diagnosis",
  "confidence": 0.0-1.0,
  "action_id": "restart_kubelet|rollout_restart|cleanup_images|raise_alert",
  "action_params": {...},
  "reason": "why this action",
  "escalate": true|false
}
If unsure, use action_id="raise_alert" and escalate=true.
"""


class LLMDiagnoser(Diagnoser):
    def __init__(self, provider: LLMProvider | None = None):
        self.provider = provider or get_provider()

    def diagnose(self, incident: Incident) -> Decision:
        user_msg = json.dumps({
            "incident": incident.model_dump(mode="json"),
        }, ensure_ascii=False)
        try:
            raw = self.provider.chat(
                messages=[
                    {"role": "system", "content": SYSTEM_PROMPT},
                    {"role": "user", "content": user_msg},
                ],
                response_schema={"type": "object"},
            )
            content = raw["choices"][0]["message"]["content"]
            data = json.loads(content)
            return Decision(
                incident_id=incident.id,
                cluster_id=incident.cluster_id,
                diagnosis=str(data.get("diagnosis", ""))[:500],
                confidence=float(data.get("confidence", 0.0)),
                action_id=str(data.get("action_id", "raise_alert")),
                action_params=dict(data.get("action_params", {})),
                reason=str(data.get("reason", ""))[:500],
                escalate=bool(data.get("escalate", False)),
            )
        except Exception:
            log.exception("LLM diagnose failed, escalating")
            return Decision(
                incident_id=incident.id,
                cluster_id=incident.cluster_id,
                diagnosis="llm_failure",
                confidence=0.0,
                action_id="raise_alert",
                reason="LLM unavailable, escalating to operator",
                escalate=True,
            )