#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
WORK="/tmp/fudosan-gh-pages-$$"
JOBS="${JOBS:-4}"

cd "$ROOT"
source backend/.venv/bin/activate

echo "=== 静的サイトビルド (${JOBS} workers, resume) ==="
python3 tools/build_public_site.py --full --jobs "$JOBS" --resume

echo "=== gh-pages へ push ==="
rm -rf "$WORK"
cp -a "$ROOT/public_site" "$WORK"
if [[ ! -f "$WORK/CNAME" ]]; then
  echo "fudosan-database.jp" > "$WORK/CNAME"
fi
cd "$WORK"
git init -q
git checkout -q -b gh-pages
git add -A
git commit -q -m "Deploy static site $(date -u +%Y-%m-%dT%H:%MZ)"
git push -f "https://github.com/takkenshiken2026-sudo/fudosan-database.jp.git" gh-pages
rm -rf "$WORK"
echo "完了: https://fudosan-database.jp/"
