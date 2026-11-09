#!/usr/bin/env bash
# scripts/status.sh — быстрый health-check всего стека.
set -uo pipefail

cd "$(dirname "$0")/.."
# shellcheck disable=SC1091
source .venv/bin/activate 2>/dev/null || true

echo "── docker ──────────────────────────────────────"
docker compose ps

echo
echo "── native processes ────────────────────────────"
ps aux | grep -E 'uvicorn healer\.core|python -m healer\.scout' | grep -v grep || echo "  (none running)"

echo
echo "── core /health /ready ─────────────────────────"
CORE_PORT="${CORE_PORT:-8080}"
curl -s "http://127.0.0.1:${CORE_PORT}/health" | (jq . 2>/dev/null || cat) || echo "  core not reachable"
curl -s "http://127.0.0.1:${CORE_PORT}/ready"  | (jq . 2>/dev/null || cat) || true

echo
echo "── wireguard ───────────────────────────────────"
sudo wg show 2>/dev/null | grep -E 'interface|latest handshake|allowed ips' || echo "  wg not available"

echo
echo "── audit rows ──────────────────────────────────"
docker compose exec -T postgres psql -U "${POSTGRES_USER:-healer}" -d "${POSTGRES_DB:-healer}" \
  -c "select count(*) as records from audit_records;" 2>/dev/null \
  || echo "  postgres not ready / table missing"