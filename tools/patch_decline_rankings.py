#!/usr/bin/env python3
"""本番 gh-pages に「値下がり率トップ10」を追加する後処理。

既存の静的 HTML（都道府県・市区町村ページ埋め込みチャートデータ）から
平均取引価格の前年比を計算し、トップページとランキングページへ反映する。
DB 不要・べき等。

使い方:
    python3 tools/patch_decline_rankings.py /path/to/gh-pages-or-public_site
"""
from __future__ import annotations

import json
import os
import re
import sys
from pathlib import Path

dec = json.JSONDecoder()
LIMIT = 10
FULL_LIMIT = 50

RANK_CARD_TITLES = {
    "平均価格トップ10": "不動産平均取引価格トップ10",
    "値上がり率トップ10": "不動産取引価格 値上がり率トップ10",
    "値下がり率トップ10": "不動産取引価格 値下がり率トップ10",
}


def card_header(title: str) -> str:
    display = RANK_CARD_TITLES.get(title, title)
    return f'''        <div class="px-3 py-1.5 border-b border-slate-100 bg-slate-50">
          <h3 class="text-sm font-semibold text-slate-700 leading-tight">{display}</h3>
        </div>'''


def read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def fmt_price(yen: float | int | None) -> str:
    if yen is None:
        return "—"
    man = yen / 1e4
    if man >= 10000:
        return f"{man / 10000:.1f}億円"
    return f"{round(man):,}万円"


def fmt_yoy_html(y: float, *, emphasize: bool = False) -> str:
    color = "text-red-600" if y >= 0 else "text-blue-600"
    cls = f'{color}{" font-medium" if emphasize else ""}'
    return f'<span class="{cls}">{y:+.1f}%</span>'


def badge(i: int, *, sm: bool = True) -> str:
    size = " rank-badge--sm" if sm else ""
    if i <= 3:
        return f'<span class="rank-badge{size} rank-{i}">{i}</span>'
    return f'<span class="rank-badge{size}">{i}</span>'


def yoy_from_yearly(yearly: list[dict]) -> float | None:
    ys = [r for r in yearly if r.get("trade_price_avg")]
    if len(ys) < 2:
        return None
    a, b = ys[-1]["trade_price_avg"], ys[-2]["trade_price_avg"]
    if not b:
        return None
    return (a - b) / b * 100


def load_chart(html: str, fn: str) -> dict | None:
    m = re.search(rf"{re.escape(fn)}\(", html)
    if not m:
        return None
    try:
        obj, _ = dec.raw_decode(html[m.end() :])
        return obj
    except Exception:
        return None


def collect_prefectures(site: Path) -> list[dict]:
    home = read(site / "index.html")
    m = re.search(r'id="prefecture-map-data">(\[.*?\])</script>', home, re.S)
    if not m:
        # fallback: scan price/*/index.html
        prefs = []
        for p in sorted((site / "price").glob("*/index.html")):
            if (p.parent / p.parent.name).exists():
                pass
            obj = load_chart(read(p), "initPrefectureCharts")
            if not obj:
                continue
            y = yoy_from_yearly(obj.get("yearly_stats") or [])
            if y is None:
                continue
            prefs.append(
                {
                    "slug": obj.get("slug") or p.parent.name,
                    "name": obj.get("name_ja") or p.parent.name,
                    "avg": obj.get("avg_price"),
                    "cnt": int(obj.get("total_transactions") or 0),
                    "yoy": y,
                }
            )
        return prefs

    mapd = json.loads(m.group(1))
    out = []
    for d in mapd:
        slug = d.get("slug")
        if not slug or not d.get("avg_price"):
            continue
        page = site / "price" / slug / "index.html"
        if not page.exists():
            continue
        obj = load_chart(read(page), "initPrefectureCharts")
        if not obj:
            continue
        y = yoy_from_yearly(obj.get("yearly_stats") or [])
        if y is None:
            continue
        out.append(
            {
                "slug": slug,
                "name": d.get("name_ja") or slug,
                "avg": d.get("avg_price"),
                "cnt": int(d.get("total_transactions") or 0),
                "yoy": y,
            }
        )
    return out


