# healer/core/api.py
from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException
from prometheus_client import CONTENT_TYPE_LATEST, generate_latest
from starlette.responses import Response

from healer.audit.factory import build_audit
from healer.core.config import settings
from healer.core.dedup import Deduplicator
from healer.core.diagnosers.llm import LLMDiagnoser
from healer.core.guardrails.blast_radius import BlastRadiusGuardrail
from healer.core.guardrails.dry_run import DryRunGuardrail
from healer.core.guardrails.rate_limit import RateLimitGuardrail
from healer.core.pipeline import Pipeline
from healer.core.rules.loader import load_rules
from healer.core.schemas import Snapshot
from healer.core.validators.schema import DecisionValidator

log = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO)

_pipeline: Pipeline | None = None
_audit = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    global _pipeline, _audit
    rules = load_rules(settings.rules_dir)
    diagnoser = LLMDiagnoser()
    validator = DecisionValidator(settings.allowlist_path)
    guardrails = [DryRunGuardrail(), RateLimitGuardrail(), BlastRadiusGuardrail()]
    _audit = build_audit(settings)
    dedup = Deduplicator(settings.redis_url)
    _pipeline = Pipeline(rules, diagnoser, validator, guardrails, _audit, dedup)
    log.info(
        "healer core started: rules=%d healer_enabled=%s dry_run=%s sinks=%s",
        len(rules), settings.healer_enabled, settings.dry_run, settings.audit_sinks,
    )
    try:
        yield
    finally:
        if _audit is not None:
            await _audit.close()
        log.info("healer core stopped")


app = FastAPI(title="K8s Node Healer", lifespan=lifespan)


@app.get("/health")
def health():
    return {"status": "ok", "enabled": settings.healer_enabled}


@app.get("/ready")
def ready():
    return {"status": "ready", "pipeline": _pipeline is not None}


@app.post("/snapshot")
async def ingest(snapshot: Snapshot):
    if _pipeline is None:
        raise HTTPException(503, "pipeline not initialized")
    records = await _pipeline.process(snapshot)
    return {
        "received": True,
        "snapshot_id": snapshot.snapshot_id,
        "incidents": len(records),
        "records": [r.record_id for r in records],
    }


@app.get("/metrics")
def metrics():
    if not settings.metrics_enabled:
        raise HTTPException(404, "metrics disabled")
    return Response(generate_latest(), media_type=CONTENT_TYPE_LATEST)