from __future__ import annotations

import logging
from datetime import datetime

from healer.core.config import settings
from healer.core.schemas import ActionResult, Decision
from healer.executor.base import ActionRunner
from healer.executor.registry import register_action

log = logging.getLogger(__name__)


@register_action
class RolloutRestartAction(ActionRunner):
    action_id = "rollout_restart"

    def run(self, decision: Decision) -> ActionResult:
        started = datetime.utcnow()
        ns = decision.action_params.get("namespace")
        name = decision.action_params.get("deployment")
        if not (ns and name):
            return self._err(decision, started, "namespace/deployment missing")

        cmd = ["kubectl", "-n", ns, "rollout", "restart", f"deployment/{name}"]
        if settings.dry_run:
            log.info("DRY-RUN: would run %s", cmd)
            return self._ok(decision, started, f"dry-run: {' '.join(cmd)}", "dry_run")

        import subprocess
        try:
            proc = subprocess.run(cmd, capture_output=True, timeout=60, text=True)
            if proc.returncode != 0:
                return self._err(decision, started, proc.stderr.strip())
        except Exception as exc:
            return self._err(decision, started, str(exc))
        return self._ok(decision, started, f"rollout restarted {ns}/{name}", "success")

    def _ok(self, d, started, msg, status):
        return ActionResult(
            decision_id=d.decision_id, action_id=self.action_id,
            status=status, message=msg, started_at=started, finished_at=datetime.utcnow(),
        )

    def _err(self, d, started, msg):
        return self._ok(d, started, msg, "failed")