def collect_municipalities(site: Path, *, min_year_n: int = 80) -> list[dict]:
    out = []
    for page in sorted((site / "price").glob("*/*/index.html")):
        html = read(page)
        obj = load_chart(html, "initMunicipalityCharts")
        if not obj:
            continue
        yearly = obj.get("yearly_stats") or []
        y = yoy_from_yearly(yearly)
        if y is None:
            continue
        recent = [r for r in yearly if r.get("trade_price_avg")]
        last_n = int(recent[-1].get("transaction_count") or 0)
        prev_n = int(recent[-2].get("transaction_count") or 0)
        if last_n < min_year_n or prev_n < min_year_n:
            continue
        avg = obj.get("recent_avg_price")
        if avg is None:
            avg = recent[-1]["trade_price_avg"]
        cnt = int(obj.get("total_transactions") or 0)
        if cnt <= 0:
            continue
        out.append(
            {
                "pref_slug": obj.get("prefecture_slug") or page.parent.parent.name,
                "slug": obj.get("slug") or page.parent.name,
                "name": obj.get("name_ja") or page.parent.name,
                "pref_name": obj.get("prefecture_name") or page.parent.parent.name,
                "avg": avg,
                "cnt": cnt,
                "yoy": y,
                "last_n": last_n,
                "prev_n": prev_n,
            }
        )
    return out


def pref_row(o: dict, rank: int) -> str:
    return f'''  <tr class="hover:bg-brand-50/40 transition cursor-pointer group" onclick="location.href='/price/{o["slug"]}'">
    <td class="px-2 py-0">
      {badge(rank)}
    </td>
    <td class="px-2 py-0 font-medium group-hover:text-brand-700">{o["name"]}</td>
    <td class="px-2 py-0 text-right tabular-nums text-brand-700">{fmt_price(o["avg"])}</td>
    <td class="px-2 py-0 text-right tabular-nums font-medium">
      {fmt_yoy_html(o["yoy"])}
    </td>
  </tr>
'''


def muni_row(o: dict, rank: int) -> str:
    return f'''  <tr class="hover:bg-brand-50/40 transition cursor-pointer group" onclick="location.href='/price/{o["pref_slug"]}/{o["slug"]}'">
    <td class="px-2 py-0">
      {badge(rank)}
    </td>
    <td class="px-2 py-0">
      <span class="font-medium text-ink-900 group-hover:text-brand-700">{o["name"]}</span>
      <span class="block text-xs text-slate-400 sm:hidden">{o["pref_name"]}</span>
    </td>
    <td class="px-2 py-0 text-slate-500 hidden sm:table-cell">{o["pref_name"]}</td>
    <td class="px-2 py-0 text-right tabular-nums text-brand-700">{fmt_price(o["avg"])}</td>
    <td class="px-2 py-0 text-right tabular-nums font-medium">
      {fmt_yoy_html(o["yoy"])}
    </td>
  </tr>
'''


def pref_card(title: str, rows_html: str) -> str:
    return f'''      <div class="overflow-hidden rounded-xl border border-slate-200 bg-white shadow-sm">
{card_header(title)}
        <div class="overflow-x-auto">
          <table class="w-full text-sm rank-table--compact">
            <thead class="bg-white text-slate-500 text-left border-b border-slate-100">
              <tr>
                <th class="px-2 py-0 w-10">順位</th>
                <th class="px-2 py-0">都道府県</th>
                <th class="px-2 py-0 text-right">平均価格</th>
                <th class="px-2 py-0 text-right">前年比</th>
              </tr>
            </thead>
            
<tbody class="divide-y divide-slate-100">
{rows_html}</tbody>

          </table>
        </div>
      </div>
'''


