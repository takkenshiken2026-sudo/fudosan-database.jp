#!/usr/bin/env python3
"""静的サイトのビルド出力に「相場シミュレーター」「都道府県ランキング」等の
追加ページ・データ・パッチを上乗せする後処理スクリプト。

deploy-gh-pages.sh が tools/build_public_site.py を実行して public_site/ を生成した
あとに、このスクリプトを `python3 tools/build_custom_overlays.py public_site` として
呼び出す。全処理はべき等（何度実行しても同じ結果）。

生成・変更するもの:
  - static/estimate-data.json         … 全市区町村の種別別㎡単価/平均価格
  - static/estimate-tx/<pref>.json    … 地区別の取引事例（遅延読込用）
  - estimate/index.html               … 相場シミュレーター本体
  - rankings/pref-price/index.html         … 都道府県平均価格ランキング
  - rankings/pref-price-growth/index.html  … 都道府県値上がり率ランキング
  - index.html (パッチ)               … トップに導線＋都道府県ランキングリンク
  - static/site.css (パッチ)          … ランキング表の余白・折り返し
  - sitemaps/sitemap-2.xml (パッチ)   … 追加ページの登録
"""
import json
import os
import re
import statistics
import sys

dec = json.JSONDecoder()
NOW = 2025
TYPES = {'中古マンション等': 'mansion', '宅地(土地と建物)': 'house', '宅地(土地)': 'land'}


# --------------------------------------------------------------------------- #
# helpers
# --------------------------------------------------------------------------- #
def load_muni(path):
    with open(path, encoding='utf-8') as fh:
        d = fh.read()
    m = re.search(r'initMunicipalityCharts\(', d)
    if not m:
        return None
    obj, _ = dec.raw_decode(d[m.end():])
    return obj


def pct(vals, q):
    if not vals:
        return None
    s = sorted(vals)
    i = q * (len(s) - 1)
    lo = int(i)
    frac = i - lo
    return s[lo] if lo + 1 >= len(s) else s[lo] * (1 - frac) + s[lo + 1] * frac


def read(site, rel):
    with open(os.path.join(site, rel), encoding='utf-8') as fh:
        return fh.read()


def write(site, rel, text):
    p = os.path.join(site, rel)
    os.makedirs(os.path.dirname(p), exist_ok=True)
    with open(p, 'w', encoding='utf-8') as fh:
        fh.write(text)


def muni_files(site):
    import glob
    return sorted(glob.glob(os.path.join(site, 'price', '*', '*', 'index.html')))


