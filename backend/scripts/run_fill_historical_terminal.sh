#!/usr/bin/env bash
# macOS Terminal.app から1本だけ fill_historical を前景実行する
set -euo pipefail
cd "$(dirname "$0")/.."

LOG="${LOG:-/tmp/fill_historical.log}"
PIDFILE="${PIDFILE:-/tmp/fill_historical.pid}"
LOCKFILE="${LOCKFILE:-/tmp/fill_historical.lock}"

if [[ -f "$PIDFILE" ]]; then
  old_pid="$(cat "$PIDFILE")"
  if kill -0 "$old_pid" 2>/dev/null; then
    echo "既に実行中です (pid=$old_pid)"
    echo "ログ: $LOG"
    exit 0
  fi
fi

if pgrep -f "scripts/fill_historical.sh" >/dev/null 2>&1; then
  echo "fill_historical.sh が既に動いています。重複起動を中止します。"
  pgrep -fl "fill_historical|sync-transactions" || true
  exit 1
fi

exec 9>"$LOCKFILE"
if ! flock -n 9 2>/dev/null; then
  # macOS には flock が無い環境があるためフォールバック
  if ! sh -c "mkdir \"$LOCKFILE.d\" 2>/dev/null"; then
    echo "別プロセスがロック中です。起動を中止します。"
    exit 1
  fi
  trap 'rmdir "$LOCKFILE.d" 2>/dev/null || true' EXIT
fi

echo $$ > "$PIDFILE"
trap 'rm -f "$PIDFILE"' EXIT

echo "=== fill_historical 開始 $(date) ===" | tee -a "$LOG"
echo "pid=$$, log=$LOG" | tee -a "$LOG"
echo "workers=7, sleep=0.3s (チェックポイントから再開)" | tee -a "$LOG"

bash scripts/fill_historical.sh 2>&1 | tee -a "$LOG"
exit_code="${PIPESTATUS[0]}"

echo "=== fill_historical 終了 $(date) exit=$exit_code ===" | tee -a "$LOG"
exit "$exit_code"
