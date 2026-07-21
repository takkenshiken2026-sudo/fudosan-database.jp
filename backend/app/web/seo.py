from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Optional

from app.config import settings

SITE_NAME = "不動産相場ナビ"
ORG_NAME = "不動産相場ナビ"
MLIT_ORG = {
    "@type": "Organization",
    "name": "国土交通省",
    "url": "https://www.mlit.go.jp/",
}


@dataclass
class SeoMeta:
    page_title: str
    meta_description: str
    canonical_path: str
    robots: str = "index,follow"
    og_type: str = "website"
    og_image_path: str = "/static/og-default.svg"
    breadcrumbs: list[tuple[str, str]] = field(default_factory=list)
    extra_graph: list[dict[str, Any]] = field(default_factory=list)
    canonical_url: str = ""
    og_image_url: str = ""
    json_ld: str = ""


def site_base_url(request_base: str) -> str:
    if settings.site_url:
        return settings.site_url.rstrip("/")
    return request_base.rstrip("/")


def absolute_url(base: str, path: str) -> str:
    if not path.startswith("/"):
        path = f"/{path}"
    return f"{base}{path}"


def finalize_seo(seo: SeoMeta, base: str) -> SeoMeta:
    seo.canonical_url = absolute_url(base, seo.canonical_path)
    seo.og_image_url = absolute_url(base, seo.og_image_path)
    graph = _base_graph(base)
    if seo.breadcrumbs:
        graph.append(_breadcrumb_list(seo.breadcrumbs))
    graph.extend(seo.extra_graph)
    seo.json_ld = json.dumps(
        {"@context": "https://schema.org", "@graph": graph},
        ensure_ascii=False,
    )
    return seo


def _base_graph(base: str) -> list[dict[str, Any]]:
    return [
        {
            "@type": "Organization",
            "@id": f"{base}/#organization",
            "name": ORG_NAME,
            "url": base,
            "logo": absolute_url(base, "/static/og-default.svg"),
            "description": (
                "国土交通省 不動産情報ライブラリの取引価格情報・地価公示データに基づき、"
                "全国の不動産相場を集計・公開する情報サービス。"
            ),
            "knowsAbout": ["不動産取引価格", "地価公示", "不動産相場", "土地価格"],
            "publishingPrinciples": absolute_url(base, "/about"),
        },
        {
            "@type": "WebSite",
            "@id": f"{base}/#website",
            "url": base,
            "name": SITE_NAME,
            "publisher": {"@id": f"{base}/#organization"},
            "inLanguage": "ja-JP",
            "potentialAction": {
                "@type": "SearchAction",
                "target": {
                    "@type": "EntryPoint",
                    "urlTemplate": absolute_url(base, "/search?q={search_term_string}"),
                },
                "query-input": "required name=search_term_string",
            },
        },
    ]


def _breadcrumb_list(items: list[tuple[str, str]]) -> dict[str, Any]:
    return {
        "@type": "BreadcrumbList",
        "itemListElement": [
            {
                "@type": "ListItem",
                "position": i + 1,
                "name": name,
                "item": url,
            }
            for i, (name, url) in enumerate(items)
        ],
    }


def seo_home(base: str) -> SeoMeta:
    seo = SeoMeta(
        page_title=f"{SITE_NAME} | 全国の不動産取引価格・相場データ",
        meta_description=(
            "全国1,920市区町村の不動産取引価格・取引件数・価格推移を無料公開。"
            "国土交通省 不動産情報ライブラリのデータに基づく地域別相場検索。"
        ),
        canonical_path="/",
        extra_graph=[
            {
                "@type": "WebPage",
                "@id": f"{base}/#webpage",
                "url": base,
                "name": f"{SITE_NAME} | 全国の不動産取引価格・相場データ",
                "isPartOf": {"@id": f"{base}/#website"},
                "inLanguage": "ja-JP",
            }
        ],
    )
    return finalize_seo(seo, base)