# --------------------------------------------------------------------------- #
# 1. estimate datasets (per-municipality unit prices + per-prefecture deals)
# --------------------------------------------------------------------------- #
def build_estimate_data(site):
    prefs = {}
    tx = {}
    for f in muni_files(site):
        try:
            js = load_muni(f)
        except Exception:
            continue
        if not js or not js.get('total_transactions'):
            continue
        ps, ms = js['prefecture_slug'], js['slug']
        pname, mname = js['prefecture_name'], js['name_ja']

        # --- per-type unit prices from recent transactions -------------------
        samp = {}
        deals = []
        for t in js.get('recent_transactions', []):
            key = TYPES.get(t['property_type'])
            if not key:
                continue
            a, p = t.get('area'), t.get('trade_price')
            dn = (t.get('district_name') or '').strip()
            yr = None
            if t.get('building_year'):
                mm = re.search(r'(\d{4})', str(t['building_year']))
                if mm and 0 <= NOW - int(mm.group(1)) <= 120:
                    yr = int(mm.group(1))
            rec = samp.setdefault(key, {'unit': [], 'age': [], 'area': []})
            if a and p and a > 0:
                rec['unit'].append(p / a)
                rec['area'].append(a)
            if yr:
                rec['age'].append(NOW - yr)
            deal = {'t': key}
            if dn:
                deal['d'] = dn
            if p:
                deal['p'] = p
            if a:
                deal['a'] = a
            if yr:
                deal['y'] = yr
            if 'p' in deal:
                deals.append(deal)

        # --- robust average price per type from property_stats ---------------
        psagg = {}
        yrs = sorted({r['trade_year'] for r in js.get('property_stats', [])})
        recent_yrs = set(yrs[-3:]) if yrs else set()
        for r in js.get('property_stats', []):
            key = TYPES.get(r['property_type'])
            if not key or r['trade_year'] not in recent_yrs:
                continue
            if r.get('trade_price_avg') and r.get('transaction_count'):
                a = psagg.setdefault(key, [0, 0])
                a[0] += r['trade_price_avg'] * r['transaction_count']
                a[1] += r['transaction_count']

        types_out = {}
        for key in ('mansion', 'house', 'land'):
            rec = samp.get(key)
            avg = round(psagg[key][0] / psagg[key][1]) if key in psagg and psagg[key][1] else None
            units = rec['unit'] if rec else []
            unit = round(statistics.median(units)) if units else None
            if not unit and avg and rec and rec['area']:
                unit = round(avg / statistics.median(rec['area']))
            if not unit:
                continue
            entry = {'u': unit, 'n': len(units)}
            if len(units) >= 6:
                entry['lo'] = round(pct(units, 0.25))
                entry['hi'] = round(pct(units, 0.75))
            if rec and rec['area']:
                entry['a'] = round(statistics.median(rec['area']), 1)
            if rec and rec['age']:
                entry['g'] = int(statistics.median(rec['age']))
            if avg:
                entry['avg'] = avg
            types_out[key] = entry

        if types_out:
            p = prefs.setdefault(ps, {'slug': ps, 'name': pname, 'm': []})
            p['m'].append({'slug': ms, 'name': mname, 't': types_out})
        if deals:
            tx.setdefault(ps, {})[ms] = deals

    out = {'now': NOW, 'prefectures': []}
    for p in prefs.values():
        p['m'].sort(key=lambda x: x['name'])
        out['prefectures'].append(p)
    out['prefectures'].sort(key=lambda x: x['name'])
    write(site, 'static/estimate-data.json',
          json.dumps(out, ensure_ascii=False, separators=(',', ':')))

    txdir = os.path.join(site, 'static', 'estimate-tx')
    os.makedirs(txdir, exist_ok=True)
    for ps, munis in tx.items():
        with open(os.path.join(txdir, ps + '.json'), 'w', encoding='utf-8') as fh:
            json.dump(munis, fh, ensure_ascii=False, separators=(',', ':'))
    print(f'  estimate-data: {sum(len(p["m"]) for p in out["prefectures"])} municipalities, '
          f'{len(tx)} prefecture tx files')
    return out


# --------------------------------------------------------------------------- #
# 2. prefecture ranking dataset + pages
# --------------------------------------------------------------------------- #
def prefecture_ranking_data(site):
    home = read(site, 'index.html')
    m = re.search(r'id="prefecture-map-data">(\[.*?\])</script>', home, re.S)
    mapd = json.loads(m.group(1))

    def yoy(slug):
        p = os.path.join(site, 'price', slug, 'index.html')
        if not os.path.exists(p):
            return None
        with open(p, encoding='utf-8') as fh:
            d = fh.read()
        mm = re.search(r'initPrefectureCharts\(', d)
        if not mm:
            return None
        try:
            obj, _ = dec.raw_decode(d[mm.end():])
        except Exception:
            return None
        ys = [r for r in obj.get('yearly_stats', []) if r.get('trade_price_avg')]
        if len(ys) < 2:
            return None
        a, b = ys[-1]['trade_price_avg'], ys[-2]['trade_price_avg']
        return (a - b) / b * 100

    out = []
    for d in mapd:
        if not d.get('avg_price'):
            continue
        y = yoy(d['slug'])
        if y is None:
            continue
        out.append({'slug': d['slug'], 'name': d['name_ja'],
                    'avg': d['avg_price'], 'cnt': d['total_transactions'], 'yoy': y})
    return out


def fmt_price(yen):
    man = yen / 1e4
    if man >= 10000:
        return f'{man / 10000:.1f}億円'
    return f'{round(man):,}万円'


def fmt_yoy(y):
    color = 'text-red-600' if y >= 0 else 'text-blue-600'
    return f'<span class="{color}">{y:+.1f}%</span>'


