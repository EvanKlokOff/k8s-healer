from __future__ import annotations

import logging
from datetime import datetime

import httpx

from healer.core.config import settings
from healer.core.schemas import ActionResult, Decision
from healer.executor.base import ActionRunner
from healer.executor.registry import register_action

log = logging.getLogger(__name__)


@register_action
class RaiseAlertAction(ActionRunner):
    action_id = "raise_alert"

    def run(self, decision: Decision) -> ActionResult:
        started = datetime.utcnow()
        msg = (
            f"[healer] {decision.diagnosis}\n"
            f"action={decision.action_id} confidence={decision.confidence:.2f}\n"
            f"reason: {decision.reason}"
        )
        if settings.dry_run or not settings.telegram_bot_token:
            log.info("DRY-RUN alert: %s", msg)
            return ActionResult(
                decision_id=decision.decision_id,
                action_id=self.action_id,
                status="dry_run",
                message=msg,
                started_at=started,
                finished_at=datetime.utcnow(),
            )
        try:
            url = f"https://api.telegram.org/bot{settings.telegram_bot_token}/sendMessage"
            httpx.post(
                url,
                json={"chat_id": settings.telegram_chat_id, "text": msg},
                timeout=10,
            )
            status = "success"
        except Exception as exc:
            log.exception("Telegram alert failed")
            status = "failed"
            msg = f"{msg}\nerror: {exc}"
        return ActionResult(
            decision_id=decision.decision_id,
            action_id=self.action_id,
            status=status,
            message=msg,
            started_at=started,
            finished_at=datetime.utcnow(),
        )