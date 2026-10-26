# healer/scout/publisher.py
"""HTTP-публикация Snapshot в healer-core с retry и метриками."""
from __future__ import annotations

import logging
import time

import httpx

from healer.core.schemas import Snapshot
from healer.scout import metrics

log = logging.getLogger(__name__)

DEFAULT_TIMEOUT = 15.0
RETRY_DELAYS = (0.5, 1.0, 2.0)


class Publisher:
    def __init__(self, core_url: str, timeout: float = DEFAULT_TIMEOUT) -> None:
        self.core_url = core_url.rstrip("/")
        self._client = httpx.Client(timeout=timeout)
        self._endpoint = f"{self.core_url}/snapshot"

    def publish(self, snapshot: Snapshot) -> bool:
        payload = snapshot.model_dump(mode="json")
        node = snapshot.scout_node
        cluster = snapshot.cluster_id
        last_exc: Exception | None = None

        for attempt, delay in enumerate((0.0, *RETRY_DELAYS), start=1):
            if delay:
                time.sleep(delay)
            try:
                resp = self._client.post(self._endpoint, json=payload)
                if resp.status_code < 500:
                    if resp.status_code >= 400:
                        log.error(
                            "core rejected snapshot for %s: %s %s",
                            node, resp.status_code, resp.text[:500],
                        )
                        metrics.snapshots_sent_total.labels(
                            status="rejected", node=node, cluster=cluster,
                        ).inc()
                        return False
                    metrics.snapshots_sent_total.labels(
                        status="ok", node=node, cluster=cluster,
                    ).inc()
                    incidents = "?"
                    try:
                        incidents = resp.json().get("incidents", "?")
                    except Exception:
                        pass
                    log.info("snapshot sent: node=%s incidents=%s", node, incidents)
                    return True
                log.warning("core 5xx on attempt %d: %s", attempt, resp.status_code)
                last_exc = httpx.HTTPStatusError(
                    f"server error {resp.status_code}",
                    request=resp.request, response=resp,
                )
            except (httpx.TransportError, httpx.TimeoutException) as exc:
                log.warning("core unreachable on attempt %d: %s", attempt, exc)
                last_exc = exc

        metrics.snapshots_sent_total.labels(
            status="failed", node=node, cluster=cluster,
        ).inc()
        log.error("snapshot publish failed after retries: node=%s err=%s", node, last_exc)
        return False

    def close(self) -> None:
        self._client.close()