"""既存データから付加価値指標を組み立てる（新規API取得なし）。"""

from __future__ import annotations

import math
from typing import Optional

from sqlalchemy import func, select, text
from sqlalchemy.orm import Session

from app.api.schemas import (
    CrossMetric,
    MunicipalityEstatInsights,
    PurchaseInsights,
    RankingItem,
    SimilarMunicipality,
    YearlyStat,
)
from app.db import (
    LandPricePoint,
    Municipality,
    MunicipalityPageMeta,
    MunicipalityTradeStat,
    Prefecture,
)
from app.estat.db import EstatSessionLocal
from app.estat.municipality_insights import (
    HOUSING_RENT_TABLE,
    SOCIAL_HOUSING_TABLE,
    SOCIAL_METRIC_CODES,
    SOCIAL_POPULATION_TABLE,
    _estat_db_available,
)


def build_cross_metrics(
    *,
    yoy_price_change_pct: Optional[float],
    purchase_insights: Optional[PurchaseInsights],
    estat: Optional[MunicipalityEstatInsights],
) -> list[CrossMetric]:
    metrics: list[CrossMetric] = []
    if not estat or not estat.available:
        return metrics

    median = None
    if purchase_insights and purchase_insights.market_summary:
        median = purchase_insights.market_summary.median_price
    rent = estat.average_monthly_rent
    if rent and median and median > 0:
        ratio = rent * 12 / median * 100
        metrics.append(
            CrossMetric(
                key="rent_to_price",
                label="家賃対価格比",
                value=round(ratio, 2),
                unit="%",
                description="年家賃 ÷ マンション中央値。高いほど価格が抑えめ",
            )
        )

    if (
        estat.population_change_pct is not None
        and yoy_price_change_pct is not None
    ):
        pop = estat.population_change_pct
        price = yoy_price_change_pct
        if pop > 0 and price > 0:
            tone = "人口・価格とも上昇"
        elif pop < 0 and price < 0:
            tone = "人口・価格とも下落"
        elif pop > 0 and price < 0:
            tone = "人口増・価格下落"
        elif pop < 0 and price > 0:
            tone = "人口減・価格上昇"
        else:
            tone = "横ばい寄り"
        metrics.append(
            CrossMetric(
                key="population_price",
                label="人口×価格",
                value=round(price - pop, 1),
                unit="pt差",
                description=f"人口{pop:+.1f}% / 価格{price:+.1f}%（{tone}）",
            )
        )

    if estat.vacancy_pct is not None:
        metrics.append(
            CrossMetric(
                key="vacancy_context",
                label="空き家比率",
                value=round(estat.vacancy_pct, 1),
                unit="%",
                description="高いほど需給が緩い傾向",
            )
        )

    if purchase_insights and purchase_insights.land_trade_gap:
        gap = purchase_insights.land_trade_gap
        if gap.gap_pct is not None:
            metrics.append(
                CrossMetric(
                    key="land_trade_gap",
                    label="取引と地価の乖離",
                    value=round(gap.gap_pct, 1),
                    unit="%",
                    description="土地取引㎡単価 − 地価公示（正なら取引が高い）",
                )
            )

    return metrics


