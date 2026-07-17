#!/usr/bin/env bash
# e-Stat DB 並列作り込み（チェックポイントで再開可能）
set -euo pipefail
cd "$(dirname "$0")/.."
PY=".venv/bin/python"
export PYTHONUNBUFFERED=1

META_WORKERS="${META_WORKERS:-8}"
VALUES_WORKERS="${VALUES_WORKERS:-20}"
SLEEP="${ESTAT_SYNC_SLEEP_SECONDS:-0.15}"
STATS_CODE="${STATS_CODE:-}"
LOG_DIR="${ESTAT_LOG_DIR:-../data/estat_parallel_logs}"
SKIP_META="${SKIP_META:-0}"
SKIP_VALUES="${SKIP_VALUES:-0}"
VALUES_MODE="${VALUES_MODE:-shard}"  # shard | prefecture

mkdir -p "$LOG_DIR"
LOCK_DIR="${ESTAT_LOCK_DIR:-../data/estat_parallel.lockdir}"
if ! mkdir "$LOCK_DIR" 2>/dev/null; then
  echo "Another sync_estat_parallel.sh is already running (lock: $LOCK_DIR)" >&2
  exit 1
fi
trap 'rmdir "$LOCK_DIR" 2>/dev/null || true' EXIT

GROUP1="01 02 03 04 05 06 07"
GROUP2="08 09 10 11 12 13 14"
GROUP3="15 16 17 18 19 20 21"
GROUP4="22 23 24 25 26 27 28"
GROUP5="29 30 31 32 33 34 35"
GROUP6="36 37 38 39 40 41 42"
GROUP7="43 44 45 46 47"

stats_code_args() {
  if [[ -n "$STATS_CODE" ]]; then
    printf '%s' --stats-code "$STATS_CODE"
  fi
}

run_meta_worker() {
  local worker_id="$1"
  local log="$LOG_DIR/meta_worker_${worker_id}.log"
  echo "[meta-worker-${worker_id}] start -> ${log}"
  # shellcheck disable=SC2046
  $PY -m app.estat.cli sync-meta-all \
    --sleep "$SLEEP" \
    $(stats_code_args) \
    --worker-id "$worker_id" \
    --worker-count "$META_WORKERS" \
    >"$log" 2>&1
  echo "[meta-worker-${worker_id}] done"
}

run_values_shard_worker() {
  local worker_id="$1"
  local log="$LOG_DIR/values_shard_${worker_id}.log"
  echo "[values-shard-${worker_id}] start -> ${log}"
  # shellcheck disable=SC2046
  $PY -m app.estat.cli sync-values-batch \
    --sleep "$SLEEP" \
    $(stats_code_args) \
    --worker-id "$worker_id" \
    --worker-count "$VALUES_WORKERS" \
    >"$log" 2>&1
  echo "[values-shard-${worker_id}] done"
}

run_values_worker() {
  local worker_id="$1"
  shift
  local prefs=("$@")
  local log="$LOG_DIR/values_worker_${worker_id}.log"
  echo "[values-worker-${worker_id}] start (${#prefs[@]} prefectures) -> ${log}"
  {
    echo "prefectures: ${prefs[*]}"
    for pref in "${prefs[@]}"; do
      echo "[values-worker-${worker_id}] prefecture ${pref}"
      # shellcheck disable=SC2046
      $PY -m app.estat.cli sync-values-batch \
        --sleep "$SLEEP" \
        $(stats_code_args) \
        --prefecture "$pref"
    done
  } >"$log" 2>&1
  echo "[values-worker-${worker_id}] done"
}

echo "=== e-Stat parallel fill ==="
echo "meta_workers=${META_WORKERS}, values_workers=${VALUES_WORKERS}, values_mode=${VALUES_MODE}, sleep=${SLEEP}s"
if [[ -n "$STATS_CODE" ]]; then
  echo "stats_code=${STATS_CODE}"
fi

$PY -m app.estat.cli init-db
# shellcheck disable=SC2046
$PY -m app.estat.cli plan $(stats_code_args)

pids=()
if [[ "$SKIP_META" != "1" ]]; then
  echo "--- phase: meta (${META_WORKERS} workers) ---"
  for ((i = 0; i < META_WORKERS; i++)); do
    run_meta_worker "$i" &
    pids+=("$!")
  done
fi

failed=0
if (( ${#pids[@]} > 0 )); then
  for pid in "${pids[@]}"; do
    if ! wait "$pid"; then
      echo "[error] meta worker pid=$pid failed" >&2
      failed=$((failed + 1))
    fi
  done
fi
pids=()

if [[ "$SKIP_VALUES" != "1" ]]; then
  echo "--- phase: values (${VALUES_WORKERS} workers, mode=${VALUES_MODE}) ---"
  if [[ "$VALUES_MODE" == "shard" ]]; then
    for ((i = 0; i < VALUES_WORKERS; i++)); do
      run_values_shard_worker "$i" &
      pids+=("$!")
    done
  else
    run_values_worker 1 $GROUP1 & pids+=("$!")
    if [[ "$VALUES_WORKERS" -ge 2 ]]; then run_values_worker 2 $GROUP2 & pids+=("$!"); fi
    if [[ "$VALUES_WORKERS" -ge 3 ]]; then run_values_worker 3 $GROUP3 & pids+=("$!"); fi
    if [[ "$VALUES_WORKERS" -ge 4 ]]; then run_values_worker 4 $GROUP4 & pids+=("$!"); fi
    if [[ "$VALUES_WORKERS" -ge 5 ]]; then run_values_worker 5 $GROUP5 & pids+=("$!"); fi
    if [[ "$VALUES_WORKERS" -ge 6 ]]; then run_values_worker 6 $GROUP6 & pids+=("$!"); fi
    if [[ "$VALUES_WORKERS" -ge 7 ]]; then run_values_worker 7 $GROUP7 & pids+=("$!"); fi
  fi
fi

if (( ${#pids[@]} > 0 )); then
  for pid in "${pids[@]}"; do
    if ! wait "$pid"; then
      echo "[error] values worker pid=$pid failed" >&2
      failed=$((failed + 1))
    fi
  done
fi

$PY -m app.estat.cli status
# shellcheck disable=SC2046
$PY -m app.estat.cli plan $(stats_code_args)

if [[ "$failed" -gt 0 ]]; then
  echo "=== finished with ${failed} failed worker(s) ===" >&2
  echo "logs: ${LOG_DIR}" >&2
  exit 1
fi

echo "=== parallel fill finished ==="
echo "logs: ${LOG_DIR}"