def muni_card(title: str, rows_html: str) -> str:
    return f'''    <div class="overflow-hidden rounded-xl border border-slate-200 bg-white shadow-sm">
{card_header(title)}
      <div class="overflow-x-auto">
        <table class="w-full text-sm rank-table--compact">
          <thead class="bg-white text-slate-500 text-left border-b border-slate-100">
            <tr>
              <th class="px-2 py-0 w-10">順位</th>
              <th class="px-2 py-0">市区町村</th>
              <th class="px-2 py-0 hidden sm:table-cell">都道府県</th>
              <th class="px-2 py-0 text-right">平均価格</th>
              <th class="px-2 py-0 text-right">前年比</th>
            </tr>
          </thead>
          
<tbody class="divide-y divide-slate-100">
{rows_html}</tbody>

        </table>
      </div>
    </div>
'''


def patch_home(site: Path, prefs: list[dict], munis: list[dict]) -> None:
    path = site / "index.html"
    html = read(path)

    if "値下がり率トップ10" in html:
        print("  home: 値下がり率トップ10 already present")
        return

    pref_losers = sorted(prefs, key=lambda x: x["yoy"])[:LIMIT]
    muni_losers = sorted(munis, key=lambda x: x["yoy"])[:LIMIT]

    pref_card_html = pref_card(
        "値下がり率トップ10",
        "".join(pref_row(o, i) for i, o in enumerate(pref_losers, 1)),
    )
    muni_card_html = muni_card(
        "値下がり率トップ10",
        "".join(muni_row(o, i) for i, o in enumerate(muni_losers, 1)),
    )

    pref_sec_start = html.find("都道府県ランキング")
    muni_sec_start = html.find('id="rankings"')
    if pref_sec_start < 0 or muni_sec_start < 0:
        raise SystemExit("home: ranking sections not found")

    old_grid = '<div class="grid lg:grid-cols-2 gap-8">'
    close = "    </div>\n  </div>\n</section>"

    pref_sec = html[pref_sec_start:muni_sec_start]
    if '値上がり率トップ10' not in pref_sec:
        raise SystemExit("home: prefecture 値上がり率カードが見つかりません")
    if old_grid not in pref_sec:
        raise SystemExit("home: pref grid not found")
    new_pref_sec = pref_sec.replace(
        old_grid, '<div class="grid lg:grid-cols-2 xl:grid-cols-3 gap-8">', 1
    )
    cidx = new_pref_sec.rfind(close)
    if cidx < 0:
        raise SystemExit("home: pref section close not found")
    new_pref_sec = new_pref_sec[:cidx] + pref_card_html + "\n" + new_pref_sec[cidx:]

    muni_sec = html[muni_sec_start:]
    if 'href="/rankings/price-growth"' in muni_sec and "price-decline" not in muni_sec:
        muni_sec = muni_sec.replace(
            '<a href="/rankings/price-growth" class="text-sm text-brand-600 font-medium hover:underline">値上がり率 全50件 →</a>',
            '<a href="/rankings/price-growth" class="text-sm text-brand-600 font-medium hover:underline">値上がり率 全50件 →</a>\n'
            '      <span class="text-slate-300">|</span>\n'
            '      <a href="/rankings/price-decline" class="text-sm text-brand-600 font-medium hover:underline">値下がり率 全50件 →</a>',
            1,
        )
    if old_grid not in muni_sec:
        raise SystemExit("home: muni grid not found")
    muni_sec = muni_sec.replace(
        old_grid, '<div class="grid lg:grid-cols-2 xl:grid-cols-3 gap-8">', 1
    )
    m_anchor = muni_sec.find(
        '        <h3 class="text-sm font-semibold text-slate-700">値上がり率トップ10</h3>'
    )
    if m_anchor < 0:
        raise SystemExit("home: municipality 値上がり率カードが見つかりません")
    next_sec = muni_sec.find("\n</section>", m_anchor)
    if next_sec < 0:
        raise SystemExit("home: muni section end not found")
    chunk = muni_sec[: next_sec + len("\n</section>")]
    insert_at = chunk.rfind("  </div>\n</section>")
    if insert_at < 0:
        raise SystemExit("home: muni grid close not found")
    new_chunk = chunk[:insert_at] + muni_card_html + "\n" + chunk[insert_at:]
    muni_sec = new_chunk + muni_sec[next_sec + len("\n</section>") :]

    write(path, html[:pref_sec_start] + new_pref_sec + muni_sec)
    print(
        f"  home: added 値下がり率トップ10 "
        f"(pref={len(pref_losers)}, muni={len(muni_losers)})"
    )


