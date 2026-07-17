#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
PY=".venv/bin/python"
LOG="${ESTAT_LOG_DIR:-../data/estat_parallel_logs}"
SLEEP="${ESTAT_SYNC_SLEEP_SECONDS:-0.3}"

run_worker() {
  local wid=$1
  shift
  local log="$LOG/values_worker_${wid}.log"
  {
    echo "--- retry $(date -u +%Y-%m-%dT%H:%M:%SZ) ---"
    echo "prefectures: $*"
    for pref in "$@"; do
      echo "[values-worker-${wid}] prefecture ${pref}"
      $PY -m app.estat.cli sync-values-batch --sleep "$SLEEP" --prefecture "$pref"
    done
  } >>"$log" 2>&1
}

run_worker 4 22 23 24 25 26 27 28 &
run_worker 5 29 30 31 32 33 34 35 &
run_worker 7 43 44 45 46 47 &
wait
