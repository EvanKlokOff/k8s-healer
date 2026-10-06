# K8s Node Healer — Design Document (MVP)

## 1. Цель
Автономный ИИ-агент, который детектит проблемы нод/подов Kubernetes
и применяет безопасные действия (L1) или эскалирует алертом.

## 2. Архитектура MVP

    ┌──────────────────────────────────────────────────────────┐
    │  DaemonSet: healer-scout (на каждой ноде)                │
    │  - k8s API (nodes, pods, events)                         │
    │  - host metrics (/proc, psutil)                          │
    │  - POST snapshot → decision-service каждые 15–30 сек     │
    └───────────────────────────┬──────────────────────────────┘
                                │ HTTP/JSON
                                ▼
    ┌──────────────────────────────────────────────────────────┐
    │  Deployment: healer-core (на control plane)              │
    │                                                          │
    │  FastAPI /snapshot                                       │
    │      │                                                   │
    │      ├─► Deduplicator (Redis)                            │
    │      ├─► RuleEngine (YAML правила)                       │
    │      │       └─► Incident[]                              │
    │      ├─► Diagnoser (LLM, function calling)               │
    │      │       └─► Decision{diagnosis, action, confidence} │
    │      ├─► Validator (JSON Schema + confidence threshold)  │
    │      ├─► Guardrails (rate-limit, blast-radius, dry-run)  │
    │      ├─► Executor (allow-list действий)                  │
    │      └─► AuditSink (Postgres / JSONL)                    │
    └──────────────────────────────────────────────────────────┘

## 3. Сценарии MVP (4)

| ID | Симптом | Детект | L1-действие |
|----|---------|--------|-------------|
| S1 | NodeNotReady | node.conditions Ready=False > 5 мин | restart_kubelet (SSH/systemd) |
| S2 | CrashLoopBackOff | pod.restarts > 5 за 10 мин | rollout_restart deployment |
| S3 | DiskPressure | node.conditions DiskPressure=True | cleanup_images (crictl rmi --prune) |
| S4 | OOMKilled | pod.lastState.terminated.reason=OOMKilled | raise_alert (L1.5 — только алерт) |

## 4. Действия MVP (allow-list)

| action_id | Тип | Риск | Guardrails |
|-----------|-----|------|------------|
| restart_kubelet | SSH + systemctl | средний | dry-run, 1/нода/час |
| rollout_restart | kubectl | низкий | 1/deployment/30мин |
| cleanup_images | SSH + crictl | низкий | 1/нода/6час, только если DiskPressure |
| raise_alert | webhook (Telegram) | нет | всегда разрешено |

## 5. Границы MVP

### Входит
- DaemonSet-скаут на всех нодах.
- 4 сценария, 4 действия (3 авто + 1 алерт).
- LLM-диагноз с JSON-схемой, confidence, fallback на rules.
- Guardrails: dry-run, rate-limit, blast-radius, allow-list.
- Аудит (Postgres JSONB + минимальный HTML дашборд).
- Алерты в Telegram.
- Ansible-роль + RBAC.
- Shadow-режим (флаг `DRY_RUN=true`).
- Unit + integration тесты.

### НЕ входит (roadmap)
- L2/L3 действия (drain, reboot, evict) с approval.
- ML-anomaly detection.
- RAG на runbook’ах.
- Локальная LLM vs API — абстракция есть, реализация одна.
- Human-in-the-loop UI.
- Chaos-mesh регулярно.
- Мультикластерность.
- Predictive healing.

## 6. Roadmap расширений (архитектурные точки)

Каждый пункт = новая реализация существующего интерфейса:

1. `Scout`: добавить `PrometheusScout`, `NodeExporterScout`.
2. `Rule`: добавить `MLAnomalyRule` рядом с YAML-правилами.
3. `Diagnoser`: добавить `RAGDiagnoser`, `RuleOnlyDiagnoser`.
4. `ActionRunner`: добавить L2/L3 с approval-flow.
5. `Guardrail`: заменить на OPA/Kyverno.
6. `AuditSink`: добавить ELK/Kafka sink.
7. `LLMProvider`: абстракция — self-hosted (vLLM/Ollama) ↔ OpenAI ↔ Anthropic без изменения ядра.
8. Очередь: Redis Streams → NATS/Kafka при росте.
9. Деплой: Ansible → Helm/GitOps.
10. Мультикластерность: отдельный core на кластер + federated audit.

## 7. Ключевой тезис защиты
MVP — это не объём, а правильные абстракции + guardrails + roadmap.
Каждый компонент заменяем без переписывания ядра.