def seo_market(base: str) -> SeoMeta:
    path = "/market"
    url = absolute_url(base, path)
    seo = SeoMeta(
        page_title=f"全国の取引価格・地価動向 | {SITE_NAME}",
        meta_description=(
            "全国の不動産取引価格・取引件数・地価公示の年次推移をグラフと表で確認。"
            "国土交通省 不動産情報ライブラリのデータに基づく全国動向。"
        ),
        canonical_path=path,
        breadcrumbs=[
            (SITE_NAME, base),
            ("全国の取引価格", url),
        ],
    )
    return finalize_seo(seo, base)


def seo_satei(base: str) -> SeoMeta:
    path = "/satei"
    url = absolute_url(base, path)
    seo = SeoMeta(
        page_title=f"不動産価格の無料査定シミュレーション | {SITE_NAME}",
        meta_description=(
            "エリアと面積・築年数を入力するだけで、中古マンション・土地・戸建の想定売却価格を"
            "無料で即時シミュレーション。国土交通省の実際の取引価格データに基づく参考査定です。"
        ),
        canonical_path=path,
        breadcrumbs=[
            (SITE_NAME, base),
            ("価格査定シミュレーション", url),
        ],
    )
    return finalize_seo(seo, base)


def seo_prefecture(
    base: str,
    name: str,
    slug: str,
    muni_count: int,
    faq_items: Optional[list[tuple[str, str]]] = None,
) -> SeoMeta:
    path = f"/price/{slug}"
    url = absolute_url(base, path)
    extra_graph: list[dict[str, Any]] = [
        {
            "@type": "CollectionPage",
            "@id": f"{url}#webpage",
            "url": url,
            "name": f"{name}の不動産相場・土地価格",
            "description": f"{name}内の市区町村別の取引価格・地価公示データ",
            "isPartOf": {"@id": f"{base}/#website"},
            "inLanguage": "ja-JP",
        }
    ]
    if faq_items:
        extra_graph.append(_faq_page(url, faq_items))
    seo = SeoMeta(
        page_title=f"{name}の不動産相場・土地価格一覧【市区町村別】 | {SITE_NAME}",
        meta_description=(
            f"{name}の{muni_count}市区町村の不動産相場・土地価格・取引件数を一覧比較。"
            f"取引価格と地価公示の年次推移グラフ・ランキングで{name}の相場がわかります。"
        ),
        canonical_path=path,
        og_type="website",
        breadcrumbs=[
            (SITE_NAME, base),
            (name, url),
        ],
        extra_graph=extra_graph,
    )
    return finalize_seo(seo, base)


