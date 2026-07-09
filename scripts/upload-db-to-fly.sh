#!/usr/bin/env bash
# ローカルの SQLite DB を Fly.io ボリュームへアップロード（初回デプロイ後に1回実行）
set -euo pipefail

APP="${FLY_APP:-fudosan-database-jp}"
LOCAL_DB="${LOCAL_DB:-$(cd "$(dirname "$0")/.." && pwd)/data/reinfolib.db}"
REMOTE_DB="/app/data/reinfolib.db"
FLY="${FLYCTL:-$HOME/.fly/bin/flyctl}"

if [[ ! -f "$LOCAL_DB" ]]; then
  echo "ローカルDBが見つかりません: $LOCAL_DB" >&2
  exit 1
fi

echo "=== Fly.io DB アップロード ==="
echo "app: $APP"
echo "local: $LOCAL_DB ($(du -h "$LOCAL_DB" | cut -f1))"
echo ""
echo "マシンを起動して SFTP で転送します（12GB 規模では数十分かかります）..."

"$FLY" machine list -a "$APP" --json | python3 -c "
import json, sys
machines = json.load(sys.stdin)
running = [m for m in machines if m.get('state') == 'started']
if not running:
    print('起動中のマシンがありません。先に fly deploy を実行してください。', file=sys.stderr)
    sys.exit(1)
print(running[0]['id'])
" > /tmp/fly_machine_id.txt

MACHINE_ID=$(cat /tmp/fly_machine_id.txt)
echo "machine: $MACHINE_ID"

# WAL をチェックポイントしてから転送
sqlite3 "$LOCAL_DB" "PRAGMA wal_checkpoint(TRUNCATE);" 2>/dev/null || true

"$FLY" ssh console -a "$APP" -s -C "mkdir -p /app/data"

echo "SFTP 転送開始..."
"$FLY" ssh sftp shell -a "$APP" -s <<EOF
put "$LOCAL_DB" "$REMOTE_DB"
bye
EOF

echo "完了。ヘルスチェック:"
"$FLY" ssh console -a "$APP" -s -C "ls -lh /app/data/reinfolib.db"
curl -fsS "https://${APP}.fly.dev/api/health" || curl -fsS "https://fudosan-database.jp/api/health" || true
echo ""
echo "https://fudosan-database.jp/ を確認してください。"
