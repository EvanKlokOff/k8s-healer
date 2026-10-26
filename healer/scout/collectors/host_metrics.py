# healer/scout/collectors/host_metrics.py
"""Собирает хост-метрики ноды через SSH.

Scout живёт вне кластера (на отдельном хосте healer), поэтому psutil/systemctl
локально не подходят — выполняем команды на ноде по SSH.

Один SSH-вызов на ноду за цикл (минимум round-trip).
"""
from __future__ import annotations

import logging
import subprocess

from healer.core.config import settings
from healer.core.schemas import NodeInfo, Snapshot
from healer.scout.collectors.base import Scout

log = logging.getLogger(__name__)


class HostMetricsScout(Scout):
    """Модифицирует Snapshot через merge_into(snapshot)."""

    def collect(self) -> Snapshot:  # pragma: no cover
        raise NotImplementedError("Use merge_into(snapshot) instead")

    def __init__(self) -> None:
        self.ssh_user = settings.ssh_user
        self.ssh_key = settings.ssh_key_path
        self.ssh_opts = [
            "-i", self.ssh_key,
            "-o", "StrictHostKeyChecking=no",
            "-o", "UserKnownHostsFile=/dev/null",
            "-o", f"ConnectTimeout={settings.ssh_connect_timeout_sec}",
            "-o", "BatchMode=yes",
            "-o", "LogLevel=ERROR",
        ]

    def merge_into(self, snapshot: Snapshot) -> Snapshot:
        node = snapshot.self_node
        host = self._ssh_host(node)
        if not host:
            log.warning("no SSH address for node %s, skipping host metrics", node.name)
            return snapshot

        data = self._collect_remote(host)
        if not data:
            # SSH не удался — оставляем поля как есть (None), не затираем нулями
            return snapshot

        node.cpu_usage_pct = data.get("cpu_pct")
        node.mem_usage_pct = data.get("mem_pct")
        node.disk_usage_pct = data.get("disk_pct")
        node.disk_inodes_pct = data.get("inodes_pct")
        node.load_1m = data.get("load_1m")
        node.load_5m = data.get("load_5m")
        node.load_15m = data.get("load_15m")
        node.uptime_sec = data.get("uptime_sec")
        node.kubelet_up = data.get("kubelet_up")
        node.containerd_up = data.get("containerd_up")
        node.kube_proxy_up = data.get("kube_proxy_up")
        return snapshot

    @staticmethod
    def _ssh_host(node: NodeInfo) -> str | None:
        # приоритет: labels["healer/ip"] (заполняет k8s_api_scout) → name
        ip = (node.labels or {}).get("healer/ip")
        return ip or node.name

    def _collect_remote(self, host: str) -> dict:
        """Один SSH-вызов, собирающий всё сразу."""
        # Каждая команда печатает ровно одну строку; системные сервисы
        # могут отсутствовать — печатаем "unknown", чтобы не сдвигать строки.
        script = (
            "cat /proc/loadavg | cut -d' ' -f1-3; "
            "awk '/^cpu /{t=0; for(i=2;i<=NF;i++)t+=$i; print $2+$3+$4, $5, t}' /proc/stat; "
            "cut -d' ' -f1 /proc/uptime; "
            "free -m | awk '/^Mem:/{print $3, $2}'; "
            "df -P / | awk 'NR==2{print $3, $2}'; "
            "df -i -P / | awk 'NR==2{print $3, $2}'; "
            "(systemctl is-active kubelet 2>/dev/null || echo unknown); "
            "(systemctl is-active containerd 2>/dev/null || echo unknown); "
            "(systemctl is-active kube-proxy 2>/dev/null || echo unknown)"
        )
        cmd = ["ssh", *self.ssh_opts, f"{self.ssh_user}@{host}", script]
        try:
            proc = subprocess.run(cmd, capture_output=True, text=True, timeout=15)
            if proc.returncode != 0:
                log.warning("ssh to %s failed: %s", host, proc.stderr.strip())
                return {}
        except subprocess.TimeoutExpired:
            log.warning("ssh to %s timed out", host)
            return {}
        except Exception:
            log.exception("ssh to %s failed", host)
            return {}
        return self._parse(proc.stdout)

    @staticmethod
    def _parse(out: str) -> dict:
        lines = out.strip().splitlines()
        if len(lines) < 9:
            log.warning("unexpected ssh output (got %d lines): %r", len(lines), out)
            return {}
        d: dict = {}
        try:
            # 1) loadavg
            l1, l5, l15 = lines[0].split()[:3]
            d["load_1m"], d["load_5m"], d["load_15m"] = float(l1), float(l5), float(l15)

            # 2) cpu: "user nice system idle total"
            parts = lines[1].split()
            busy = int(parts[0])
            idle = int(parts[1])
            total = int(parts[2])
            d["cpu_pct"] = round(100.0 * busy / total, 2) if total else None

            # 3) uptime
            d["uptime_sec"] = int(float(lines[2].strip()))

            # 4) mem: used_mb total_mb
            used_mb, total_mb = map(int, lines[3].split())
            d["mem_pct"] = round(100.0 * used_mb / total_mb, 2) if total_mb else None

            # 5) disk: used_kb total_kb
            d_used, d_total = map(int, lines[4].split())
            d["disk_pct"] = round(100.0 * d_used / d_total, 2) if d_total else None

            # 6) inodes: used total
            i_used, i_total = map(int, lines[5].split())
            d["inodes_pct"] = round(100.0 * i_used / i_total, 2) if i_total else None

            def _svc(v: str) -> bool | None:
                v = v.strip()
                if v == "active":
                    return True
                if v in ("inactive", "failed", "deactivating"):
                    return False
                return None

            d["kubelet_up"] = _svc(lines[6])
            d["containerd_up"] = _svc(lines[7])
            d["kube_proxy_up"] = _svc(lines[8])
        except Exception:
            log.exception("failed to parse ssh output: %r", out)
            return {}
        return d