def build_decline_page(site: Path, munis: list[dict]) -> None:
    src = site / "rankings" / "price-growth" / "index.html"
    if not src.exists():
        print("  decline page: price-growth template missing (skipped)")
        return
    html = read(src)
    items = sorted(munis, key=lambda x: x["yoy"])[:FULL_LIMIT]

    # Retitle
    html = html.replace("市区町村価格上昇率ランキング", "市区町村価格下落率ランキング")
    html = html.replace("価格上昇率ランキング", "価格下落率ランキング")
    html = html.replace("価格上昇率", "価格下落率")
    html = html.replace("/rankings/price-growth", "/rankings/price-decline")
    # Fix tab highlight: after replace, decline tab is active; growth should not be
    # Re-insert growth tab as inactive and decline as active
    # After blanket replace, growth URL became decline — restore tabs carefully from original
    orig = read(src)
    # Extract tabs block from original and rebuild
    tm = re.search(
        r'<div class="flex flex-wrap gap-2 mt-6">.*?</div>\s*</div>\s*</section>',
        orig,
        re.S,
    )
    if tm:
        tabs = tm.group(0)
        # deactivate growth, insert decline tab after growth
        tabs = tabs.replace(
            'href="/rankings/price-growth"\n'
            '         class="px-4 py-2 rounded-full text-sm font-medium transition bg-brand-600 text-white">\n'
            "        価格上昇率\n      </a>",
            'href="/rankings/price-growth"\n'
            '         class="px-4 py-2 rounded-full text-sm font-medium transition bg-slate-100 text-slate-600 hover:bg-slate-200">\n'
            "        価格上昇率\n      </a>\n"
            "      \n"
            '      <a href="/rankings/price-decline"\n'
            '         class="px-4 py-2 rounded-full text-sm font-medium transition bg-brand-600 text-white">\n'
            "        価格下落率\n      </a>",
        )
        # Replace tabs in the already-rewritten html (URLs may be decline)
        tm2 = re.search(
            r'<div class="flex flex-wrap gap-2 mt-6">.*?</div>\s*</div>\s*</section>',
            html,
            re.S,
        )
        if tm2:
            html = html[: tm2.start()] + tabs + html[tm2.end() :]

    # Rebuild tbody rows
    rows = []
    for i, o in enumerate(items, 1):
        yoy_txt = f'{o["yoy"]:+.1f}%'
        rows.append(
            f'''        <tr class="hover:bg-brand-50/30 transition">
          <td class="px-4 py-3">
            {badge(i, sm=False)}
          </td>
          <td class="px-4 py-3">
            <a href="/price/{o["pref_slug"]}/{o["slug"]}" class="font-medium text-brand-700 hover:underline">
              {o["name"]}
            </a>
          </td>
          <td class="px-4 py-3 text-slate-500">{o["pref_name"]}</td>
          <td class="px-4 py-3 text-right tabular-nums font-medium">
            {yoy_txt}
          </td>
          <td class="px-4 py-3 text-right tabular-nums hidden sm:table-cell">
            {fmt_price(o["avg"])}
          </td>
        </tr>
'''
        )
    tb = re.search(r"<tbody class=\"divide-y divide-slate-100\">.*?</tbody>", html, re.S)
    if not tb:
        raise SystemExit("decline page: tbody not found")
    html = (
        html[: tb.start()]
        + '<tbody class="divide-y divide-slate-100">\n'
        + "".join(rows)
        + "      </tbody>"
        + html[tb.end() :]
    )

    # JSON-LD item list names/urls — best effort replace ItemList name
    html = html.replace("価格上昇率ランキング", "価格下落率ランキング")

    dest = site / "rankings" / "price-decline" / "index.html"
    write(dest, html)
    print(f"  decline page: wrote {len(items)} rows -> rankings/price-decline/")


