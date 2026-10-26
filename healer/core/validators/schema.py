# healer/core/validators/schema.py
from __future__ import annotations

import logging

import yaml

from healer.core.config import settings
from healer.core.schemas import Decision

log = logging.getLogger(__name__)


class DecisionValidator:
    """Проверяет Decision: confidence, allow-list, параметры."""

    def __init__(self, allowlist_path: str = "actions/allowlist.yaml"):
        with open(allowlist_path) as f:
            self.allowlist = yaml.safe_load(f)["actions"]

    def validate(self, decision: Decision) -> tuple[bool, str]:
        action = self.allowlist.get(decision.action_id)
        if not action:
            return False, f"action {decision.action_id} not in allowlist"
        if not action.get("enabled", True):
            return False, f"action {decision.action_id} disabled"

        required = action.get("requires_confidence")
        if required is not None and decision.confidence < required:
            return False, (
                f"confidence {decision.confidence} < required {required} "
                f"for {decision.action_id}"
            )

        if decision.confidence < settings.confidence_threshold and not decision.escalate:
            return False, (
                f"confidence {decision.confidence} < global threshold "
                f"{settings.confidence_threshold}"
            )

        return True, ""