#!/usr/bin/env bash
# scripts/run-scout.sh <node-name>
#
# Пример:
#   ./scripts/run-scout.sh k8s-worker-1
#   ./scripts/run-scout.sh k8s-master
#   ./scripts/run-scout.sh k8s-worker-2
#
# Запускать из корня проекта, каждый в своём терминале.
set -euo pipefail

if [[ $# -lt 1 ]]; then
  echo "usage: $0 <node-name>"
  echo "пример: $0 k8s-worker-1"
  exit 1
fi

NODE_NAME="$1"

cd "$(dirname "$0")/.."
# shellcheck disable=SC1091
source .venv/bin/activate

if [[ ! -f .env ]]; then
  echo "ERROR: .env отсутствует. Запусти ./scripts/bootstrap.sh"
  exit 1
fi

# Уникальный METRICS_PORT на каждого скаута, чтобы не конфликтовали
case "$NODE_NAME" in
  k8s-master)   METRICS_PORT=9100 ;;
  k8s-worker-1) METRICS_PORT=9101 ;;
  k8s-worker-2) METRICS_PORT=9102 ;;
  *)            METRICS_PORT=0    ;;   # 0 = не поднимать metrics
esac

# NODE_NAME и METRICS_PORT читаются скаутом напрямую через os.getenv,
# остальное (CORE_URL, KUBECONFIG_PATH, SSH_KEY_PATH, SSH_USER, CLUSTER_ID,
# INTERVAL_SEC) берётся из .env через settings.
export NODE_NAME
export METRICS_PORT

echo "==> starting scout for node=$NODE_NAME metrics_port=$METRICS_PORT"
exec python -m healer.scout.main