def strip_cumulative_count_columns(html: str) -> str:
    """ランキング表から「累計件数」列（th/td）を除去する。"""
    if "累計件数" not in html:
        return html
    html = re.sub(
        r'\n\s*<th class="[^"]*">\s*累計件数\s*</th>',
        "",
        html,
    )
    html = re.sub(
        r'\n\s*<td class="px-[34] py-[13]\.?5 text-right tabular-nums hidden (?:sm|md):table-cell">[\d,]+</td>',
        "",
        html,
    )
    return html


def apply_count_column_strip(site: Path) -> None:
    targets = [site / "index.html", site / "rankings" / "price-decline" / "index.html"]
    for path in targets:
        if not path.exists():
            continue
        html = read(path)
        stripped = strip_cumulative_count_columns(html)
        if stripped != html:
            write(path, stripped)
            print(f"  stripped 累計件数 column: {path.relative_to(site)}")


def patch_ranking_tabs(site: Path) -> None:
    """全ランキングページのタブに価格下落率を追加。"""
    ranking_dir = site / "rankings"
    growth_tab = (
        '      <a href="/rankings/price-growth"\n'
        '         class="px-4 py-2 rounded-full text-sm font-medium transition bg-slate-100 text-slate-600 hover:bg-slate-200">\n'
        "        価格上昇率\n      </a>"
    )
    decline_tab = (
        '      <a href="/rankings/price-decline"\n'
        '         class="px-4 py-2 rounded-full text-sm font-medium transition bg-slate-100 text-slate-600 hover:bg-slate-200">\n'
        "        価格下落率\n      </a>"
    )
    n = 0
    for page in ranking_dir.glob("*/index.html"):
        if page.parent.name == "price-decline":
            continue
        html = read(page)
        if "/rankings/price-decline" in html:
            continue
        if growth_tab not in html:
            # active growth tab variant
            active = (
                '      <a href="/rankings/price-growth"\n'
                '         class="px-4 py-2 rounded-full text-sm font-medium transition bg-brand-600 text-white">\n'
                "        価格上昇率\n      </a>"
            )
            if active in html:
                html = html.replace(
                    active,
                    active + "\n      \n" + decline_tab,
                    1,
                )
                write(page, html)
                n += 1
            continue
        html = html.replace(growth_tab, growth_tab + "\n      \n" + decline_tab, 1)
        write(page, html)
        n += 1
    # Also rankings/index.html
    root = ranking_dir / "index.html"
    if root.exists():
        html = read(root)
        if "/rankings/price-decline" not in html and growth_tab in html:
            write(root, html.replace(growth_tab, growth_tab + "\n      \n" + decline_tab, 1))
            n += 1
    print(f"  ranking tabs: patched {n} pages")


RANK_TABLE_CSS = """\
.rank-table--compact {
  table-layout: fixed;
  width: 100%;
  border-collapse: collapse;
}

.rank-table--compact th,
.rank-table--compact td {
  padding: 0 4px !important;
  line-height: 1.2 !important;
  white-space: nowrap !important;
  vertical-align: middle !important;
}

.rank-table--compact thead th {
  padding-top: 2px !important;
  padding-bottom: 2px !important;
  font-size: 0.75rem;
}

.rank-table--compact tbody tr {
  border-bottom: 1px solid #f1f5f9;
}

.rank-table--compact tbody tr:last-child {
  border-bottom: none;
}

.rank-table--compact .rank-badge--sm {
  width: 15px !important;
  height: 15px !important;
  border-radius: 4px;
  font-size: 8px !important;
  line-height: 15px !important;
}

.home-rank-grid {
  gap: 0.75rem;
}

@media (min-width: 1280px) {
  .home-rank-grid {
    gap: 1rem;
  }
}
"""

