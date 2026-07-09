#!/usr/bin/env bash
# e-Stat 主要統計を一括取り込み（市区町村レベル）。
# 前提: backend/.env に ESTAT_APP_ID、かつ api.e-stat.go.jp への egress 許可。
#
# 使い方:
#   bash scripts/sync_estat_all.sh            # 全調査
#   DRY=1 bash scripts/sync_estat_all.sh      # 発見した表の一覧のみ（取得なし）
set -euo pipefail
cd "$(dirname "$0")/../backend"

SURVEYS=(census migration housing)
FLAG=""
[ "${DRY:-0}" = "1" ] && FLAG="--list-only"

for s in "${SURVEYS[@]}"; do
  echo "===== survey: $s ====="
  python -m app.sync_cli sync-estat-survey --survey "$s" --municipality-only $FLAG
done

echo "===== status ====="
python -m app.sync_cli status
