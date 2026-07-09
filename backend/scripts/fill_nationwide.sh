#!/usr/bin/env bash
# 東京都同期完了後、全国の取引データを投入する
set -euo pipefail
cd "$(dirname "$0")/.."
PY=".venv/bin/python"
FROM_YEAR="${FROM_YEAR:-2023}"
TO_YEAR="${TO_YEAR:-2025}"

wait_pid="${1:-}"
if [[ -n "$wait_pid" ]] && kill -0 "$wait_pid" 2>/dev/null; then
  echo "waiting for pid $wait_pid ..."
  while kill -0 "$wait_pid" 2>/dev/null; do sleep 30; done
fi

echo "=== nationwide sync ${FROM_YEAR}-${TO_YEAR} ==="
$PY -m app.sync_cli plan --from-year "$FROM_YEAR" --to-year "$TO_YEAR"
$PY -m app.sync_cli sync-transactions --from-year "$FROM_YEAR" --to-year "$TO_YEAR"
$PY -m app.sync_cli rebuild-stats
$PY -m app.sync_cli status
