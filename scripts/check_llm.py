"""Ручная проверка LLMDiagnoser на 4 фиктивных инцидентах.

Usage:
    LLM_BASE_URL=http://localhost:11434/v1 LLM_MODEL=qwen2.5:7b-instruct \
        python scripts/check_llm.py
"""
from __future__ import annotations

import json
import sys
from datetime import datetime, timezone

from healer.core.diagnosers.llm import LLMDiagnoser
from healer.core.schemas import Incident

NOW = datetime.now(timezone.utc)

INCIDENTS = [
    Incident(
        id="inc-nr", type="node_not_ready", target="k8s-worker-1",
        severity="high", priority=200,
        evidence={
            "node": "k8s-worker-1", "condition": "Ready", "status": "False",
            "age_sec": 420, "role": "worker",
            "kubelet_up": False, "containerd_up": True,
        },
        detected_at=NOW, cluster_id="k8s-dev-1", rule_id="node_not_ready",
    ),
    Incident(
        id="inc-cl", type="pod_crashloop", target="default/web-7d9f8b-abc12",
        severity="medium", priority=150,
        evidence={
            "namespace": "default", "pod": "web-7d9f8b-abc12",
            "restarts": 8, "owner_kind": "ReplicaSet",
            "owner_name": "web-7d9f8b",
            "last_terminated_reason": "CrashLoopBackOff",
        },
        detected_at=NOW, cluster_id="k8s-dev-1", rule_id="pod_crashloop",
    ),
    Incident(
        id="inc-dp", type="node_disk_pressure", target="k8s-worker-2",
        severity="high", priority=180,
        evidence={
            "node": "k8s-worker-2", "condition": "DiskPressure",
            "status": "True", "role": "worker",
        },
        detected_at=NOW, cluster_id="k8s-dev-1", rule_id="node_disk_pressure",
    ),
    Incident(
        id="inc-oom", type="pod_oomkilled", target="default/api-5f7b9-x2k",
        severity="medium", priority=160,
        evidence={
            "namespace": "default", "pod": "api-5f7b9-x2k",
            "container": "api", "exit_code": 137, "mem_limit_mb": 128,
        },
        detected_at=NOW, cluster_id="k8s-dev-1", rule_id="pod_oomkilled",
    ),
]


def main() -> int:
    d = LLMDiagnoser(redis_url=False)         # без кэша для чистого прогона
    for inc in INCIDENTS:
        decision, meta = d.diagnose(inc)
        print(f"\n=== {inc.type} -> {inc.target} ===")
        print(json.dumps(decision.model_dump(mode="json"), indent=2, ensure_ascii=False))
        if meta:
            print(f"meta: model={meta.model} latency_ms={meta.latency_ms} "
                  f"tokens={meta.prompt_tokens}+{meta.completion_tokens}")
    return 0


if __name__ == "__main__":
    sys.exit(main())