def seo_municipality(
    base: str,
    pref_name: str,
    pref_slug: str,
    name: str,
    muni_slug: str,
    *,
    total_transactions: int,
    recent_avg_price: Optional[float],
    latest_year: Optional[int],
    stats_updated_at: Optional[datetime] = None,
    land_avg_unit_price: Optional[float] = None,
    land_yoy: Optional[float] = None,
    faq_items: Optional[list[tuple[str, str]]] = None,
) -> SeoMeta:
    path = f"/price/{pref_slug}/{muni_slug}"
    url = absolute_url(base, path)
    pref_url = absolute_url(base, f"/price/{pref_slug}")
    price_text = (
        f"平均取引価格{_format_man(recent_avg_price)}、" if recent_avg_price else ""
    )
    land_text = ""
    if land_avg_unit_price:
        land_text = f"地価公示{int(land_avg_unit_price):,}円/㎡"
        if land_yoy is not None:
            sign = "+" if land_yoy > 0 else ""
            land_text += f"（前年比{sign}{land_yoy:.1f}%）"
        land_text += "、"
    year_prefix = f"【{latest_year}年最新】" if latest_year else ""
    year_text = f"{latest_year}年までの" if latest_year else ""
    webpage: dict[str, Any] = {
        "@type": "WebPage",
        "@id": f"{url}#webpage",
        "url": url,
        "name": f"{pref_name}{name}の不動産取引価格・相場",
        "isPartOf": {"@id": f"{base}/#website"},
        "inLanguage": "ja-JP",
        "about": {"@id": f"{url}#place"},
        "mainEntity": {"@id": f"{url}#dataset"},
    }
    if stats_updated_at:
        webpage["dateModified"] = stats_updated_at.strftime("%Y-%m-%d")
    extra_graph: list[dict[str, Any]] = [
        webpage,
        {
            "@type": "Place",
            "@id": f"{url}#place",
            "name": f"{pref_name}{name}",
            "containedInPlace": {
                "@type": "AdministrativeArea",
                "name": pref_name,
            },
        },
        {
            "@type": "Dataset",
            "@id": f"{url}#dataset",
            "name": f"{pref_name}{name}の不動産取引価格データ",
            "description": (
                f"国土交通省 不動産情報ライブラリに基づく"
                f"{pref_name}{name}の取引価格統計（{total_transactions:,}件）"
            ),
            "creator": MLIT_ORG,
            "isBasedOn": "https://www.reinfolib.mlit.go.jp/",
            "temporalCoverage": "2005/2025",
            "spatialCoverage": {
                "@type": "Place",
                "name": f"{pref_name}{name}",
            },
            "license": "https://www.mlit.go.jp/",
        },
    ]
    if faq_items:
        extra_graph.append(_faq_page(url, faq_items))
    seo = SeoMeta(
        page_title=f"{pref_name}{name}の不動産相場・土地価格{year_prefix} | {SITE_NAME}",
        meta_description=(
            f"{pref_name}{name}の不動産相場・土地価格を無料公開。"
            f"{price_text}{land_text}"
            f"{year_text}中古マンション・土地・戸建の取引価格の推移グラフと"
            f"累計{total_transactions:,}件の実データ、地価公示を掲載。"
        ),
        canonical_path=path,
        og_type="article",
        breadcrumbs=[
            (SITE_NAME, base),
            (pref_name, pref_url),
            (name, url),
        ],
        extra_graph=extra_graph,
    )
    return finalize_seo(seo, base)


def _faq_page(page_url: str, items: list[tuple[str, str]]) -> dict[str, Any]:
    """可視 FAQ セクションと対になる FAQPage 構造化データを生成。"""
    return {
        "@type": "FAQPage",
        "@id": f"{page_url}#faq",
        "mainEntity": [
            {
                "@type": "Question",
                "name": question,
                "acceptedAnswer": {"@type": "Answer", "text": answer},
            }
            for question, answer in items
        ],
    }


def seo_rankings(
    base: str, sort: str, items: Optional[list] = None
) -> SeoMeta:
    is_price = sort == "price"
    title = "平均価格ランキング" if is_price else "取引件数ランキング"
    extra: list[dict[str, Any]] = []
    if items:
        extra.append(
            {
                "@type": "ItemList",
                "name": f"市区町村{title}",
                "numberOfItems": len(items),
                "itemListElement": [
                    {
                        "@type": "ListItem",
                        "position": it.rank,
                        "url": absolute_url(base, f"/price/{it.prefecture_slug}/{it.slug}"),
                        "name": f"{it.prefecture_name}{it.name_ja}",
                    }
                    for it in items[:20]
                ],
            }
        )
    seo = SeoMeta(
        page_title=f"市区町村{title} | 不動産取引価格 | {SITE_NAME}",
        meta_description=(
            f"全国市区町村の不動産{title}（TOP50）。"
            "国土交通省データに基づく取引件数・平均価格のランキング。"
        ),
        canonical_path="/rankings",
        breadcrumbs=[
            (SITE_NAME, base),
            (title, absolute_url(base, "/rankings")),
        ],
        extra_graph=extra,
    )
    return finalize_seo(seo, base)


def seo_search(base: str, query: str, result_count: int) -> SeoMeta:
    q = query.strip()
    path = f"/search?q={q}" if q else "/search"
    seo = SeoMeta(
        page_title=f"「{q}」の検索結果 | {SITE_NAME}" if q else f"エリア検索 | {SITE_NAME}",
        meta_description=(
            f"「{q}」に一致する市区町村の不動産取引価格データ（{result_count}件）。"
            if q
            else "市区町村名で不動産取引価格・相場データを検索。"
        ),
        canonical_path=path,
        robots="noindex,follow" if q else "index,follow",
        breadcrumbs=[
            (SITE_NAME, base),
            ("検索", absolute_url(base, "/search")),
        ],
    )
    return finalize_seo(seo, base)


