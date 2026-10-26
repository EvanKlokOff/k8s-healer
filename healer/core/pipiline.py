# healer/core/pipeline.py
from __future__ import annotations

import logging
from datetime import datetime

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
    Snapshot,
)
from healer.core.validators.schema import DecisionValidator
from healer.executor.registry import get_runner

log = logging.getLogger(__name__)


class Pipeline:
    """Оркестратор: snapshot → rules → dedup → diagnoser → validator
    → guardrails → executor → audit."""

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

    def process(self, snapshot: Snapshot) -> list[AuditRecord]:
        if not settings.healer_enabled:
            log.warning("Healer disabled via kill switch, skipping snapshot")
            return []

        incidents = self._detect(snapshot)
        incidents.sort(key=lambda i: (i.priority, i.severity), reverse=True)

        records: list[AuditRecord] = []
        for incident in incidents:
            if self.dedup and not self.dedup.claim(incident):
                log.info("Incident %s deduplicated", incident.id)
                continue
            records.append(self._handle(incident))
        return records

    # ---------- private ----------

    def _detect(self, snapshot: Snapshot) -> list[Incident]:
        incidents: list[Incident] = []
        for rule in self.rules:
            try:
                incidents.extend(rule.evaluate(snapshot))
            except Exception:
                log.exception("Rule %s failed", rule.rule_id)
        return incidents

    def _handle(self, incident: Incident) -> AuditRecord:
        record = AuditRecord(
            cluster_id=incident.cluster_id,
            incident=incident,
            versions={"code": "0.1.0"},
        )

        # 1. Diagnose
        try:
            decision = self.diagnoser.diagnose(incident)
        except Exception:
            log.exception("Diagnoser failed for %s", incident.id)
            decision = Decision(
                incident_id=incident.id,
                cluster_id=incident.cluster_id,
                diagnosis="diagnoser_error",
                confidence=0.0,
                action_id="raise_alert",
                reason="Diagnoser exception, escalating",
                escalate=True,
            )
        record.decision = decision

        # 2. Validate
        ok, reason = self.validator.validate(decision)
        if not ok:
            log.warning("Decision rejected by validator: %s", reason)
            record.guardrails.append(
                GuardrailResult(name="validator", allowed=False, reason=reason)
            )
            return self._finalize(record, status="skipped", message=reason)

        # 3. Guardrails
        for g in self.guardrails:
            result = g.check(decision)
            record.guardrails.append(result)
            if not result.allowed:
                log.warning("Guardrail %s blocked: %s", g.name, result.reason)
                return self._finalize(
                    record, status="skipped", message=f"{g.name}: {result.reason}"
                )

        # 4. Execute
        try:
            runner = get_runner(decision.action_id)
            action_result = runner.run(decision)
        except KeyError:
            action_result = ActionResult(
                decision_id=decision.decision_id,
                action_id=decision.action_id,
                status="failed",
                message=f"No runner registered for {decision.action_id}",
                started_at=datetime.utcnow(),
                finished_at=datetime.utcnow(),
            )
        except Exception as exc:
            log.exception("Executor failed for %s", decision.action_id)
            action_result = ActionResult(
                decision_id=decision.decision_id,
                action_id=decision.action_id,
                status="failed",
                message=str(exc),
                started_at=datetime.utcnow(),
                finished_at=datetime.utcnow(),
            )

        record.action_result = action_result
        self.audit.record(record)
        return record

    def _finalize(self, record: AuditRecord, status: str, message: str) -> AuditRecord:
        if record.decision:
            record.action_result = ActionResult(
                decision_id=record.decision.decision_id,
                action_id=record.decision.action_id,
                status=status,  # type: ignore[arg-type]
                message=message,
                started_at=datetime.utcnow(),
                finished_at=datetime.utcnow(),
            )
        self.audit.record(record)
        return record