def page_shell(site):
    """rankings/price ページから共通の <body>…<main> と </main>…</body> を取り出す。"""
    base = read(site, 'rankings/price/index.html').split('\n')
    body_i = next(i for i, l in enumerate(base) if l.startswith('<body'))
    main_i = next(i for i, l in enumerate(base) if 'id="main-content"' in l)
    footer_i = next(i for i, l in enumerate(base) if '</main>' in l)
    header = '\n'.join(base[body_i:main_i + 1])   # <body> … <main …>
    footer = '\n'.join(base[footer_i:])           # </main> … </body>
    return header, footer


def build_pref_pages(site, data):
    header, footer = page_shell(site)
    N = len(data)

    def head(title, desc, path, itemname, items):
        ld = {"@context": "https://schema.org", "@graph": [
            {"@type": "Organization", "@id": "https://fudosan-database.jp/#organization", "name": "不動産相場ナビ", "url": "https://fudosan-database.jp", "logo": "https://fudosan-database.jp/static/og-default.svg"},
            {"@type": "WebSite", "@id": "https://fudosan-database.jp/#website", "url": "https://fudosan-database.jp", "name": "不動産相場ナビ", "publisher": {"@id": "https://fudosan-database.jp/#organization"}, "inLanguage": "ja-JP", "potentialAction": {"@type": "SearchAction", "target": {"@type": "EntryPoint", "urlTemplate": "https://fudosan-database.jp/search?q={search_term_string}"}, "query-input": "required name=search_term_string"}},
            {"@type": "BreadcrumbList", "itemListElement": [
                {"@type": "ListItem", "position": 1, "name": "不動産相場ナビ", "item": "https://fudosan-database.jp"},
                {"@type": "ListItem", "position": 2, "name": "ランキング", "item": "https://fudosan-database.jp/rankings"},
                {"@type": "ListItem", "position": 3, "name": itemname, "item": f"https://fudosan-database.jp{path}"}]},
            {"@type": "ItemList", "name": itemname, "numberOfItems": len(items), "itemListElement": [
                {"@type": "ListItem", "position": i + 1, "url": f"https://fudosan-database.jp/price/{o['slug']}", "name": o['name']} for i, o in enumerate(items)]}]}
        url = f'https://fudosan-database.jp{path}'
        return f'''<!DOCTYPE html>
<html lang="ja" prefix="og: https://ogp.me/ns#">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{title} | 不動産相場ナビ</title>
  <meta name="description" content="{desc}">
  <meta name="robots" content="index,follow">
  <link rel="canonical" href="{url}">
  <link rel="alternate" hreflang="ja" href="{url}">
  <link rel="alternate" hreflang="x-default" href="{url}">

  <meta property="og:locale" content="ja_JP">
  <meta property="og:site_name" content="不動産相場ナビ">
  <meta property="og:title" content="{title} | 不動産相場ナビ">
  <meta property="og:description" content="{desc}">
  <meta property="og:url" content="{url}">
  <meta property="og:type" content="website">
  <meta property="og:image" content="https://fudosan-database.jp/static/og-default.svg">
  <meta name="twitter:image" content="https://fudosan-database.jp/static/og-default.svg">

  <meta name="twitter:card" content="summary_large_image">
  <meta name="twitter:title" content="{title} | 不動産相場ナビ">
  <meta name="twitter:description" content="{desc}">

  <link rel="icon" href="/static/favicon.svg" type="image/svg+xml">
  <link rel="apple-touch-icon" href="/static/og-default.svg">

  <link rel="preconnect" href="https://fonts.googleapis.com">
  <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
  <link href="https://fonts.googleapis.com/css2?family=Noto+Sans+JP:wght@400;500;600;700&display=swap" rel="stylesheet">

  <script type="application/ld+json">{json.dumps(ld, ensure_ascii=False)}</script>

  <script src="https://cdn.tailwindcss.com"></script>
  <script>
    tailwind.config = {{
      theme: {{
        extend: {{
          colors: {{
            brand: {{ 50:'#f0f9ff',100:'#e0f2fe',400:'#38bdf8',500:'#0ea5e9',600:'#0284c7',700:'#0369a1',800:'#075985',900:'#0c4a6e' }},
            ink: {{ 700:'#334155', 900:'#0f172a' }}
          }},
          fontFamily: {{ sans: ['"Noto Sans JP"', 'sans-serif'] }}
        }}
      }}
    }}
  </script>
  <link rel="stylesheet" href="/static/site.css">
  <script src="/static/site.js" defer></script>

</head>
'''

    def tabs(active):
        def pill(href, label, on):
            cls = 'bg-brand-600 text-white' if on else 'bg-slate-100 text-slate-600 hover:bg-slate-200'
            return (f'      <a href="{href}"\n'
                    f'         class="px-4 py-2 rounded-full text-sm font-medium transition {cls}">\n'
                    f'        {label}\n      </a>')
        return '\n'.join([
            pill('/rankings/pref-price', '平均価格', active == 'price'),
            pill('/rankings/pref-price-growth', '値上がり率', active == 'growth'),
            pill('/rankings', '市区町村ランキング', False)])

    def badge(i):
        cls = f'rank-badge rank-{i}' if i <= 3 else 'rank-badge'
        return f'<span class="{cls}">{i}</span>'

    def build(kind):
        if kind == 'price':
            items = sorted(data, key=lambda x: -x['avg'])
            title = '都道府県平均価格ランキング'
            desc = f'全国都道府県の平均取引価格ランキング（全{N}件）。国土交通省・e-Statデータに基づくランキング。'
            path = '/rankings/pref-price'
            sub, col3, col4, active = '平均取引価格が高い都道府県', '平均価格', '前年比', 'price'
        else:
            items = sorted(data, key=lambda x: -x['yoy'])
            title = '都道府県値上がり率ランキング'
            desc = f'全国都道府県の価格上昇率（前年比）ランキング（全{N}件）。国土交通省・e-Statデータに基づくランキング。'
            path = '/rankings/pref-price-growth'
            sub, col3, col4, active = '平均取引価格の前年比上昇率が高い都道府県', '値上がり率', '平均価格', 'growth'
        crumb = title
        rows = []
        for i, o in enumerate(items, 1):
            if kind == 'price':
                c3, c4 = fmt_price(o['avg']), fmt_yoy(o['yoy'])
            else:
                c3, c4 = fmt_yoy(o['yoy']), fmt_price(o['avg'])
            rows.append(f'''        <tr class="hover:bg-brand-50/30 transition">
          <td class="px-4 py-3 whitespace-nowrap">
            {badge(i)}
          </td>
          <td class="px-4 py-3">
            <a href="/price/{o['slug']}" class="font-medium text-brand-700 hover:underline">
              {o['name']}
            </a>
          </td>
          <td class="px-4 py-3 text-right tabular-nums font-medium">
            {c3}
          </td>
          <td class="px-4 py-3 text-right tabular-nums">
            {c4}
          </td>
          <td class="px-4 py-3 text-right tabular-nums hidden sm:table-cell">
            {o['cnt']:,}
          </td>
        </tr>''')
        content = f'''
<section class="bg-white border-b border-slate-200">
  <div class="max-w-6xl mx-auto px-4 py-8">

<nav class="text-sm text-slate-500 mb-4 flex flex-wrap items-center gap-1" aria-label="パンくず">
      <a href="/" class="hover:text-brand-600 transition">トップ</a>
      <span class="text-slate-300">/</span>
      <a href="/rankings" class="hover:text-brand-600 transition">ランキング</a>
      <span class="text-slate-300">/</span>
      <span class="text-ink-900 font-medium">{crumb}</span>
</nav>


    <h1 class="text-2xl md:text-3xl font-bold">{title}</h1>
    <p class="mt-2 text-slate-600">{sub}<span class="text-slate-400">（全{N}件）</span></p>

    <div class="flex flex-wrap gap-2 mt-6">
{tabs(active)}
    </div>
  </div>
</section>

<section class="max-w-6xl mx-auto px-4 py-8">
  <div class="overflow-hidden rounded-xl border border-slate-200 bg-white shadow-sm">
    <div class="overflow-x-auto">
    <table class="w-full text-sm">
      <thead class="bg-slate-50 text-left text-slate-600">
        <tr>
          <th class="px-4 py-3 w-14 font-medium whitespace-nowrap">順位</th>
          <th class="px-4 py-3 font-medium">都道府県</th>
          <th class="px-4 py-3 text-right font-medium">{col3}</th>
          <th class="px-4 py-3 text-right font-medium">{col4}</th>
          <th class="px-4 py-3 text-right font-medium hidden sm:table-cell">
            累計件数
          </th>
        </tr>
      </thead>
      <tbody class="divide-y divide-slate-100">
{chr(10).join(rows)}
      </tbody>
    </table>
    </div>
  </div>
  <p class="mt-4 text-xs text-slate-400">
    値上がり率（前年比）は直近2年の平均取引価格比較。平均価格・累計件数は国土交通省の取引価格情報に基づく集計値です。データのない都道府県は除外しています。
  </p>
</section>
'''
        return path.strip('/'), head(title, desc, path, crumb, items) + header + content + '\n' + footer

    for kind in ('price', 'growth'):
        rel, page = build(kind)
        write(site, rel + '/index.html', page)
    print(f'  prefecture ranking pages: {N} prefectures')
    return N


