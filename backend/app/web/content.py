"""検索意図に地の文で答えるための本文・FAQ 生成ヘルパー。

市区町村・都道府県ページの冒頭要約テキストと FAQ（可視セクション兼
FAQPage 構造化データ）を、DB 由来の数値から動的に組み立てる。
「相場」「土地価格」「地価」といったクエリ語を自然に含めることで、
タイトル・本文・構造化データの語一致を高めることを狙う。
"""

from __future__ import annotations

from typing import Any, Optional

from app.web.formatters import (
    format_man_yen,
    format_percent,
    format_yen_per_sqm,
)


def _trend_word(yoy: Optional[float]) -> str:
    """前年比(%)からざっくりした傾向語を返す。"""
    if yoy is None:
        return ""
    if yoy >= 1.5:
        return "上昇傾向"
    if yoy <= -1.5:
        return "下落傾向"
    return "横ばい"


def build_municipality_intro(detail: Any) -> str:
    """市区町村ページ冒頭に置く 2〜3 文の要約テキスト。

    検索意図（相場・土地価格・推移）に対して、ページを開いてすぐ
    地の文で答えることで、検索結果スニペットと本文の語一致を高める。
    """
    area = f"{detail.prefecture_name}{detail.name_ja}"
    year = detail.latest_year
    year_text = f"{year}年時点で" if year else ""
    parts: list[str] = []

    if detail.recent_avg_price:
        parts.append(
            f"{area}の不動産取引価格の平均は{year_text}約"
            f"{format_man_yen(detail.recent_avg_price)}です。"
        )
    else:
        parts.append(f"{area}の不動産取引価格・相場データをまとめています。")

    total = detail.total_transactions
    trend = _trend_word(detail.yoy_price_change_pct)
    if total:
        sentence = (
            f"国土交通省の実際の取引データ累計{total:,}件をもとに、"
            "中古マンション・土地・戸建の相場と価格推移を掲載しています"
        )
        if trend:
            sentence += f"（直近の価格は{trend}）。"
        else:
            sentence += "。"
        parts.append(sentence)

    land = detail.land_prices
    if land and land.avg_unit_price:
        sentence = f"{area}の地価公示（土地価格）の平均は{format_yen_per_sqm(land.avg_unit_price)}"
        if land.yoy_change_avg is not None:
            sentence += f"（前年比{format_percent(land.yoy_change_avg)}）"
        sentence += "です。"
        parts.append(sentence)

    return "".join(parts)


def build_municipality_faq(detail: Any) -> list[tuple[str, str]]:
    """市区町村ページの FAQ（質問・回答）を数値から生成。

    可視 FAQ セクションと FAQPage 構造化データの両方で使う。
    データが無い項目はスキップし、事実に基づく回答のみを返す。
    """
    area = f"{detail.prefecture_name}{detail.name_ja}"
    year = detail.latest_year
    year_text = f"{year}年時点で" if year else ""
    faq: list[tuple[str, str]] = []

    if detail.recent_avg_price:
        answer = (
            f"{area}の不動産取引価格の平均は{year_text}約"
            f"{format_man_yen(detail.recent_avg_price)}です。"
        )
        if detail.total_transactions:
            answer += (
                f"国土交通省の取引データ累計{detail.total_transactions:,}件に基づく"
                "参考値で、物件種別や築年数により価格は異なります。"
            )
        faq.append((f"{area}の不動産相場（取引価格）はいくらですか？", answer))

    market = (
        detail.purchase_insights.market_summary
        if detail.purchase_insights
        else None
    )
    if market and market.median_price:
        answer = (
            f"{area}の{market.property_label}の取引価格は中央値で約"
            f"{format_man_yen(market.median_price)}"
        )
        if market.p25_price and market.p75_price:
            answer += (
                f"、価格帯の中心はおおむね{format_man_yen(market.p25_price)}〜"
                f"{format_man_yen(market.p75_price)}"
            )
        answer += f"です（直近{market.sample_count:,}件の取引に基づく）。"
        faq.append((f"{area}の中古マンション価格の相場は？", answer))

    land = detail.land_prices
    if land and land.avg_unit_price:
        answer = f"{area}の地価公示の平均は{format_yen_per_sqm(land.avg_unit_price)}"
        if land.yoy_change_avg is not None:
            answer += f"、前年比{format_percent(land.yoy_change_avg)}"
        land_year = land.latest_year or year
        year_part = f"{land_year}年・" if land_year else ""
        answer += f"です（{year_part}{land.point_count:,}地点の平均）。"
        faq.append((f"{area}の土地価格・地価はどのくらいですか？", answer))

    trend = _trend_word(detail.yoy_price_change_pct)
    if trend:
        answer = (
            f"{area}の直近の不動産価格は前年比"
            f"{format_percent(detail.yoy_price_change_pct)}で{trend}です。"
            "ページ内の価格推移グラフで年次・四半期ごとの変化を確認できます。"
        )
        faq.append(
            (f"{area}の不動産価格は上がっていますか？下がっていますか？", answer)
        )

    return faq


def build_prefecture_intro(
    prefecture_name: str,
    municipality_count: int,
    chart_data: Optional[dict[str, Any]] = None,
) -> str:
    """都道府県ページ冒頭の要約テキスト。"""
    parts = [
        f"{prefecture_name}の{municipality_count:,}市区町村の不動産取引価格・相場を"
        "一覧で比較できます。"
    ]
    latest = _latest_yearly(chart_data)
    if latest and latest.get("trade_price_avg"):
        year = latest.get("trade_year")
        year_text = f"{year}年の" if year else "直近の"
        parts.append(
            f"{prefecture_name}全体の{year_text}平均取引価格は約"
            f"{format_man_yen(latest['trade_price_avg'])}です。"
        )
    parts.append(
        "国土交通省 不動産情報ライブラリのデータに基づき、市区町村別の"
        "取引価格・地価公示・価格推移を掲載しています。"
    )
    return "".join(parts)


def build_prefecture_faq(
    prefecture_name: str,
    municipality_count: int,
    chart_data: Optional[dict[str, Any]] = None,
) -> list[tuple[str, str]]:
    """都道府県ページの FAQ を生成。"""
    faq: list[tuple[str, str]] = []
    latest = _latest_yearly(chart_data)
    if latest and latest.get("trade_price_avg"):
        year = latest.get("trade_year")
        year_text = f"{year}年時点で" if year else ""
        faq.append(
            (
                f"{prefecture_name}の不動産相場はいくらですか？",
                f"{prefecture_name}全体の不動産取引価格の平均は{year_text}約"
                f"{format_man_yen(latest['trade_price_avg'])}です。"
                f"市区町村ごとの相場は{prefecture_name}内{municipality_count:,}"
                "市区町村の一覧・ランキングで比較できます。",
            )
        )

    tops = (chart_data or {}).get("top_municipalities") or []
    top_names = [m.get("name_ja") for m in tops[:3] if m.get("name_ja")]
    if top_names:
        faq.append(
            (
                f"{prefecture_name}で取引が多いエリアはどこですか？",
                f"{prefecture_name}で不動産取引件数が多いのは"
                f"{'、'.join(top_names)}などです。各エリアの平均価格・価格推移は"
                "市区町村ページで確認できます。",
            )
        )

    return faq


def _latest_yearly(chart_data: Optional[dict[str, Any]]) -> Optional[dict[str, Any]]:
    if not chart_data:
        return None
    yearly = chart_data.get("yearly_stats") or []
    valid = [y for y in yearly if y.get("trade_price_avg")]
    if not valid:
        return None
    return max(valid, key=lambda y: y.get("trade_year") or 0)