def get_similar_municipalities(
    db: Session,
    *,
    prefecture_code: str,
    municipality_code: str,
    recent_avg_price: Optional[float],
    estat: Optional[MunicipalityEstatInsights],
    limit: int = 6,
) -> list[SimilarMunicipality]:
    rows = db.execute(
        select(
            Municipality.code,
            Municipality.name_ja,
            Municipality.slug,
            MunicipalityPageMeta.total_transactions,
            MunicipalityPageMeta.recent_avg_price,
            MunicipalityPageMeta.latest_year,
            MunicipalityPageMeta.latest_quarter,
        )
        .join(
            MunicipalityPageMeta,
            MunicipalityPageMeta.municipality_code == Municipality.code,
        )
        .where(
            Municipality.prefecture_code == prefecture_code,
            Municipality.code != municipality_code,
            MunicipalityPageMeta.total_transactions > 0,
            MunicipalityPageMeta.recent_avg_price.isnot(None),
        )
    ).all()
    if not rows or not recent_avg_price:
        return []

    target_vacancy = estat.vacancy_pct if estat else None
    target_owner = estat.owner_occupied_pct if estat else None

    scored: list[tuple[float, list[str], object]] = []
    for row in rows:
        price = float(row[4] or 0)
        if price <= 0:
            continue
        price_dist = abs(math.log(price) - math.log(recent_avg_price))
        score = price_dist * 0.55
        reasons: list[str] = []
        price_gap = (price - recent_avg_price) / recent_avg_price * 100
        if abs(price_gap) < 15:
            reasons.append(f"平均価格が近い（{price_gap:+.0f}%）")
        elif abs(price_gap) < 30:
            reasons.append(f"価格帯が近い（{price_gap:+.0f}%）")

        volume = int(row[3] or 0)
        if volume >= 1000:
            score *= 0.95
            reasons.append("取引データが豊富")

        if target_vacancy is not None and abs(price_gap) < 20 and "近い" not in "".join(reasons):
            reasons.append("同県内の類似価格帯")
        if not reasons:
            reasons.append("同県内の相場が近い")

        scored.append((score, reasons[:2], row))

    scored.sort(key=lambda item: item[0])
    result: list[SimilarMunicipality] = []
    for i, (score, reasons, row) in enumerate(scored[:limit]):
        similarity = max(0.0, min(100.0, 100 - score * 40))
        result.append(
            SimilarMunicipality(
                code=row[0],
                name_ja=row[1],
                slug=row[2],
                total_transactions=int(row[3] or 0),
                recent_avg_price=row[4],
                latest_year=row[5],
                latest_quarter=row[6],
                similarity_score=round(similarity, 1),
                similarity_reasons=reasons,
            )
        )
    return result


def get_feature_rankings(
    db: Session,
    *,
    kind: str,
    limit: int = 50,
) -> list[RankingItem]:
    if kind == "volume":
        return _page_meta_rankings(db, sort="volume", limit=limit)
    if kind == "price":
        return _page_meta_rankings(db, sort="price", limit=limit)
    if kind == "price-growth":
        return _price_growth_rankings(db, limit=limit)
    if kind == "land-price-growth":
        return _land_price_growth_rankings(db, limit=limit)
    if kind == "land-price":
        return _land_price_level_rankings(db, limit=limit)
    if kind in _ESTAT_RANKING_SPECS:
        return _estat_rankings(db, kind=kind, limit=limit)
    return []


def _page_meta_rankings(
    db: Session, *, sort: str, limit: int
) -> list[RankingItem]:
    order = (
        MunicipalityPageMeta.recent_avg_price.desc().nullslast()
        if sort == "price"
        else MunicipalityPageMeta.total_transactions.desc()
    )
    rows = db.execute(
        select(
            Municipality.code,
            Municipality.name_ja,
            Municipality.slug,
            Prefecture.name_ja,
            Prefecture.slug,
            MunicipalityPageMeta.total_transactions,
            MunicipalityPageMeta.recent_avg_price,
        )
        .join(Prefecture, Prefecture.code == Municipality.prefecture_code)
        .join(
            MunicipalityPageMeta,
            MunicipalityPageMeta.municipality_code == Municipality.code,
        )
        .where(MunicipalityPageMeta.total_transactions > 0)
        .order_by(order)
        .limit(limit)
    ).all()
    return [
        RankingItem(
            rank=i + 1,
            code=row[0],
            name_ja=row[1],
            slug=row[2],
            prefecture_name=row[3],
            prefecture_slug=row[4],
            total_transactions=int(row[5] or 0),
            recent_avg_price=row[6],
        )
        for i, row in enumerate(rows)
    ]