# --------------------------------------------------------------------------- #
# 3. estimate simulator page
# --------------------------------------------------------------------------- #
def build_estimate_page(site):
    header, footer = page_shell(site)
    tmpl_path = os.path.join(os.path.dirname(__file__), 'custom_estimate_page.html')
    with open(tmpl_path, encoding='utf-8') as fh:
        tmpl = fh.read()
    head_part, content_part = tmpl.split('\n<!--CUSTOM-HEADER-SLOT-->\n')
    page = head_part + '\n' + header + '\n' + content_part + '\n' + footer
    write(site, 'estimate/index.html', page)
    print('  estimate page: written')


# --------------------------------------------------------------------------- #
# 4. patches to generated files (idempotent)
# --------------------------------------------------------------------------- #
def patch_home(site, pref_n):
    rel = 'index.html'
    d = read(site, rel)
    changed = False

    # 4a. action card + grid 4->5
    if '/estimate' not in d:
        old = ('  <div class="grid sm:grid-cols-2 lg:grid-cols-4 gap-3">\n'
               '    <a href="#market-overview" class="home-action-card">')
        new = ('  <div class="grid sm:grid-cols-2 lg:grid-cols-5 gap-3">\n'
               '    <a href="/estimate" class="home-action-card ring-2 ring-brand-500 bg-brand-50/60">\n'
               '      <svg class="w-5 h-5 text-brand-600" fill="none" stroke="currentColor" viewBox="0 0 24 24" aria-hidden="true"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M9 7h6m-6 4h6m-6 4h4M5 3h14a2 2 0 012 2v14a2 2 0 01-2 2H5a2 2 0 01-2-2V5a2 2 0 012-2z"/></svg>\n'
               '      <span class="font-semibold text-sm">相場シミュレーター</span>\n'
               '    </a>\n'
               '    <a href="#market-overview" class="home-action-card">')
        if old in d:
            d = d.replace(old, new, 1)
            changed = True

    # 4b. prefecture ranking links in the 都道府県ランキング header
    if 'pref-price' not in d:
        old = ('  <div class="max-w-6xl mx-auto px-4 py-14">\n'
               '    \n'
               '<div class="mb-6">\n'
               '  <h2 class="text-xl font-bold text-ink-900">都道府県ランキング</h2>\n'
               '  <p class="mt-1 text-sm text-slate-500">クリックで市区町村一覧へ</p>\n'
               '</div>\n'
               '\n'
               '    <div class="grid lg:grid-cols-2 gap-8">')
        new = (f'  <div class="max-w-6xl mx-auto px-4 py-14">\n'
               f'    <div class="flex flex-col sm:flex-row sm:items-end sm:justify-between gap-4 mb-6">\n'
               f'\n'
               f'<div class="mb-6">\n'
               f'  <h2 class="text-xl font-bold text-ink-900">都道府県ランキング</h2>\n'
               f'  <p class="mt-1 text-sm text-slate-500">クリックで市区町村一覧へ</p>\n'
               f'</div>\n'
               f'\n'
               f'      <div class="flex gap-2 shrink-0">\n'
               f'        <a href="/rankings/pref-price" class="text-sm text-brand-600 font-medium hover:underline">価格順 全{pref_n}件 →</a>\n'
               f'        <span class="text-slate-300">|</span>\n'
               f'        <a href="/rankings/pref-price-growth" class="text-sm text-brand-600 font-medium hover:underline">値上がり率 全{pref_n}件 →</a>\n'
               f'      </div>\n'
               f'    </div>\n'
               f'    <div class="grid lg:grid-cols-2 gap-8">')
        if old in d:
            d = d.replace(old, new, 1)
            changed = True

    if changed:
        write(site, rel, d)
    print(f'  home patch: {"applied" if changed else "already present"}')


