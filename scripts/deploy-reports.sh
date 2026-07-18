#!/usr/bin/env bash
# レポートページだけを既存 public_site に再生成 → gh-pages へ公開（数分）。
# 全ページの再ビルド（deploy-gh-pages.sh）は不要。レポートのテンプレート・生成JS・
# 埋め込みデータを変更したときの高速反映用。
#
# 前提: 一度 scripts/deploy-gh-pages.sh --full でフルビルド済み（public_site が揃っている）。
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
JOBS="${JOBS:-4}"
cd "$ROOT"
export DATABASE_URL="${DATABASE_URL:-sqlite:///$ROOT/data/reinfolib.db}"

if [[ ! -f "$ROOT/public_site/index.html" ]]; then
  echo "ABORT: public_site がありません。先に一度 scripts/deploy-gh-pages.sh --full を実行してください。"
  exit 1
fi

echo "=== レポートページのみ再生成 ==="
python3 tools/rebuild_reports.py --jobs "$JOBS"

echo "=== gh-pages へ push ==="
WORK="/tmp/fudosan-gh-pages-$$"
rm -rf "$WORK"
cp -a "$ROOT/public_site" "$WORK"
if [[ ! -f "$WORK/CNAME" ]]; then
  echo "fudosan-database.jp" > "$WORK/CNAME"
fi
cd "$WORK"
git init -q
git checkout -q -b gh-pages
git add -A
git commit -q -m "Update report pages $(date -u +%Y-%m-%dT%H:%MZ)"
git push -f "https://github.com/takkenshiken2026-sudo/fudosan-database.jp.git" gh-pages

rm -rf "$WORK"
echo "完了: https://fudosan-database.jp/ （反映まで1〜2分）"
