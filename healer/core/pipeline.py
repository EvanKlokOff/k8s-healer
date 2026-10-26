# healer/core/pipeline.py
from __future__ import annotations

import logging
from datetime import datetime, timezone

from healer.audit.base import AuditSink
from healer.core.config import settings
from healer.core.dedup import Deduplicator
from healer.core.diagnosers.base import Diagnoser
from healer.core.guardrails.base import Guardrail
from healer.core.rules.base import Rule
from healer.core.schemas import (
    ActionResult,
    AuditRecord,
    Decision,
    GuardrailResult,
    Incident,
    Snapshot, LLMMeta,
)
from healer.core.validators.schema import DecisionValidator
from healer.executor.registry import get_runner

log = logging.getLogger(__name__)


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class Pipeline:
    """Оркестратор: snapshot → rules → dedup → diagnoser → validator
    → guardrails → executor → audit.

    process() — async, потому что AuditSink.record async (Postgres).
    """

    def __init__(
        self,
        rules: list[Rule],
        diagnoser: Diagnoser,
        validator: DecisionValidator,
        guardrails: list[Guardrail],
        audit: AuditSink,
        dedup: Deduplicator | None = None,
    ):
        self.rules = rules
        self.diagnoser = diagnoser
        self.validator = validator
        self.guardrails = guardrails
        self.audit = audit
        self.dedup = dedup

    # ---------- public ----------

    async def process(self, snapshot: Snapshot) -> list[AuditRecord]:
        if not settings.healer_enabled:
            log.warning("healer disabled via kill switch, skipping snapshot")
            return []

        incidents = self._detect(snapshot)
        incidents.sort(key=lambda i: (i.priority, i.severity), reverse=True)

        records: list[AuditRecord] = []
        for incident in incidents:
            if self.dedup and not self.dedup.claim(incident):
                log.info("incident %s deduplicated", incident.id)
                continue
            records.append(await self._handle(incident, snapshot))
        return records

    # ---------- detection ----------

    def _detect(self, snapshot: Snapshot) -> list[Incident]:
        incidents: list[Incident] = []
        for rule in self.rules:
            try:
                incidents.extend(rule.evaluate(snapshot))
            except Exception:
                log.exception("rule %s failed", rule.rule_id)
        return incidents

    # ---------- per-incident ----------

    async def _handle(self, incident: Incident, snapshot: Snapshot) -> AuditRecord:
        record = AuditRecord(
            cluster_id=incident.cluster_id,
            snapshot_id=snapshot.snapshot_id,        # <-- fix: пробрасываем snapshot_id
            incident=incident,
            versions={"code": "0.1.0"},
        )

        # 1. Diagnose
        decision, llm_meta = self._diagnose(incident)  # <-- tuple, не Decision
        # 1.5. Enrich node_ip для SSH-действий (restart_kubelet, cleanup_images)
        self._enrich_node_ip(decision, incident, snapshot)
        record.decision = decision
        record.llm_meta = llm_meta  # <-- новое

        # 2. Validate
        ok, reason = self.validator.validate(decision)
        if not ok:
            log.warning("decision rejected by validator: %s", reason)
            record.guardrails.append(
                GuardrailResult(name="validator", allowed=False, reason=reason)
            )
            return await self._finalize(record, status="skipped", message=reason)

        # 3. Guardrails
        for g in self.guardrails:
            result = g.check(decision)
            record.guardrails.append(result)
            if not result.allowed:
                log.warning("guardrail %s blocked: %s", g.name, result.reason)
                return await self._finalize(
                    record, status="skipped", message=f"{g.name}: {result.reason}",
                )

        # 4. Execute
        action_result = self._execute(decision)
        record.action_result = action_result
        await self.audit.record(record)
        return record

    # ---------- steps ----------

    def _diagnose(
            self, incident: Incident,
    ) -> tuple[Decision, LLMMeta | None]:
        try:
            return self.diagnoser.diagnose(incident)
        except Exception:
            log.exception("diagnoser failed for %s", incident.id)
            return Decision(
                incident_id=incident.id,
                cluster_id=incident.cluster_id,
                diagnosis="diagnoser_error",
                confidence=0.0,
                action_id="raise_alert",
                reason="Diagnoser exception, escalating",
                escalate=True,
            ), None

    def _enrich_node_ip(
        self, decision: Decision, incident: Incident, snapshot: Snapshot,
    ) -> None:
        """Для SSH-действий (restart_kubelet, cleanup_images) нужен IP ноды,
        а не имя. Берём из NodeInfo.labels["healer/ip"] (заполняет скаут).

        LLM возвращает action_params["node"] = имя ноды (или мы берём из incident.target).
        Добавляем action_params["node_ip"] — executor использует его для `ssh user@IP`.
        """
        if decision.action_id not in ("restart_kubelet", "cleanup_images"):
            return
        node_name = decision.action_params.get("node") or incident.target
        if not node_name:
            return
        ip = self._resolve_node_ip(snapshot, str(node_name))
        if ip:
            decision.action_params["node_ip"] = ip
        else:
            log.warning(
                "no healer/ip for node %s, SSH action may fail", node_name,
            )

    @staticmethod
    def _resolve_node_ip(snapshot: Snapshot, node_name: str) -> str | None:
        if snapshot.self_node.name == node_name:
            return (snapshot.self_node.labels or {}).get("healer/ip")
        for n in snapshot.peer_nodes:
            if n.name == node_name:
                return (n.labels or {}).get("healer/ip")
        return None

    def _execute(self, decision: Decision) -> ActionResult:
        try:
            runner = get_runner(decision.action_id)
            return runner.run(decision)
        except KeyError:
            return self._failed(decision, f"no runner for {decision.action_id}")
        except Exception as exc:
            log.exception("executor failed for %s", decision.action_id)
            return self._failed(decision, str(exc))

    @staticmethod
    def _failed(decision: Decision, message: str) -> ActionResult:
        now = _utcnow()
        return ActionResult(
            decision_id=decision.decision_id,
            action_id=decision.action_id,
            status="failed",
            message=message,
            started_at=now,
            finished_at=now,
        )

    async def _finalize(
        self, record: AuditRecord, status: str, message: str,
    ) -> AuditRecord:
        if record.decision:
            now = _utcnow()
            record.action_result = ActionResult(
                decision_id=record.decision.decision_id,
                action_id=record.decision.action_id,
                status=status,  # type: ignore[arg-type]
                message=message,
                started_at=now,
                finished_at=now,
            )
        await self.audit.record(record)
        return record