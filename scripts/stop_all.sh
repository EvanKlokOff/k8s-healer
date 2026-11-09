#!/usr/bin/env bash
# scripts/stop-all.sh
#
# Останавливает нативные процессы core/scout и docker-compose.
# Нативные ищем по cmdline (uvicorn healer.core.api / python -m healer.scout.main).
set -euo pipefail

cd "$(dirname "$0")/.."

echo "==> killing native healer-core"
pkill -f 'uvicorn healer.core.api:app' 2>/dev/null || true

echo "==> killing native scouts"
pkill -f 'python -m healer.scout.main' 2>/dev/null || true

echo "==> docker compose down"
docker compose down

echo "==> done"