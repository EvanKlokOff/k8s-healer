from prometheus_client import Counter, Histogram

incidents_detected_total = Counter(
    "healer_incidents_detected_total", "Incidents detected", ["type", "cluster"]
)
decisions_made_total = Counter(
    "healer_decisions_made_total", "Decisions made", ["action", "cluster"]
)
actions_executed_total = Counter(
    "healer_actions_executed_total", "Actions executed", ["action", "status"]
)
llm_latency_seconds = Histogram(
    "healer_llm_latency_seconds", "LLM latency", ["provider", "model"]
)
guardrail_rejections_total = Counter(
    "healer_guardrail_rejections_total", "Guardrail rejections", ["name"]
)