def patch_css(site):
    rel = 'static/site.css'
    d = read(site, rel)
    if 'ランキングテーブル' in d or '.rank-table--compact tbody tr:first-child' in d:
        print('  css patch: already present')
        return
    old = ('.rank-table--compact th,\n'
           '.rank-table--compact td {\n'
           '  padding-top: 0.2rem;\n'
           '  padding-bottom: 0.2rem;\n'
           '  line-height: 1.25;\n'
           '}')
    new = ('.rank-table--compact th,\n'
           '.rank-table--compact td {\n'
           '  padding-top: 0.2rem;\n'
           '  padding-bottom: 0.2rem;\n'
           '  line-height: 1.25;\n'
           '  white-space: nowrap;\n'
           '}\n'
           '\n'
           '/* ランキングテーブルの上下に少し余白を持たせる */\n'
           '.rank-table--compact thead th {\n'
           '  padding-top: 0.5rem;\n'
           '  padding-bottom: 0.5rem;\n'
           '}\n'
           '\n'
           '.rank-table--compact tbody tr:first-child td {\n'
           '  padding-top: 0.55rem;\n'
           '}\n'
           '\n'
           '.rank-table--compact tbody tr:last-child td {\n'
           '  padding-bottom: 0.6rem;\n'
           '}')
    if old in d:
        write(site, rel, d.replace(old, new, 1))
        print('  css patch: applied')
    else:
        print('  css patch: WARNING anchor not found (skipped)')


