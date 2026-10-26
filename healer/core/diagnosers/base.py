from abc import ABC, abstractmethod

from healer.core.schemas import Decision, Incident


class Diagnoser(ABC):
    """Ставит диагноз и выбирает действие.
    Реализации: LLMDiagnoser, позже RuleOnlyDiagnoser, RAGDiagnoser."""

    @abstractmethod
    def diagnose(self, incident: Incident) -> Decision:
        ...