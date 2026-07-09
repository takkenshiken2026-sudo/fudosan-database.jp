#!/usr/bin/env bash
# 不動産相場ナビ UI サーバー起動
set -euo pipefail
cd "$(dirname "$0")/.."
PORT="${PORT:-8001}"

if lsof -ti ":$PORT" >/dev/null 2>&1; then
  echo "既にポート $PORT で起動中: http://127.0.0.1:$PORT/"
  exit 0
fi

echo "起動中: http://127.0.0.1:$PORT/"
echo "停止: Ctrl+C"
exec .venv/bin/uvicorn app.main:app --host 127.0.0.1 --port "$PORT" --reload
