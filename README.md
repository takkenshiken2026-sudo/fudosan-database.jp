# 不動産相場ナビ（fudosan-database.jp）

国土交通省 [不動産情報ライブラリ](https://www.reinfolib.mlit.go.jp/) のデータに基づき、全国の不動産取引価格・地価公示・駅乗降客数を検索・閲覧できるサイトです。

## 構成

- **Backend**: Python 3.11 + FastAPI + Jinja2 SSR
- **DB**: SQLite（`data/reinfolib.db`）
- **デプロイ**: Fly.io（東京リージョン `nrt`）

## ローカル開発

```bash
cd backend
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp ../.env.example ../.env   # REINFOLIB_API_KEY を設定

python -m app.sync_cli init-db
python -m app.sync_cli seed-prefectures
bash scripts/run_ui.sh       # http://127.0.0.1:8001/
```

## Fly.io デプロイ

### 1. 初回セットアップ

```bash
# Fly CLI（未インストール時）
curl -L https://fly.io/install.sh | sh

# アプリ作成（初回のみ）
flyctl apps create fudosan-database-jp --org personal
flyctl volumes create reinfolib_data --size 20 --region nrt -a fudosan-database-jp

# シークレット
flyctl secrets set REINFOLIB_API_KEY=xxx -a fudosan-database-jp

# デプロイ
flyctl deploy -a fudosan-database-jp
```

### 2. カスタムドメイン

```bash
flyctl certs add fudosan-database.jp -a fudosan-database-jp
flyctl certs add www.fudosan-database.jp -a fudosan-database-jp
```

DNS で `A` / `AAAA` または CNAME を Fly の指示に従って設定します。

### 3. DB アップロード（初回のみ）

ローカルで同期済みの SQLite（約12GB）をボリュームへ転送します。

```bash
bash scripts/upload-db-to-fly.sh
```

### 4. GitHub Actions 自動デプロイ

リポジトリシークレット `FLY_API_TOKEN` を設定すると、`main` への push で自動デプロイされます。

```bash
flyctl tokens create deploy -a fudosan-database-jp
# → GitHub: Settings → Secrets → FLY_API_TOKEN
```

## データ同期

```bash
cd backend
python -m app.sync_cli status
python -m app.sync_cli sync-transactions --prefecture 13 --from-year 2005 --to-year 2025
bash scripts/sync_stations_parallel.sh
```

## 主要 URL

| パス | 内容 |
|------|------|
| `/` | トップ（全国統計・地価推移） |
| `/price/{都道府県}` | 都道府県別相場 |
| `/price/{都道府県}/{市区町村}` | 市区町村別相場 |
| `/station/{id}` | 駅別乗降客数 |
| `/news/area/{都道府県}` | 地域ニュース |
| `/sitemap.xml` | サイトマップ |
| `/api/health` | ヘルスチェック |

## ライセンス・データ出典

取引価格・地価公示データは国土交通省不動産情報ライブラリに基づきます。利用条件は同サイトの利用規約に従ってください。
