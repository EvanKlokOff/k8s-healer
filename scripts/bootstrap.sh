#!/usr/bin/env bash
# scripts/bootstrap.sh
#
# One-time setup: venv, зависимости, data-каталоги, проверка /etc/healer.
# Запускать из корня проекта.
set -euo pipefail

cd "$(dirname "$0")/.."
ROOT="$(pwd)"

echo "==> project root: $ROOT"

# 1. venv
if [[ ! -d .venv ]]; then
  echo "==> creating .venv"
  python3 -m venv .venv
fi
# shellcheck disable=SC1091
source .venv/bin/activate

# 2. зависимости
echo "==> installing requirements"
pip install --quiet --upgrade pip
pip install --quiet -r requirenments.txt

# 3. data-каталоги
mkdir -p data/audit
echo "==> data/audit ready"

# 4. /etc/healer
if [[ ! -f /etc/healer/kubeconfig ]]; then
  echo "WARN: /etc/healer/kubeconfig отсутствует — положи read-only kubeconfig."
fi
if [[ ! -f /etc/healer/ssh/k8s_debian ]]; then
  echo "WARN: /etc/healer/ssh/k8s_debian отсутствует — положи SSH-ключ."
fi

# 5. .env
if [[ ! -f .env ]]; then
  cp .env.example .env
  chmod 600 .env
  echo "==> .env создан из .env.example — отредактируй и перезапусти."
  exit 0
fi

# 6. sanity: LLM_API_KEY не CHANGE_ME
if grep -q '^LLM_API_KEY=CHANGE_ME' .env; then
  echo "WARN: LLM_API_KEY всё ещё CHANGE_ME — заполни."
fi

echo
echo "==> bootstrap OK"
echo "Дальше:"
echo "  1) docker compose up -d"
echo "  2) ./scripts/run-core.sh           # отдельный терминал"
echo "  3) ./scripts/run-scout.sh k8s-worker-1  # отдельный терминал"
echo "     ./scripts/run-scout.sh k8s-master"
echo "     ./scripts/run-scout.sh k8s-worker-2"