RANK_INLINE_STYLE = """<style id="rank-table-overrides">
table.rank-table--compact {
  table-layout: fixed;
  width: 100%;
  border-collapse: collapse;
}
table.rank-table--compact th,
table.rank-table--compact td {
  padding: 0 4px !important;
  line-height: 1.2 !important;
  white-space: nowrap !important;
  vertical-align: middle !important;
}
table.rank-table--compact thead th {
  padding-top: 2px !important;
  padding-bottom: 2px !important;
}
table.rank-table--compact tbody tr {
  border-bottom: 1px solid #f1f5f9;
}
table.rank-table--compact tbody tr:last-child {
  border-bottom: none;
}
table.rank-table--compact .rank-badge--sm {
  width: 15px !important;
  height: 15px !important;
  font-size: 8px !important;
  line-height: 15px !important;
}
.home-rank-grid {
  gap: 0.75rem !important;
}
@media (min-width: 1280px) {
  .home-rank-grid {
    gap: 1rem !important;
  }
}
</style>"""


def patch_ranking_table_css(site: Path) -> None:
    css_path = site / "static" / "site.css"
    css = read(css_path)
    new_block = RANK_TABLE_CSS.strip()

    if "padding: 0 4px !important" in css and "table-layout: fixed" in css:
        print("  ranking css: already up to date")
        return

    m = re.search(
        r"\.rank-table--compact th,\s*\n\.rank-table--compact td \{.*?"
        r"@media \(min-width: 1280px\) \{\s*\n  \.home-rank-grid \{\s*\n    gap: 1\.25rem;\s*\n  \}\s*\n\}",
        css,
        re.S,
    )
    if m:
        css = css[: m.start()] + new_block + css[m.end() :]
    else:
        css = css.rstrip() + "\n\n/* Home ranking tables */\n" + new_block

    write(css_path, css)
    print("  ranking css: updated")


def patch_ranking_table_html(site: Path) -> None:
    """Tailwind py-1.5 を上書きできないため、ランキング表のセルクラスを直接修正。"""
    path = site / "index.html"
    html = read(path)
    if "rank-table--compact" not in html:
        return
    changed = False

    def fix_table(m: re.Match[str]) -> str:
        block = m.group(0)
        block = block.replace("px-3 py-1.5", "px-1 py-0")
        block = block.replace("px-2 py-0", "px-1 py-0")
        block = block.replace("px-2 py-1", "px-1 py-0")
        block = block.replace('w-12">順位', 'w-10">順位')
        block = block.replace('w-12">#', 'w-10">#')
        block = block.replace('class="divide-y divide-slate-100"', 'class="rank-table-body"')
        return block

    new_html = re.sub(
        r'<table class="w-full text-sm rank-table--compact">.*?</table>',
        fix_table,
        html,
        flags=re.S,
    )
    if new_html != html:
        html = new_html
        changed = True

    if 'id="rank-table-overrides"' not in html:
        m = re.search(r"</head>", html, re.I)
        if m:
            html = html[: m.start()] + RANK_INLINE_STYLE + "\n" + html[m.start() :]
            changed = True

    if changed:
        write(path, html)
        print("  ranking html: tightened cells + inline style")
    else:
        print("  ranking html: already up to date")


def bump_site_css_version(site: Path, *, index_only: bool = True) -> None:
    """CSS キャッシュを更新。"""
    n = 0
    version = str(int(__import__("time").time()))
    paths = [site / "index.html"] if index_only else site.rglob("*.html")
    for path in paths:
        if not path.exists():
            continue
        html = read(path)
        if "/static/site.css?v=" not in html:
            continue
        new_html = re.sub(
            r"/static/site\.css\?v=\d+",
            f"/static/site.css?v={version}",
            html,
            count=1,
        )
        if new_html != html:
            write(path, new_html)
            n += 1
    if n:
        print(f"  css cache bust: {n} pages")
    else:
        print("  css cache bust: skipped")


