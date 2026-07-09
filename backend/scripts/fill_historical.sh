#!/usr/bin/env bash
# 過去取引(2005-2022) → 集計 → 地価公示(2005-2025)
set -euo pipefail
cd "$(dirname "$0")/.."
PY=".venv/bin/python"

echo "=== historical transactions 2005-2022 (7 parallel, sleep 0.3s) ==="
WORKERS=7 SLEEP=0.3 bash scripts/sync_transactions_parallel.sh
$PY -m app.sync_cli rebuild-stats

echo "=== land prices 2005-2025 (7 parallel, skip empty tiles, sleep 0.3s) ==="
$PY -m app.sync_cli plan-land-prices --from-year 2005 --to-year 2025 --sleep 0.3
WORKERS=7 SLEEP=0.3 bash scripts/sync_land_prices_parallel.sh
$PY -m app.sync_cli status
