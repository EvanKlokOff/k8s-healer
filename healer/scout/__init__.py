# ┌─────────────────────────────────────────────────────────────────────┐
# │                         Pod (DaemonSet)                             │
# │  NODE_NAME=k8s-worker-1                                             │
# │                                                                     │
# │  ┌──────────────┐   ┌──────────────────┐   ┌────────────────────┐  │
# │  │ K8sApiScout  │──▶│ HostMetricsScout │──▶│   Publisher        │  │
# │  │ (k8s client) │   │ (psutil/systemd) │   │ (HTTP + retry)     │  │
# │  └──────────────┘   └──────────────────┘   └─────────┬──────────┘  │
# │         │                    │                       │              │
# │         ▼                    ▼                       ▼              │
# │   self_node +          cpu/mem/disk/          POST /snapshot       │
# │   peer_nodes +         kubelet_up/...         (JSON, 15s timeout)  │
# │   pods + events                                                  │
# └─────────────────────────────────────────────────────────────────────┘
#                                                               │
#                                                               ▼
#                                                     ┌──────────────────┐
#                                                     │  healer-core     │
#                                                     │  POST /snapshot  │
#                                                     └──────────────────┘
# healer/scout/__init__.py
from healer.scout.collectors.host_metrics import HostMetricsScout
from healer.scout.collectors.k8s_api_scout import K8sApiScout
from healer.scout.publisher import Publisher

__all__ = ["K8sApiScout", "HostMetricsScout", "Publisher"]