def patch_ranking_labels(site: Path) -> None:
    path = site / "index.html"
    html = read(path)
    changed = False
    h3 = '<h3 class="text-sm font-semibold text-slate-700 leading-tight">'

    # 旧タイトル + サブタイトル → 一文タイトル
    legacy_subs = {
        "平均価格トップ10": "不動産取引価格の平均",
        "値上がり率トップ10": "平均取引価格の前年比（上昇順）",
        "値下がり率トップ10": "平均取引価格の前年比（下落順）",
    }
    for old_title, desc in legacy_subs.items():
        block = (
            f"{h3}{old_title}</h3>\n"
            f'          <p class="text-[11px] text-slate-500 leading-snug mt-0.5">{desc}</p>'
        )
        new_title = RANK_CARD_TITLES[old_title]
        if block in html:
            html = html.replace(block, f"{h3}{new_title}</h3>")
            changed = True

    for old_title, new_title in RANK_CARD_TITLES.items():
        for cls in (
            "text-sm font-semibold text-slate-700",
            "text-sm font-semibold text-slate-700 leading-tight",
        ):
            old = f'<h3 class="{cls}">{old_title}</h3>'
            new = f'<h3 class="text-sm font-semibold text-slate-700 leading-tight">{new_title}</h3>'
            if old in html:
                html = html.replace(old, new)
                changed = True

    subs = [
        (
            '<p class="mt-1 text-sm text-slate-500">クリックで市区町村一覧へ</p>',
            '<p class="mt-1 text-sm text-slate-500">国土交通省の不動産取引価格情報に基づく。クリックで市区町村一覧へ</p>',
        ),
        (
            '<p class="mt-1 text-sm text-slate-500">行をクリックして詳細・グラフを表示</p>',
            '<p class="mt-1 text-sm text-slate-500">不動産取引価格の平均・前年比ランキング。行をクリックで詳細へ</p>',
        ),
    ]
    for old, new in subs:
        if old in html:
            html = html.replace(old, new, 1)
            changed = True

    if "home-rank-grid" not in html:
        html = html.replace(
            "grid lg:grid-cols-2 xl:grid-cols-3 gap-8",
            "grid lg:grid-cols-2 xl:grid-cols-3 gap-4 home-rank-grid",
        )
        html = html.replace(
            "grid lg:grid-cols-2 gap-8",
            "grid lg:grid-cols-2 xl:grid-cols-3 gap-4 home-rank-grid",
        )
        changed = True

    if 'px-4 py-2 border-b border-slate-100 bg-slate-50' in html:
        html = html.replace(
            'px-4 py-2 border-b border-slate-100 bg-slate-50',
            'px-3 py-1.5 border-b border-slate-100 bg-slate-50',
        )
        changed = True

    if changed:
        write(path, html)
        print("  ranking labels/UI: applied")
    else:
        print("  ranking labels/UI: already present")


def main() -> None:
    if len(sys.argv) < 2:
        print("usage: patch_decline_rankings.py <site_dir>")
        sys.exit(1)
    site = Path(sys.argv[1]).resolve()
    if not (site / "price").is_dir():
        sys.exit(f"error: {site} does not look like a built site (no price/)")
    print(f"== patch decline rankings -> {site} ==")
    prefs = collect_prefectures(site)
    munis = collect_municipalities(site)
    print(f"  collected: prefs={len(prefs)}, munis={len(munis)}")
    if not prefs or not munis:
        sys.exit("error: insufficient ranking source data")
    patch_home(site, prefs, munis)
    build_decline_page(site, munis)
    patch_ranking_tabs(site)
    apply_count_column_strip(site)
    patch_ranking_table_css(site)
    patch_ranking_labels(site)
    patch_ranking_table_html(site)
    bump_site_css_version(site)
    print("== done ==")


if __name__ == "__main__":
    main()
