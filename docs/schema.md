# DB設計

不動産情報ライブラリAPI（XIT001/XIT002）のキャッシュと、SEO用集計・有料レポート用の基盤スキーマ。

## ER概要

```
prefectures 1 ── * municipalities 1 ── * districts
                      │
                      ├── * trade_transactions
                      ├── * municipality_trade_stats
                      └── 1 municipality_page_meta

sync_checkpoints（同期進捗）
```

## テーブル

### prefectures
都道府県マスタ（47件・静的シード）。

| 列 | 型 | 説明 |
|---|---|---|
| code | TEXT PK | 2桁都道府県コード（例: `13`） |
| name_ja | TEXT | 東京都 |
| name_en | TEXT | Tokyo |
| slug | TEXT UNIQUE | URL用（例: `tokyo`） |

### municipalities
市区町村マスタ（XIT002から同期）。

| 列 | 型 | 説明 |
|---|---|---|
| code | TEXT PK | 5桁市区町村コード（例: `13101`） |
| prefecture_code | TEXT FK | 都道府県コード |
| name_ja | TEXT | 千代田区 |
| name_en | TEXT | 英語名（APIが返す場合） |
| slug | TEXT | URL用ローマ字（例: `shibuya-ku`）。旧コードURLは301リダイレクト |

### districts
取引データから抽出した地区マスタ。

| 列 | 型 | 説明 |
|---|---|---|
| code | TEXT PK | 地区コード（DistrictCode） |
| municipality_code | TEXT FK | 市区町村コード |
| name | TEXT | 地区名 |

### trade_transactions
XIT001 取引・成約価格の正規化レコード。

| 列 | 型 | 説明 |
|---|---|---|
| id | INTEGER PK | 自動採番 |
| record_hash | TEXT UNIQUE | 重複排除用ハッシュ |
| price_category | TEXT | 不動産取引価格情報 / 成約価格情報 |
| price_classification | TEXT | `01` 取引 / `02` 成約 |
| trade_year | INTEGER | 同期パラメータ年 |
| trade_quarter | INTEGER | 同期パラメータ四半期（1-4） |
| property_type | TEXT | Type（宅地、中古マンション等） |
| region | TEXT | Region（商業地等） |
| municipality_code | TEXT FK | |
| prefecture_name | TEXT | |
| municipality_name | TEXT | |
| district_code | TEXT | |
| district_name | TEXT | |
| trade_price | INTEGER | 円（パース済み） |
| price_per_unit | INTEGER | 坪単価 |
| unit_price | INTEGER | ㎡単価 |
| area | REAL | 面積㎡ |
| total_floor_area | REAL | 延床面積 |
| floor_plan | TEXT | 間取り |
| building_year | TEXT | 建築年（原文保持） |
| structure | TEXT | 構造 |
| city_planning | TEXT | 用途地域 |
| coverage_ratio | REAL | 建ぺい率 |
| floor_area_ratio | REAL | 容積率 |
| period_label | TEXT | Period（例: 2023年第4四半期） |
| remarks | TEXT | 取引の事情等 |
| raw_json | TEXT | 原データJSON（デバッグ用） |
| synced_at | DATETIME | 取り込み日時 |

### municipality_trade_stats
SEOページ用の事前集計（市区町村 × 年 × 四半期 × 種別）。

| 列 | 型 | 説明 |
|---|---|---|
| id | INTEGER PK | |
| municipality_code | TEXT FK | |
| trade_year | INTEGER | |
| trade_quarter | INTEGER | |
| price_classification | TEXT | `01`/`02`/空=合算 |
| property_type | TEXT | 空=全種別 |
| transaction_count | INTEGER | 件数 |
| trade_price_sum | INTEGER | 合計 |
| trade_price_avg | REAL | 平均 |
| trade_price_min | INTEGER | 最小 |
| trade_price_max | INTEGER | 最大 |
| unit_price_avg | REAL | ㎡単価平均 |
| area_avg | REAL | 面積平均 |
| updated_at | DATETIME | |

ユニーク: `(municipality_code, trade_year, trade_quarter, price_classification, property_type)`

### municipality_page_meta
一覧・SEOページ用の最新サマリー。

| 列 | 型 | 説明 |
|---|---|---|
| municipality_code | TEXT PK FK | |
| latest_year | INTEGER | DB内最新年 |
| latest_quarter | INTEGER | DB内最新四半期 |
| total_transactions | INTEGER | 累計件数 |
| recent_avg_price | REAL | 直近4四半期の平均取引価格 |
| stats_updated_at | DATETIME | |

### land_price_points
地価公示（XPT002）の地点データ。

| 列 | 型 | 説明 |
|---|---|---|
| id | INTEGER PK | |
| point_id | INTEGER | 地点ID |
| survey_year | INTEGER | 調査年 |
| municipality_code | TEXT | 市区町村コード |
| location | TEXT | 所在 |
| unit_price | INTEGER | ㎡単価（円） |
| year_on_year_change_rate | REAL | 前年比（%） |
| latitude / longitude | REAL | 地図表示用座標 |
| nearest_station | TEXT | 最寄駅 |

ユニーク: `(point_id, survey_year)`

### sync_checkpoints
API同期の再開ポイント。

| 列 | 型 | 説明 |
|---|---|---|
| id | INTEGER PK | |
| sync_type | TEXT | `municipalities` / `transactions` / `land_prices` |
| prefecture_code | TEXT | |
| municipality_code | TEXT | |
| trade_year | INTEGER | |
| trade_quarter | INTEGER | |
| status | TEXT | pending / done / empty / failed |
| record_count | INTEGER | 取得件数 |
| error_message | TEXT | |
| started_at | DATETIME | |
| finished_at | DATETIME | |

ユニーク: `(sync_type, municipality_code, trade_year, trade_quarter)`

## 同期フロー

1. `seed-prefectures` … 47都道府県を投入（API不要）
2. `sync-municipalities` … XIT002 × 47回
3. `sync-transactions` … XIT001 × 市区町村 × 年 × 四半期
4. `rebuild-stats` … 集計テーブル再計算
5. `retry-failed` … failed チェックポイントの再同期（`--dry-run` で件数確認）

## API呼び出し見積もり

1市区町村・1年・4四半期 = 4リクエスト。  
東京都23区・直近3年 ≈ 23 × 3 × 4 = **276リクエスト**

レート制限対策: リクエスト間スリープ（デフォルト1.5秒）、チェックポイントで再開。
