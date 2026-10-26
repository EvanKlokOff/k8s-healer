from abc import ABC, abstractmethod

from healer.core.schemas import AuditRecord


class AuditSink(ABC):
    """Пишет решения и результаты. Реализации: PostgresAudit, JsonlAudit.
    Позже — ELK/Kafka."""

    @abstractmethod
    def record(self, record: AuditRecord) -> None:
        ...