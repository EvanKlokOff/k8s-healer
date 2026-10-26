# healer/core/config.py
from __future__ import annotations

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # --- Core ---
    kubeconfig_path: str = "/etc/healer/kubeconfig"

    # --- SSH (scout host-metrics + executor actions) ---
    ssh_user: str = "debian"
    ssh_key_path: str = "/etc/healer/ssh/k8s_debian"
    ssh_connect_timeout_sec: int = 5

    cluster_id: str = "k8s-dev-1"
    redis_url: str = "redis://redis:6379/0"
    postgres_dsn: str = "postgresql://healer:healer@postgres:5432/healer"
    dry_run: bool = True
    healer_enabled: bool = True
    confidence_threshold: float = 0.7

    # --- Guardrails ---
    rate_limit_per_node_per_hour: int = 1
    rate_limit_per_deployment_per_30min: int = 1
    blast_radius_max_pct: int = 30

    # --- LLM ---
    llm_provider: str = "openai_compat"
    llm_base_url: str = "http://localhost:11434/v1"
    llm_api_key: str = "ollama"
    llm_model: str = "qwen2.5:7b-instruct"
    llm_timeout_sec: int = 60
    llm_max_tokens_per_hour: int = 100_000

    # --- Alerts ---
    telegram_bot_token: str = ""
    telegram_chat_id: str = ""

    # --- Audit ---
    audit_sinks: str = "jsonl"                    # csv: jsonl,postgres
    audit_jsonl_path: str = "decisions.jsonl"
    audit_retention_days: int = 365

    # --- Approval (заглушка) ---
    approval_mode: str = "auto"                   # auto | manual_high | manual_all
    approval_timeout_sec: int = 300

    # --- Metrics ---
    metrics_enabled: bool = True


settings = Settings()