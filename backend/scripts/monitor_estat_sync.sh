#!/usr/bin/env bash
set -uo pipefail

LOG="${ESTAT_MONITOR_LOG:-../data/estat_monitor.log}"
BACKEND="$(cd "$(dirname "$0")/.." && pwd)"
LOCK="${ESTAT_LOCK_DIR:-$BACKEND/../data/estat_parallel.lockdir}"
MAINLOG="${ESTAT_MAIN_LOG:-$BACKEND/../data/estat_parallel_main.log}"
PY="$BACKEND/.venv/bin/python"
TOTAL=76140
INTERVAL="${ESTAT_MONITOR_INTERVAL:-180}"

log() {
  echo "[$(date '+%Y-%m-%d %H:%M:%S')] $*" >>"$LOG"
}

count_workers() {
  pgrep -f "sync-values-batch" 2>/dev/null | wc -l | tr -d ' '
}

count_done() {
  cd "$BACKEND" || return 1
  "$PY" -c "
from sqlalchemy import func, select
from app.estat.db import EstatSessionLocal, EstatSyncCheckpoint
db = EstatSessionLocal()
print(db.scalar(select(func.count()).where(
    EstatSyncCheckpoint.sync_type == 'values',
    EstatSyncCheckpoint.status == 'done',
)))
db.close()
"
}

restart_sync() {
  log "workers stopped, restarting sync..."
  rm -rf "$LOCK" 2>/dev/null || true
  (
    cd "$BACKEND" || exit 1
    SKIP_META=1 VALUES_WORKERS=20 VALUES_MODE=shard ESTAT_SYNC_SLEEP_SECONDS=0.15 \
      ./scripts/sync_estat_parallel.sh >>"$MAINLOG" 2>&1
  ) &
  log "restart pid=$!"
}

log "monitor started (pid=$$)"

while true; do
  workers="$(count_workers)"
  done_count="$(count_done 2>/dev/null || echo '?')"
  if [[ "$done_count" =~ ^[0-9]+$ ]]; then
    pct="$(awk "BEGIN {printf \"%.1f\", ($done_count / $TOTAL) * 100}")"
    log "workers=$workers done=$done_count (${pct}%)"
    if (( done_count >= TOTAL )); then
      log "sync complete!"
      exit 0
    fi
  else
    log "workers=$workers done=?"
  fi

  if (( workers == 0 )); then
    if [[ -d "$LOCK" ]]; then
      log "lock exists but no workers, clearing stale lock"
      rm -rf "$LOCK"
    fi
    restart_sync
  fi

  sleep "$INTERVAL"
done