FEATURE_RANKING_META: dict[str, dict[str, str]] = {
    "volume": {
        "title": "取引件数ランキング",
        "description": "累計の不動産取引件数が多い市区町村",
        "metric_label": "累計件数",
        "tab": "取引件数",
    },
    "price": {
        "title": "平均価格ランキング",
        "description": "平均取引価格が高い市区町村",
        "metric_label": "平均価格",
        "tab": "平均価格",
    },
    "price-growth": {
        "title": "価格上昇率ランキング",
        "description": "直近2年の平均取引価格の上昇率が高い市区町村",
        "metric_label": "価格上昇率",
        "tab": "価格上昇率",
    },
    "land-price": {
        "title": "地価公示ランキング",
        "description": "最新の地価公示平均㎡単価が高い市区町村",
        "metric_label": "平均地価",
        "tab": "地価水準",
    },
    "land-price-growth": {
        "title": "地価上昇率ランキング",
        "description": "地価公示の年平均上昇率が高い市区町村",
        "metric_label": "地価上昇率",
        "tab": "地価上昇率",
    },
    "avg-rent": {
        "title": "平均家賃ランキング",
        "description": "住宅・土地統計調査に基づく専用住宅の平均家賃が高い市区町村",
        "metric_label": "平均家賃",
        "tab": "平均家賃",
    },
    "population-growth": {
        "title": "人口増加率ランキング",
        "description": "社会・人口統計体系に基づく人口増加率が高い市区町村",
        "metric_label": "人口増加率",
        "tab": "人口増加率",
    },
    "population-density": {
        "title": "人口密度ランキング",
        "description": "人口密度が高い市区町村",
        "metric_label": "人口密度",
        "tab": "人口密度",
    },
    "elderly": {
        "title": "高齢化率ランキング",
        "description": "65歳以上人口の比率が高い市区町村",
        "metric_label": "高齢化率",
        "tab": "高齢化率",
    },
    "low-vacancy": {
        "title": "空き家率が低い市区町村",
        "description": "社会・人口統計体系に基づく空き家比率が低い市区町村",
        "metric_label": "空き家比率",
        "tab": "空き家率が低い",
    },
    "owner-occupied": {
        "title": "持ち家率ランキング",
        "description": "持ち家比率が高い市区町村",
        "metric_label": "持ち家比率",
        "tab": "持ち家率",
    },
    "single-household": {
        "title": "高齢単独世帯比率ランキング",
        "description": "高齢単独世帯の比率が高い市区町村",
        "metric_label": "高齢単独世帯比率",
        "tab": "高齢単独世帯",
    },
}

_ESTAT_RANKING_SPECS: dict[str, dict] = {
    "low-vacancy": {
        "sid": SOCIAL_HOUSING_TABLE,
        "cat01": "#H01405",
        "ascending": True,
        "unit": "%",
        "label": "空き家比率",
    },
    "owner-occupied": {
        "sid": SOCIAL_HOUSING_TABLE,
        "cat01": "#H01301",
        "ascending": False,
        "unit": "%",
        "label": "持ち家比率",
    },
    "single-household": {
        "sid": SOCIAL_POPULATION_TABLE,
        "cat01": SOCIAL_METRIC_CODES["single_elderly_household_pct"],
        "ascending": False,
        "unit": "%",
        "label": "高齢単独世帯比率",
    },
    "population-growth": {
        "sid": SOCIAL_POPULATION_TABLE,
        "cat01": SOCIAL_METRIC_CODES["population_growth_pct"],
        "ascending": False,
        "unit": "%",
        "label": "人口増加率",
    },
    "population-density": {
        "sid": SOCIAL_POPULATION_TABLE,
        "cat01": SOCIAL_METRIC_CODES["population_density"],
        "ascending": False,
        "unit": "人/km²",
        "label": "人口密度",
    },
    "elderly": {
        "sid": SOCIAL_POPULATION_TABLE,
        "cat01": SOCIAL_METRIC_CODES["elderly_pct"],
        "ascending": False,
        "unit": "%",
        "label": "高齢化率",
    },
    "avg-rent": {
        "sid": HOUSING_RENT_TABLE,
        "cat01": "1",
        "cat02": "1",
        "ascending": False,
        "unit": "円",
        "label": "平均家賃",
    },
}


def ranking_tabs() -> list[tuple[str, str]]:
    return [(key, meta["tab"]) for key, meta in FEATURE_RANKING_META.items()]


