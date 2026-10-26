# healer/core/rules/base.py
"""Интерфейс правила и модель YAML-конфига.

Rule.evaluate(snapshot) -> list[Incident] — контракт, который использует Pipeline.
YamlRule — единственная реализация в MVP, но контракт позволяет добавить
MLAnomalyRule, RAGRule и т.п. без правки Pipeline.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from healer.core.schemas import Incident, Snapshot


Severity = Literal["low", "medium", "high", "critical"]


class RuleConfig(BaseModel):
    """Конфиг одного правила, читается из rules/*.yaml."""

    model_config = ConfigDict(extra="forbid")

    id: str
    version: str = "0.1.0"
    enabled: bool = True
    priority: int = 100                       # больше = важнее
    incident_type: str                        # "node_not_ready", "pod_crashloop", ...
    severity: Severity = "medium"
    scenario_version: str = "0.1.0"
    condition: dict[str, Any] = Field(default_factory=dict)


class Rule(ABC):
    """Правило: Snapshot → list[Incident]."""

    rule_id: str
    version: str

    @abstractmethod
    def evaluate(self, snapshot: Snapshot) -> list[Incident]:
        raise NotImplementedError