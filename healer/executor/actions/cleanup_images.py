from __future__ import annotations

import logging
import subprocess
from datetime import datetime

from healer.core.config import settings
from healer.core.schemas import ActionResult, Decision
from healer.executor.base import ActionRunner
from healer.executor.registry import register_action

log = logging.getLogger(__name__)


@register_action
class CleanupImagesAction(ActionRunner):
    action_id = "cleanup_images"

    def run(self, decision: Decision) -> ActionResult:
        started = datetime.utcnow()
        node = decision.action_params.get("node")
        if not node:
            return self._err(decision, started, "node missing")

        cmd = ["ssh", f"root@{node}", "crictl rmi --prune"]
        if settings.dry_run:
            log.info("DRY-RUN: would run %s", cmd)
            return self._ok(decision, started, f"dry-run: {' '.join(cmd)}", "dry_run")
        try:
            proc = subprocess.run(cmd, capture_output=True, timeout=120, text=True)
            if proc.returncode != 0:
                return self._err(decision, started, proc.stderr.strip())
        except Exception as exc:
            return self._err(decision, started, str(exc))
        return self._ok(decision, started, f"images pruned on {node}", "success")

    def _ok(self, d, started, msg, status):
        return ActionResult(
            decision_id=d.decision_id, action_id=self.action_id,
            status=status, message=msg, started_at=started, finished_at=datetime.utcnow(),
        )

    def _err(self, d, started, msg):
        return self._ok(d, started, msg, "failed")