def patch_sitemap(site):
    rel = 'sitemaps/sitemap-2.xml'
    p = os.path.join(site, rel)
    if not os.path.exists(p):
        print('  sitemap patch: file not found (skipped)')
        return
    d = read(site, rel)
    if '/estimate</loc>' in d:
        print('  sitemap patch: already present')
        return
    anchor = ('    <loc>https://fudosan-database.jp/rankings</loc>\n'
              '    <changefreq>daily</changefreq>\n'
              '    <priority>0.9</priority>\n'
              '  </url>')
    add = anchor + ('\n  <url>\n'
                    '    <loc>https://fudosan-database.jp/estimate</loc>\n'
                    '    <changefreq>weekly</changefreq>\n'
                    '    <priority>0.9</priority>\n'
                    '  </url>\n'
                    '  <url>\n'
                    '    <loc>https://fudosan-database.jp/rankings/pref-price</loc>\n'
                    '    <changefreq>daily</changefreq>\n'
                    '    <priority>0.8</priority>\n'
                    '  </url>\n'
                    '  <url>\n'
                    '    <loc>https://fudosan-database.jp/rankings/pref-price-growth</loc>\n'
                    '    <changefreq>daily</changefreq>\n'
                    '    <priority>0.8</priority>\n'
                    '  </url>')
    if anchor in d:
        write(site, rel, d.replace(anchor, add, 1))
        print('  sitemap patch: applied')
    else:
        print('  sitemap patch: WARNING anchor not found (skipped)')


# --------------------------------------------------------------------------- #
def main():
    if len(sys.argv) < 2:
        print('usage: build_custom_overlays.py <site_dir>')
        sys.exit(1)
    site = sys.argv[1].rstrip('/')
    if not os.path.isdir(os.path.join(site, 'price')):
        print(f'error: {site} does not look like a built site (no price/ dir)')
        sys.exit(1)
    print(f'== custom overlays -> {site} ==')
    build_estimate_data(site)
    pref = prefecture_ranking_data(site)
    n = build_pref_pages(site, pref)
    build_estimate_page(site)
    patch_home(site, n)
    patch_css(site)
    patch_sitemap(site)
    print('== done ==')


if __name__ == '__main__':
    main()
