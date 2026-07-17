# SEO artifacts

`sitemap.xml`（および `sitemaps/`）は `tools/build_public_site.py` 実行時に
`public_site/` の生成結果から同期されます。

- 通常ビルド: 都道府県・市区町村・ニュース・ランキングなど（地区・駅は含まない）
- `--full` ビルド: 地区・駅ページも含む

Search Console には **デプロイ済みの** `https://fudosan-database.jp/sitemap.xml` を登録してください。
手編集しないでください。
