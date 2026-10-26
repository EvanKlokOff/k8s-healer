# healer/core/diagnosers/base.py
from abc import ABC, abstractmethod

from healer.core.schemas import Decision, Incident, LLMMeta


class Diagnoser(ABC):
    """Ставит диагноз и выбирает действие.

    Возвращает (Decision, LLMMeta | None). LLMMeta — только для LLM-based
    реализаций; RuleOnlyDiagnoser вернёт None.

    Реализации: LLMDiagnoser, позже RuleOnlyDiagnoser, RAGDiagnoser.
    """

    @abstractmethod
    def diagnose(self, incident: Incident) -> tuple[Decision, LLMMeta | None]:
        ...