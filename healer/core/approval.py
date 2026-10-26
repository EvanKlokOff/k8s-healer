from __future__ import annotations

from healer.core.config import settings
from healer.core.schemas import ActionRisk, Decision


class ApprovalGate:
    """Заглушка approval-flow. В MVP всегда auto.
    Позже: Telegram/Slack/UI + timeout + RBAC."""

    def __init__(self, mode: str | None = None):
        self.mode = mode or settings.approval_mode

    def required(self, decision: Decision) -> bool:
        if self.mode == "auto":
            return False
        if self.mode == "manual_all":
            return True
        if self.mode == "manual_high":
            return decision.risk in (ActionRisk.HIGH, ActionRisk.CRITICAL)
        return False

    def request(self, decision: Decision) -> tuple[bool, str]:
        """Возвращает (approved, reason). В MVP — всегда True."""
        if not self.required(decision):
            return True, "auto-approved"
        # TODO: отправить в канал, дождаться ответа с таймаутом
        return True, "stub: auto-approved (approval flow not implemented)"