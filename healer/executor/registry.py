from __future__ import annotations

from healer.executor.base import ActionRunner

_REGISTRY: dict[str, type[ActionRunner]] = {}


def register_action(cls: type[ActionRunner]) -> type[ActionRunner]:
    _REGISTRY[cls.action_id] = cls
    return cls


def get_runner(action_id: str) -> ActionRunner:
    if action_id not in _REGISTRY:
        raise KeyError(f"No runner registered for {action_id}")
    return _REGISTRY[action_id]()


def list_actions() -> list[str]:
    return list(_REGISTRY)