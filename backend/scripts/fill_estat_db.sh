#!/usr/bin/env bash
# e-Stat DB作り込みパイプライン（再開可能・バックグラウンド向け）
set -euo pipefail
cd "$(dirname "$0")/.."
PY=".venv/bin/python"
export PYTHONUNBUFFERED=1

STATS_CODE="${STATS_CODE:-}"
LOG="${ESTAT_FILL_LOG:-../data/estat_fill.log}"

echo "=== e-Stat DB fill ===" | tee -a "$LOG"
echo "started: $(date -Iseconds)" | tee -a "$LOG"
if [[ -n "$STATS_CODE" ]]; then
  echo "stats_code: ${STATS_CODE}" | tee -a "$LOG"
else
  echo "stats_code: ALL" | tee -a "$LOG"
fi

FILL_ARGS=(--skip-catalog)
if [[ -n "$STATS_CODE" ]]; then
  FILL_ARGS+=(--stats-code "$STATS_CODE")
fi

$PY -m app.estat.cli init-db 2>&1 | tee -a "$LOG"
$PY -m app.estat.cli test-api 2>&1 | tee -a "$LOG"
$PY -m app.estat.cli plan ${STATS_CODE:+--stats-code "$STATS_CODE"} 2>&1 | tee -a "$LOG"

echo "--- phase: meta + values ---" | tee -a "$LOG"
$PY -m app.estat.cli fill "${FILL_ARGS[@]}" 2>&1 | tee -a "$LOG"

$PY -m app.estat.cli status 2>&1 | tee -a "$LOG"
echo "finished: $(date -Iseconds)" | tee -a "$LOG"
