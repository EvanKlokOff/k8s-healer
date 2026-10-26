"""Тесты load_rules: валидация YAML, disabled, ошибки."""
from __future__ import annotations

from pathlib import Path

import pytest

from healer.core.rules.loader import load_rules


def _write(tmp_path: Path, name: str, content: str) -> Path:
    p = tmp_path / name
    p.write_text(content, encoding="utf-8")
    return p


def test_load_all_four_rules(tmp_path):
    """Все 4 YAML из rules/ загружаются."""
    rules_dir = Path(__file__).resolve().parents[3] / "healer" / "rules"
    rules = load_rules(rules_dir)
    ids = {r.rule_id for r in rules}
    assert {"node_not_ready", "node_disk_pressure",
            "pod_crashloop", "pod_oomkilled"} <= ids


def test_load_skips_invalid_yaml(tmp_path):
    _write(tmp_path, "good.yaml", """
id: good
incident_type: node_not_ready
condition: {node_condition: Ready, status: "False", duration_sec: 0}
""")
    _write(tmp_path, "bad.yaml", "id: bad\nincident_type: [unclosed")
    rules = load_rules(tmp_path)
    assert len(rules) == 1
    assert rules[0].rule_id == "good"


def test_load_skips_unknown_field(tmp_path):
    """extra='forbid' в RuleConfig → опечатка в YAML ловится."""
    _write(tmp_path, "typo.yaml", """
id: typo
incident_type: node_not_ready
severty: high
condition: {}
""")
    assert load_rules(tmp_path) == []


def test_load_skips_disabled(tmp_path):
    _write(tmp_path, "off.yaml", """
id: off
incident_type: node_not_ready
enabled: false
condition: {}
""")
    assert load_rules(tmp_path) == []


def test_load_missing_dir(tmp_path):
    assert load_rules(tmp_path / "nope") == []