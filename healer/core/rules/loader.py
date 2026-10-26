# healer/core/rules/loader.py
"""Загрузка YAML-правил из директории.

Правила — файлы *.yaml в rules/. Каждый — RuleConfig. Ошибка в одном файле
не валит остальные: log.warning + пропуск. Если файлов нет — пустой список
(скаут работает, но инцидентов не будет — это лучше, чем падать).
"""
from __future__ import annotations

import logging
from datetime import datetime
from pathlib import Path
from typing import Callable

import yaml
from pydantic import ValidationError

from healer.core.rules.base import Rule, RuleConfig
from healer.core.rules.yaml_rule import YamlRule

log = logging.getLogger(__name__)


def load_rules(rules_dir: str | Path,now_fn: Callable[[], datetime] | None = None,) -> list[Rule]:
    path = Path(rules_dir)
    if not path.exists():
        log.warning("rules dir %s does not exist, no rules loaded", path)
        return []

    rules: list[Rule] = []
    for f in sorted(path.glob("*.yaml")):
        try:
            data = yaml.safe_load(f.read_text(encoding="utf-8"))
            if not isinstance(data, dict):
                log.warning("rule file %s: expected mapping, got %r", f.name, type(data).__name__)
                continue
            cfg = RuleConfig.model_validate(data)
            if not cfg.enabled:
                log.info("rule %s disabled, skipping", cfg.id)
                continue
            rules.append(YamlRule(cfg, now_fn=now_fn))
            log.info("loaded rule %s v%s (%s)", cfg.id, cfg.version, cfg.incident_type)
        except yaml.YAMLError as exc:
            log.error("rule file %s: YAML parse error: %s", f.name, exc)
        except ValidationError as exc:
            log.error("rule file %s: invalid config: %s", f.name, exc)
        except Exception:
            log.exception("rule file %s: unexpected error", f.name)

    return rules