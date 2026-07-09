#!/usr/bin/env bash
# 都道府県単位で並列取得（チェックポイントで再開可能）
set -euo pipefail
cd "$(dirname "$0")/.."
PY=".venv/bin/python"

FROM_YEAR="${FROM_YEAR:-2005}"
TO_YEAR="${TO_YEAR:-2022}"
SLEEP="${SLEEP:-0.3}"
WORKERS="${WORKERS:-7}"

GROUP1="01 02 03 04 05 06 07"
GROUP2="08 09 10 11 12 13 14"
GROUP3="15 16 17 18 19 20 21"
GROUP4="22 23 24 25 26 27 28"
GROUP5="29 30 31 32 33 34 35"
GROUP6="36 37 38 39 40 41 42"
GROUP7="43 44 45 46 47"

sync_group() {
  local group_id="$1"
  shift
  local codes=("$@")
  echo "[worker-${group_id}] start (${#codes[@]} prefectures, sleep=${SLEEP}s)"
  for code in "${codes[@]}"; do
    echo "[worker-${group_id}] prefecture ${code}"
    $PY -m app.sync_cli sync-transactions \
      --prefecture "$code" \
      --from-year "$FROM_YEAR" \
      --to-year "$TO_YEAR" \
      --sleep "$SLEEP"
  done
  echo "[worker-${group_id}] done"
}

echo "=== parallel sync ${FROM_YEAR}-${TO_YEAR} ==="
echo "workers=${WORKERS}, sleep=${SLEEP}s"

pids=()
sync_group 1 $GROUP1 & pids+=($!)
if [[ "$WORKERS" -ge 2 ]]; then sync_group 2 $GROUP2 & pids+=($!); fi
if [[ "$WORKERS" -ge 3 ]]; then sync_group 3 $GROUP3 & pids+=($!); fi
if [[ "$WORKERS" -ge 4 ]]; then sync_group 4 $GROUP4 & pids+=($!); fi
if [[ "$WORKERS" -ge 5 ]]; then sync_group 5 $GROUP5 & pids+=($!); fi
if [[ "$WORKERS" -ge 6 ]]; then sync_group 6 $GROUP6 & pids+=($!); fi
if [[ "$WORKERS" -ge 7 ]]; then sync_group 7 $GROUP7 & pids+=($!); fi

failed=0
for pid in "${pids[@]}"; do
  if ! wait "$pid"; then
    echo "[error] worker pid=$pid exited non-zero" >&2
    failed=$((failed + 1))
  fi
done

if [[ "$failed" -gt 0 ]]; then
  echo "=== parallel sync finished with $failed failed worker(s) ===" >&2
  exit 1
fi

echo "=== parallel sync finished ==="