def _price_growth_rankings(db: Session, *, limit: int) -> list[RankingItem]:
    yearly = (
        select(
            MunicipalityTradeStat.municipality_code,
            MunicipalityTradeStat.trade_year,
            func.sum(MunicipalityTradeStat.transaction_count).label("cnt"),
            func.sum(MunicipalityTradeStat.trade_price_sum).label("psum"),
        )
        .where(
            MunicipalityTradeStat.price_classification == "01",
            MunicipalityTradeStat.property_type != "",
            MunicipalityTradeStat.property_type.isnot(None),
        )
        .group_by(
            MunicipalityTradeStat.municipality_code,
            MunicipalityTradeStat.trade_year,
        )
        .subquery()
    )
    rows = db.execute(
        select(
            yearly.c.municipality_code,
            yearly.c.trade_year,
            yearly.c.cnt,
            yearly.c.psum,
        ).order_by(yearly.c.municipality_code, yearly.c.trade_year)
    ).all()

    by_code: dict[str, list[tuple[int, int, float]]] = {}
    for code, year, cnt, psum in rows:
        if not cnt or not psum:
            continue
        by_code.setdefault(code, []).append((int(year), int(cnt), float(psum)))

    growth: list[tuple[str, float, int, float]] = []
    for code, series in by_code.items():
        if len(series) < 2:
            continue
        series.sort(key=lambda x: x[0])
        prev_year, prev_cnt, prev_sum = series[-2]
        cur_year, cur_cnt, cur_sum = series[-1]
        if cur_year - prev_year != 1:
            continue
        if prev_cnt < 80 or cur_cnt < 80:
            continue
        prev_avg = prev_sum / prev_cnt
        cur_avg = cur_sum / cur_cnt
        if prev_avg <= 0:
            continue
        pct = (cur_avg - prev_avg) / prev_avg * 100
        growth.append((code, pct, cur_cnt, cur_avg))

    growth.sort(key=lambda x: x[1], reverse=True)
    return _hydrate_ranking_items(
        db,
        growth[:limit],
        metric_unit="%",
        metric_label="価格上昇率",
    )


def _land_price_growth_rankings(db: Session, *, limit: int) -> list[RankingItem]:
    yearly = (
        select(
            LandPricePoint.municipality_code,
            LandPricePoint.survey_year,
            func.avg(LandPricePoint.unit_price).label("avg_price"),
            func.count(LandPricePoint.id).label("cnt"),
        )
        .where(LandPricePoint.unit_price.isnot(None))
        .group_by(LandPricePoint.municipality_code, LandPricePoint.survey_year)
        .subquery()
    )
    rows = db.execute(
        select(
            yearly.c.municipality_code,
            yearly.c.survey_year,
            yearly.c.avg_price,
            yearly.c.cnt,
        ).order_by(yearly.c.municipality_code, yearly.c.survey_year)
    ).all()
    by_code: dict[str, list[tuple[int, float, int]]] = {}
    for code, year, avg_price, cnt in rows:
        if avg_price is None:
            continue
        by_code.setdefault(code, []).append((int(year), float(avg_price), int(cnt)))

    growth: list[tuple[str, float, int, float]] = []
    for code, series in by_code.items():
        if len(series) < 2:
            continue
        series.sort(key=lambda x: x[0])
        prev_year, prev_avg, prev_cnt = series[-2]
        cur_year, cur_avg, cur_cnt = series[-1]
        if cur_year - prev_year != 1:
            continue
        if prev_cnt < 3 or cur_cnt < 3 or prev_avg <= 0:
            continue
        pct = (cur_avg - prev_avg) / prev_avg * 100
        growth.append((code, pct, cur_cnt, cur_avg))

    growth.sort(key=lambda x: x[1], reverse=True)
    return _hydrate_ranking_items(
        db,
        growth[:limit],
        metric_unit="%",
        metric_label="地価上昇率",
        secondary_is_unit_price=True,
    )


def _land_price_level_rankings(db: Session, *, limit: int) -> list[RankingItem]:
    latest_year = db.scalar(select(func.max(LandPricePoint.survey_year)))
    if not latest_year:
        return []
    rows = db.execute(
        select(
            LandPricePoint.municipality_code,
            func.avg(LandPricePoint.unit_price),
            func.count(LandPricePoint.id),
        )
        .where(
            LandPricePoint.survey_year == latest_year,
            LandPricePoint.unit_price.isnot(None),
        )
        .group_by(LandPricePoint.municipality_code)
        .having(func.count(LandPricePoint.id) >= 3)
        .order_by(func.avg(LandPricePoint.unit_price).desc())
        .limit(limit)
    ).all()
    packed = [
        (str(code), float(avg_price), int(cnt), float(avg_price))
        for code, avg_price, cnt in rows
        if avg_price is not None
    ]
    return _hydrate_ranking_items(
        db,
        packed,
        metric_unit="円/㎡",
        metric_label="平均地価",
    )


