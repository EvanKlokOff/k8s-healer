# healer/audit/base.py
from abc import ABC, abstractmethod

from healer.core.schemas import AuditRecord


class AuditSink(ABC):
    """Пишет решения и результаты. Реализации: PostgresAudit, JsonlAudit.
    Позже — ELK/Kafka.

    MVP: async. Postgres — asyncpg (нативно async). JSONL — синхронная запись
    внутри async-метода (быстро, не блокирует event loop заметно).
    """

    @abstractmethod
    async def record(self, record: AuditRecord) -> None:
        raise NotImplementedError

    async def close(self) -> None:
        """Закрыть ресурсы. Default — no-op."""
        return None