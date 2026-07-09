#!/usr/bin/env bash
# ローカルビルド → gh-pages ブランチへデプロイ（GitHub Pages 本番）
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
SITE_URL="${SITE_URL:-https://fudosan-database.jp}"
WORK="/tmp/fudosan-gh-pages-$$"
JOBS="${JOBS:-4}"
PREWARM_JOBS="${PREWARM_JOBS:-4}"

cd "$ROOT"

echo "=== 購入参考データの事前計算 ==="
python3 tools/prewarm_purchase_insights.py --jobs "$PREWARM_JOBS"

echo "=== 静的サイトビルド (${JOBS} workers) ==="
python3 tools/build_public_site.py --jobs "$JOBS" "$@"

echo "=== gh-pages へ push ==="
rm -rf "$WORK"
cp -a "$ROOT/public_site" "$WORK"
cd "$WORK"
git init -q
git checkout -q -b gh-pages
git add -A
git commit -q -m "Deploy static site $(date -u +%Y-%m-%dT%H:%MZ)"
git push -f "https://github.com/takkenshiken2026-sudo/fudosan-database.jp.git" gh-pages

rm -rf "$WORK"
echo "完了: https://fudosan-database.jp/ （反映まで1〜2分）"
