#!/usr/bin/env bash
# Fly.io 本番セットアップ（課金登録後に1回実行）
set -euo pipefail

APP="${FLY_APP:-fudosan-database-jp}"
REGION="${FLY_REGION:-nrt}"
FLY="${FLYCTL:-$HOME/.fly/bin/flyctl}"
ROOT="$(cd "$(dirname "$0")/.." && pwd)"

cd "$ROOT"

echo "=== Fly.io 本番セットアップ: $APP ==="

if ! "$FLY" apps list 2>/dev/null | grep -q "$APP"; then
  echo "[1/6] アプリ作成..."
  "$FLY" apps create "$APP" --org personal
else
  echo "[1/6] アプリは既に存在します"
fi

if ! "$FLY" volumes list -a "$APP" 2>/dev/null | grep -q reinfolib_data; then
  echo "[2/6] ボリューム作成 (20GB)..."
  "$FLY" volumes create reinfolib_data --size 20 --region "$REGION" -a "$APP" --yes
else
  echo "[2/6] ボリュームは既に存在します"
fi

if [[ -f "$ROOT/.env" ]]; then
  echo "[3/6] シークレット設定..."
  # shellcheck disable=SC1091
  set -a && source "$ROOT/.env" && set +a
  [[ -n "${REINFOLIB_API_KEY:-}" ]] && "$FLY" secrets set "REINFOLIB_API_KEY=$REINFOLIB_API_KEY" -a "$APP"
  [[ -n "${GOOGLE_SITE_VERIFICATION:-}" ]] && "$FLY" secrets set "GOOGLE_SITE_VERIFICATION=$GOOGLE_SITE_VERIFICATION" -a "$APP"
  [[ -n "${GOOGLE_SITE_VERIFICATION_FILE:-}" ]] && "$FLY" secrets set "GOOGLE_SITE_VERIFICATION_FILE=$GOOGLE_SITE_VERIFICATION_FILE" -a "$APP"
else
  echo "[3/6] .env がないためシークレットはスキップ（手動で fly secrets set）"
fi

echo "[4/6] デプロイ..."
"$FLY" deploy -a "$APP"

echo "[5/6] カスタムドメイン証明書..."
"$FLY" certs add fudosan-database.jp -a "$APP" 2>/dev/null || true
"$FLY" certs add www.fudosan-database.jp -a "$APP" 2>/dev/null || true
"$FLY" certs list -a "$APP"

echo "[6/6] GitHub Actions 用トークン（手動で FLY_API_TOKEN に登録）:"
"$FLY" tokens create deploy -a "$APP" 2>/dev/null || echo "  fly tokens create deploy -a $APP を実行してください"

echo ""
echo "=== 次のステップ ==="
echo "1. DNS を Fly の指示に従って設定"
echo "2. bash scripts/upload-db-to-fly.sh で DB をアップロード"
echo "3. GSC: https://fudosan-database.jp/sitemap.xml を登録"
echo "4. ヘルスチェック: curl https://fudosan-database.jp/api/health"