def seo_news(base: str, category: str = "") -> SeoMeta:
    from app.news.categories import CATEGORY_BY_ID

    if category and category in CATEGORY_BY_ID:
        cat = CATEGORY_BY_ID[category]
        title = f"{cat.label}ニュース"
        desc = f"不動産・{cat.label}に関する最新ニュース（Googleニュース）。{cat.description}"
        path = f"/news?category={category}"
    else:
        title = "不動産・地価ニュース"
        desc = "地価公示・不動産取引・住宅市場・政策などカテゴリ別の最新ニュースを収集・表示。"
        path = "/news"
    seo = SeoMeta(
        page_title=f"{title} | {SITE_NAME}",
        meta_description=desc,
        canonical_path=path,
        breadcrumbs=[
            (SITE_NAME, base),
            ("ニュース", absolute_url(base, "/news")),
        ],
    )
    return finalize_seo(seo, base)


def seo_station(base: str, station) -> SeoMeta:
    title_name = f"{station.station_name}駅"
    line = station.line_name or ""
    pref = station.prefecture_name or ""
    path = f"/station/{station.id}"
    desc = (
        f"{title_name}（{line}）の乗降客数推移。"
        f"{pref}の鉄道駅データ（国土数値情報・駅別乗降客数）。"
    )
    if station.latest_year and station.latest_passengers:
        desc += f"最新{station.latest_year}年: 約{station.latest_passengers:,}人/日。"
    seo = SeoMeta(
        page_title=f"{title_name}の乗降客数 | {SITE_NAME}",
        meta_description=desc,
        canonical_path=path,
        breadcrumbs=[
            (SITE_NAME, base),
            (title_name, absolute_url(base, path)),
        ],
    )
    return finalize_seo(seo, base)


def seo_regional_news(
    base: str,
    area_label: str,
    prefecture_slug: str,
    prefecture_name: str,
    municipality_slug: Optional[str] = None,
    municipality_name: Optional[str] = None,
) -> SeoMeta:
    if municipality_slug:
        path = f"/news/area/{prefecture_slug}/{municipality_slug}"
        pref_url = absolute_url(base, f"/price/{prefecture_slug}")
        crumbs = [
            (SITE_NAME, base),
            ("ニュース", absolute_url(base, "/news")),
            (prefecture_name, absolute_url(base, f"/news/area/{prefecture_slug}")),
            (municipality_name or area_label, absolute_url(base, path)),
        ]
    else:
        path = f"/news/area/{prefecture_slug}"
        crumbs = [
            (SITE_NAME, base),
            ("ニュース", absolute_url(base, "/news")),
            (area_label, absolute_url(base, path)),
        ]
    seo = SeoMeta(
        page_title=f"{area_label}の不動産ニュース | {SITE_NAME}",
        meta_description=(
            f"{area_label}に関する不動産・地価・住宅市場の最新ニュースを収集。"
            "Googleニュース経由で各メディアの記事へアクセスできます。"
        ),
        canonical_path=path,
        breadcrumbs=crumbs,
    )
    return finalize_seo(seo, base)


def seo_for_agents(base: str) -> SeoMeta:
    seo = SeoMeta(
        page_title=f"不動産仲介店向け 取引事例レポート自動生成 | {SITE_NAME}",
        meta_description=(
            "不動産仲介店向けSaaS。住所・エリア指定で取引事例・地価公示をまとめた"
            "顧客向けレポートを自動生成。PDF出力対応予定。"
        ),
        canonical_path="/for-agents",
        breadcrumbs=[
            (SITE_NAME, base),
            ("仲介店向け", absolute_url(base, "/for-agents")),
        ],
    )
    return finalize_seo(seo, base)


