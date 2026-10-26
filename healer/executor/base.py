from abc import ABC, abstractmethod

from healer.core.schemas import ActionResult, Decision


class ActionRunner(ABC):
    """Исполняет действие. Регистрируется через @register_action.
    Позже — L2/L3 с approval."""

    action_id: str

    @abstractmethod
    def run(self, decision: Decision) -> ActionResult:
        ...