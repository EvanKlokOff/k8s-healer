#!/usr/bin/env bash
# scripts/run-core.sh
#
# Запуск healer-core нативно (uvicorn) в текущем терминале.
# Ctrl+C — остановка. Логи идут в stdout.
set -euo pipefail

cd "$(dirname "$0")/.."
# shellcheck disable=SC1091
source .venv/bin/activate

# .env подхватится автоматически через pydantic-settings,
# но на всякий случай убедимся, что он есть.
if [[ ! -f .env ]]; then
  echo "ERROR: .env отсутствует. Запусти ./scripts/bootstrap.sh"
  exit 1
fi

# Sanity: core нативный, значит БД на localhost
if ! grep -qE '^(REDIS_URL|POSTGRES_DSN)=' .env; then
  echo "ERROR: .env должен содержать REDIS_URL и POSTGRES_DSN"
  exit 1
fi

echo "==> starting healer-core on ${CORE_BIND:-127.0.0.1}:${CORE_PORT:-8080}"
exec uvicorn healer.core.api:app \
  --host "${CORE_BIND:-127.0.0.1}" \
  --port "${CORE_PORT:-8080}" \
  --log-level info