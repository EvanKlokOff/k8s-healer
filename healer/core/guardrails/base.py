from abc import ABC, abstractmethod

from healer.core.schemas import Decision, GuardrailResult


class Guardrail(ABC):
    """Middleware перед исполнением. Может отклонить решение.
    Реализации: RateLimit, BlastRadius, DryRun.
    Позже — OPA/Kyverno."""

    name: str

    @abstractmethod
    def check(self, decision: Decision) -> GuardrailResult:
        ...