def seo_about(base: str) -> SeoMeta:
    path = "/about"
    url = absolute_url(base, path)
    seo = SeoMeta(
        page_title=f"データについて（出典・調査方法） | {SITE_NAME}",
        meta_description=(
            "不動産相場ナビのデータ出典・対象範囲・統計の算出方法・更新方針・"
            "免責事項について。国土交通省 不動産情報ライブラリのデータに基づく"
            "全国の不動産相場情報の根拠を公開しています。"
        ),
        canonical_path=path,
        breadcrumbs=[
            (SITE_NAME, base),
            ("データについて", url),
        ],
        extra_graph=[
            {
                "@type": "AboutPage",
                "@id": f"{url}#webpage",
                "url": url,
                "name": f"データについて（出典・調査方法） | {SITE_NAME}",
                "isPartOf": {"@id": f"{base}/#website"},
                "about": {"@id": f"{base}/#organization"},
                "inLanguage": "ja-JP",
            }
        ],
    )
    return finalize_seo(seo, base)


def seo_report_new(base: str) -> SeoMeta:
    seo = SeoMeta(
        page_title=f"取引事例レポート作成 | {SITE_NAME}",
        meta_description="市区町村を指定して取引事例レポートをプレビュー。仲介店の顧客説明資料に。",
        canonical_path="/report/new",
        robots="noindex,follow",
    )
    return finalize_seo(seo, base)


def seo_report_page(base: str, detail: Any) -> SeoMeta:
    area = f"{detail.prefecture_name}{detail.name_ja}"
    seo = SeoMeta(
        page_title=f"{area}の取引事例レポート | {SITE_NAME}",
        meta_description=(
            f"{area}の取引統計・周辺事例・地価公示をまとめたレポートを"
            "PowerPoint / Word でダウンロード。仲介店の顧客説明資料に。"
        ),
        canonical_path=f"/report/{detail.prefecture_slug}/{detail.slug}",
        robots="noindex,follow",
    )
    return finalize_seo(seo, base)


def seo_compare(
    base: str,
    left_name: Optional[str] = None,
    right_name: Optional[str] = None,
) -> SeoMeta:
    if left_name and right_name:
        title = f"{left_name} vs {right_name} 不動産相場比較"
        desc = f"{left_name}と{right_name}の取引件数・平均価格・価格推移を並べて比較。"
        path = "/compare"
        robots = "index,follow"
    else:
        title = "エリア比較"
        desc = "2つの市区町村の不動産取引価格・取引件数を並べて比較できます。"
        path = "/compare"
        robots = "index,follow"
    seo = SeoMeta(
        page_title=f"{title} | {SITE_NAME}",
        meta_description=desc,
        canonical_path=path,
        robots=robots,
        breadcrumbs=[
            (SITE_NAME, base),
            ("エリア比較", absolute_url(base, "/compare")),
        ],
    )
    return finalize_seo(seo, base)


def seo_not_found(base: str) -> SeoMeta:
    seo = SeoMeta(
        page_title=f"ページが見つかりません | {SITE_NAME}",
        meta_description="お探しのページは見つかりませんでした。トップページまたは検索からお探しください。",
        canonical_path="/404",
        robots="noindex,nofollow",
    )
    return finalize_seo(seo, base)


def _format_man(value: Optional[float]) -> str:
    if value is None:
        return ""
    man = value / 10_000
    if man >= 1:
        return f"{man:,.0f}万円"
    return f"{value:,.0f}円"


def format_lastmod(dt: Optional[datetime]) -> Optional[str]:
    if not dt:
        return None
    return dt.strftime("%Y-%m-%d")


def render_sitemap_xml(entries: list[tuple[str, Optional[str], str, str]]) -> str:
    lines = [
        '<?xml version="1.0" encoding="UTF-8"?>',
        '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">',
    ]
    for loc, lastmod, changefreq, priority in entries:
        lines.append("  <url>")
        lines.append(f"    <loc>{_xml_escape(loc)}</loc>")
        if lastmod:
            lines.append(f"    <lastmod>{lastmod}</lastmod>")
        lines.append(f"    <changefreq>{changefreq}</changefreq>")
        lines.append(f"    <priority>{priority}</priority>")
        lines.append("  </url>")
    lines.append("</urlset>")
    return "\n".join(lines)


def _xml_escape(text: str) -> str:
    return (
        text.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
        .replace("'", "&apos;")
    )
