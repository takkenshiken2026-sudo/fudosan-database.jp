#!/usr/bin/env bash
# DB作り込みパイプライン（再開可能）
set -euo pipefail
cd "$(dirname "$0")/.."
PY=".venv/bin/python"

FROM_YEAR="${FROM_YEAR:-2023}"
TO_YEAR="${TO_YEAR:-2025}"
SLEEP="${SYNC_SLEEP_SECONDS:-1.5}"

echo "=== reinfolib DB fill ==="
echo "range: ${FROM_YEAR}-${TO_YEAR}"

$PY -m app.sync_cli init-db
$PY -m app.sync_cli seed-prefectures
$PY -m app.sync_cli sync-municipalities
$PY -m app.sync_cli sync-transactions --from-year "$FROM_YEAR" --to-year "$TO_YEAR" --sleep "$SLEEP"
$PY -m app.sync_cli rebuild-stats
$PY -m app.sync_cli status
