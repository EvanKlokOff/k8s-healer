from healer.core.config import settings
from healer.core.guardrails.base import Guardrail
from healer.core.schemas import Decision, GuardrailResult


class DryRunGuardrail(Guardrail):
    """Помечает решение как dry-run. Executor сам решает, исполнять ли."""

    name = "dry_run"

    def check(self, decision: Decision) -> GuardrailResult:
        if settings.dry_run:
            return GuardrailResult(
                name=self.name, allowed=True, reason="dry-run mode active"
            )
        return GuardrailResult(name=self.name, allowed=True)