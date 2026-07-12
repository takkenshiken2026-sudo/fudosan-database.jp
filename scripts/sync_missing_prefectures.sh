#!/usr/bin/env bash
#
# 取引価格データが未収集の9県（都道府県コード 01〜09）を一括同期する。
#
#   01 北海道 / 02 青森 / 03 岩手 / 04 宮城 / 05 秋田
#   06 山形   / 07 福島 / 08 茨城 / 09 栃木
#
# これらは市区町村マスタ・地価公示は同期済みだが、取引価格情報(XIT001)が
# 0件のためトップの「取引データのある都道府県」から除外されている。
#
# 前提:
#   - backend/ で仮想環境が有効、依存関係インストール済み
#   - .env に REINFOLIB_API_KEY を設定済み（または環境変数で渡す）
#   - data/reinfolib.db が存在（seed-prefectures / sync-municipalities 済み）
#
# 使い方:
#   bash scripts/sync_missing_prefectures.sh
#   FROM_YEAR=2005 TO_YEAR=2025 bash scripts/sync_missing_prefectures.sh
#
# 収集後は集計を再計算し、静的サイトを再ビルド → デプロイすること（末尾参照）。
set -euo pipefail

FROM_YEAR="${FROM_YEAR:-2005}"
TO_YEAR="${TO_YEAR:-2025}"
PREFS=(01 02 03 04 05 06 07 08 09)

cd "$(dirname "$0")/../backend"

if [[ -z "${REINFOLIB_API_KEY:-}" ]] && ! grep -q "^REINFOLIB_API_KEY=." ../.env 2>/dev/null; then
  echo "ERROR: REINFOLIB_API_KEY を .env か環境変数で設定してください" >&2
  exit 1
fi

echo "== 事前見積り（API呼び出し数） =="
for code in "${PREFS[@]}"; do
  python -m app.sync_cli plan --prefecture "$code" --from-year "$FROM_YEAR" --to-year "$TO_YEAR" || true
done

echo
echo "== 取引価格を同期（${FROM_YEAR}〜${TO_YEAR}） =="
for code in "${PREFS[@]}"; do
  echo "--- 都道府県 $code ---"
  # ネットワーク断でも途中再開できるよう skip_done(既定) を活用。失敗時はリトライ。
  for attempt in 1 2 3; do
    if python -m app.sync_cli sync-transactions \
        --prefecture "$code" --from-year "$FROM_YEAR" --to-year "$TO_YEAR"; then
      break
    fi
    echo "retry $attempt for prefecture $code" >&2
    sleep $((attempt * 5))
  done
done

echo
echo "== 集計テーブルを再計算 =="
python -m app.sync_cli rebuild-stats

echo
echo "== 完了。件数確認 =="
python -m app.sync_cli status

cat <<'NEXT'

次の手順（本番反映）:
  1. 静的サイトを再生成（DB必須・全ページで約2〜3時間）
       python3 tools/build_public_site.py --full
  2. gh-pages へデプロイ
       bash scripts/deploy-gh-pages.sh
     （または main への push で CI ビルドが走る運用ならそれに従う）
  3. リトライで残った失敗があれば確認
       cd backend && python -m app.sync_cli retry-failed --sync-type transactions --dry-run
NEXT
