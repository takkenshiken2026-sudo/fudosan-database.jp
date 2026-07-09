#!/usr/bin/env bash
# fill_historical を Cursor/ターミナルセッションから切り離して起動する
set -euo pipefail
cd "$(dirname "$0")/.."

LOG="${LOG:-/tmp/fill_historical.log}"
PIDFILE="${PIDFILE:-/tmp/fill_historical.pid}"

if [[ -f "$PIDFILE" ]]; then
  old_pid="$(cat "$PIDFILE")"
  if kill -0 "$old_pid" 2>/dev/null; then
    echo "already running (pid=$old_pid)"
    exit 0
  fi
fi

# サブシェルで起動し、親シェル終了の影響を受けないようにする
sh -c "nohup bash scripts/fill_historical.sh >> '$LOG' 2>&1 & echo \$! > '$PIDFILE'"

sleep 1
if [[ -f "$PIDFILE" ]]; then
  echo "started pid=$(cat "$PIDFILE"), log=$LOG"
else
  echo "failed to start (see $LOG)"
  exit 1
fi
