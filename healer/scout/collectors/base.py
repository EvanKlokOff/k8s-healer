from abc import ABC, abstractmethod

from healer.core.schemas import Snapshot


class Scout(ABC):
    """Собирает часть снапшота. Реализации: K8sApiScout, HostMetricsScout,
    позже — PrometheusScout, NodeExporterScout."""

    @abstractmethod
    def collect(self) -> Snapshot:
        ...