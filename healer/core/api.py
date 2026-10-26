# healer/core/api.py
from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException

from healer.audit.jsonl import JsonlAudit
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


@asynccontextmanager
async def lifespan(app: FastAPI):
    global _pipeline
    rules = load_rules("rules")
    diagnoser = LLMDiagnoser()
    validator = DecisionValidator("actions/allowlist.yaml")
    guardrails = [DryRunGuardrail(), RateLimitGuardrail(), BlastRadiusGuardrail()]
    audit = JsonlAudit(settings.audit_jsonl_path)
    dedup = Deduplicator(settings.redis_url)
    _pipeline = Pipeline(rules, diagnoser, validator, guardrails, audit, dedup)
    log.info("Healer core started with %d rules", len(rules))
    yield
    log.info("Healer core stopped")


app = FastAPI(title="K8s Node Healer", lifespan=lifespan)


@app.get("/health")
def health():
    return {"status": "ok", "enabled": settings.healer_enabled}


@app.get("/ready")
def ready():
    return {"status": "ready", "pipeline": _pipeline is not None}


@app.post("/snapshot")
def ingest(snapshot: Snapshot):
    if _pipeline is None:
        raise HTTPException(503, "pipeline not initialized")
    records = _pipeline.process(snapshot)
    return {
        "received": True,
        "incidents": len(records),
        "records": [r.record_id for r in records],
    }