def _estat_rankings(db: Session, *, kind: str, limit: int) -> list[RankingItem]:
    if not _estat_db_available():
        return []

    spec = _ESTAT_RANKING_SPECS.get(kind)
    if not spec:
        return []

    sid = spec["sid"]
    cat = spec["cat01"]
    cat02 = spec.get("cat02")
    ascending = bool(spec["ascending"])
    unit = spec["unit"]
    label = spec["label"]

    if cat02 is not None:
        latest_extra = "AND cat02 = :cat02"
        outer_extra = "AND v.cat02 = :cat02"
    else:
        latest_extra = ""
        outer_extra = ""

    params: dict = {"sid": sid, "cat": cat}
    if cat02 is not None:
        params["cat02"] = cat02

    estat_db = EstatSessionLocal()
    try:
        rows = estat_db.execute(
            text(
                f"""
                SELECT v.area_code, v.value
                FROM estat_stat_values v
                INNER JOIN (
                    SELECT area_code, MAX(time_code) AS max_time
                    FROM estat_stat_values
                    WHERE stats_data_id = :sid AND cat01 = :cat AND value IS NOT NULL
                      {latest_extra}
                    GROUP BY area_code
                ) latest
                  ON latest.area_code = v.area_code AND latest.max_time = v.time_code
                WHERE v.stats_data_id = :sid AND v.cat01 = :cat AND v.value IS NOT NULL
                  {outer_extra}
                """
            ),
            params,
        ).all()
    finally:
        estat_db.close()

    values = [(str(code), float(value)) for code, value in rows if code and value is not None]
    values = [(c, v) for c, v in values if len(c) == 5]
    values.sort(key=lambda x: x[1], reverse=not ascending)
    packed = [(code, value, 0, value) for code, value in values[: limit * 2]]
    return _hydrate_ranking_items(
        db,
        packed,
        metric_unit=unit,
        metric_label=label,
    )[:limit]


def _hydrate_ranking_items(
    db: Session,
    rows: list[tuple[str, float, int, float]],
    *,
    metric_unit: str,
    metric_label: str,
    secondary_is_unit_price: bool = False,
) -> list[RankingItem]:
    if not rows:
        return []
    codes = [r[0] for r in rows]
    meta = {
        row[0]: row
        for row in db.execute(
            select(
                Municipality.code,
                Municipality.name_ja,
                Municipality.slug,
                Prefecture.name_ja,
                Prefecture.slug,
                MunicipalityPageMeta.total_transactions,
                MunicipalityPageMeta.recent_avg_price,
            )
            .join(Prefecture, Prefecture.code == Municipality.prefecture_code)
            .outerjoin(
                MunicipalityPageMeta,
                MunicipalityPageMeta.municipality_code == Municipality.code,
            )
            .where(Municipality.code.in_(codes))
        ).all()
    }
    items: list[RankingItem] = []
    for i, (code, metric_value, sample_count, secondary) in enumerate(rows):
        info = meta.get(code)
        if not info:
            continue
        items.append(
            RankingItem(
                rank=len(items) + 1,
                code=code,
                name_ja=info[1],
                slug=info[2],
                prefecture_name=info[3],
                prefecture_slug=info[4],
                total_transactions=int(info[5] or 0),
                recent_avg_price=None if secondary_is_unit_price else (info[6] or secondary),
                metric_value=round(metric_value, 2),
                metric_unit=metric_unit,
                metric_label=metric_label,
                secondary_value=round(secondary, 1) if secondary_is_unit_price else None,
                secondary_label="平均地価（円/㎡）" if secondary_is_unit_price else None,
                sample_count=sample_count or None,
            )
        )
        if len(items) >= len(rows):
            break
    # re-rank after filtering missing
    for i, item in enumerate(items):
        item.rank = i + 1
    return items
