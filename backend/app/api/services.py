from __future__ import annotations

from time import time as time_time
from typing import Optional

from sqlalchemy import func, select
from sqlalchemy.orm import Session, joinedload

from app.api.schemas import (
    CompareSide,
    CompareView,
    DistrictSearchResult,
    HomeChartData,
    HomeHighlights,
    LandPricePointItem,
    LandPriceSummary,
    LandPriceYearlyStat,
    MunicipalityDetail,
    MunicipalityEstatInsights,
    MunicipalitySummary,
    PrefectureChartData,
    PrefectureSummary,
    RankingItem,
    ReportContext,
    SearchResult,
    StationDetail,
    StationMunicipalityPrice,
    StationSummary,
    StationYearlyPassenger,
    StatBucket,
    TransactionItem,
    TransactionPage,
    YearlyStat,
)
from app.db import (
    District,
    LandPricePoint,
    Municipality,
    MunicipalityPageMeta,
    MunicipalityTradeStat,
    Prefecture,
    StationPassenger,
    TradeTransaction,
)
from app.reinfolib.district_pages import DISTRICT_MIN_TRANSACTIONS, district_area_slug
from app.reinfolib.purchase_insights import get_purchase_insights, renovation_from_raw
from app.estat.municipality_insights import get_municipality_estat_insights
from app.api.value_insights import build_cross_metrics, get_similar_municipalities
from app.reinfolib.station_passengers import (
    haversine_m,
    normalize_station_name,
    passengers_json_loads,
)


def list_prefectures(db: Session) -> list[PrefectureSummary]:
    rows = db.execute(
        select(
            Prefecture.code,
            Prefecture.name_ja,
            Prefecture.slug,
            func.count(Municipality.code),
            func.coalesce(func.sum(MunicipalityPageMeta.total_transactions), 0),
            func.avg(MunicipalityPageMeta.recent_avg_price),
        )
        .join(Municipality, Municipality.prefecture_code == Prefecture.code)
        .outerjoin(
            MunicipalityPageMeta,
            MunicipalityPageMeta.municipality_code == Municipality.code,
        )
        .group_by(Prefecture.code, Prefecture.name_ja, Prefecture.slug)
        .order_by(Prefecture.code)
    ).all()
    return [
        PrefectureSummary(
            code=row[0],
            name_ja=row[1],
            slug=row[2],
            municipality_count=row[3],
            total_transactions=int(row[4] or 0),
            avg_price=float(row[5]) if row[5] is not None else None,
        )
        for row in rows
    ]


def _median(values: list[float]) -> Optional[float]:
    if not values:
        return None
    ordered = sorted(values)
    mid = len(ordered) // 2
    if len(ordered) % 2:
        return ordered[mid]
    return (ordered[mid - 1] + ordered[mid]) / 2


def _enrich_prefecture_price_stats(
    db: Session, prefectures: list[PrefectureSummary]
) -> list[PrefectureSummary]:
    """市区町村平均の中央値と、年次集計からの前年比を付与。"""
    if not prefectures:
        return prefectures

    muni_price_rows = db.execute(
        select(
            Municipality.prefecture_code,
            MunicipalityPageMeta.recent_avg_price,
        )
        .join(
            MunicipalityPageMeta,
            MunicipalityPageMeta.municipality_code == Municipality.code,
        )
        .where(MunicipalityPageMeta.recent_avg_price.isnot(None))
    ).all()
    prices_by_pref: dict[str, list[float]] = {}
    for pref_code, price in muni_price_rows:
        prices_by_pref.setdefault(pref_code, []).append(float(price))

    yearly_rows = db.execute(
        select(
            Municipality.prefecture_code,
            MunicipalityTradeStat.trade_year,
            func.sum(MunicipalityTradeStat.transaction_count),
            func.sum(MunicipalityTradeStat.trade_price_sum),
        )
        .join(Municipality, Municipality.code == MunicipalityTradeStat.municipality_code)
        .where(MunicipalityTradeStat.price_classification == "01")
        .group_by(Municipality.prefecture_code, MunicipalityTradeStat.trade_year)
        .order_by(Municipality.prefecture_code, MunicipalityTradeStat.trade_year)
    ).all()
    yearly_avg: dict[str, list[tuple[int, float]]] = {}
    for pref_code, year, cnt, psum in yearly_rows:
        if not cnt or not psum:
            continue
        yearly_avg.setdefault(pref_code, []).append((int(year), float(psum) / float(cnt)))

    yoy_by_pref: dict[str, float] = {}
    for pref_code, series in yearly_avg.items():
        if len(series) < 2:
            continue
        _prev_year, prev_avg = series[-2]
        _cur_year, cur_avg = series[-1]
        if prev_avg:
            yoy_by_pref[pref_code] = (cur_avg - prev_avg) / prev_avg * 100

    for pref in prefectures:
        pref.median_price = _median(prices_by_pref.get(pref.code, []))
        pref.yoy_price_change_pct = yoy_by_pref.get(pref.code)
    return prefectures


def get_prefecture_by_slug(db: Session, slug: str) -> Optional[Prefecture]:
    return db.scalar(select(Prefecture).where(Prefecture.slug == slug))


def list_municipalities_for_prefecture(
    db: Session, prefecture: Prefecture
) -> list[MunicipalitySummary]:
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
        .outerjoin(
            MunicipalityPageMeta,
            MunicipalityPageMeta.municipality_code == Municipality.code,
        )
        .where(Municipality.prefecture_code == prefecture.code)
        .order_by(MunicipalityPageMeta.total_transactions.desc().nullslast(), Municipality.code)
    ).all()
    return [
        MunicipalitySummary(
            code=row[0],
            name_ja=row[1],
            slug=row[2],
            total_transactions=int(row[3] or 0),
            recent_avg_price=row[4],
            latest_year=row[5],
            latest_quarter=row[6],
        )
        for row in rows
    ]


def resolve_municipality(
    db: Session, prefecture_slug: str, municipality_slug: str
) -> tuple[Optional[Prefecture], Optional[Municipality]]:
    prefecture = get_prefecture_by_slug(db, prefecture_slug)
    if not prefecture:
        return None, None
    municipality = db.scalar(
        select(Municipality)
        .options(joinedload(Municipality.page_meta))
        .where(
            Municipality.prefecture_code == prefecture.code,
            (Municipality.slug == municipality_slug)
            | (Municipality.code == municipality_slug),
        )
    )
    return prefecture, municipality


def search_municipalities(db: Session, query: str, limit: int = 12) -> list[SearchResult]:
    q = query.strip()
    if not q:
        return []
    pattern = f"%{q}%"
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
        .outerjoin(
            MunicipalityPageMeta,
            MunicipalityPageMeta.municipality_code == Municipality.code,
        )
        .where(Municipality.name_ja.like(pattern))
        .order_by(MunicipalityPageMeta.total_transactions.desc().nullslast())
        .limit(limit)
    ).all()
    return [
        SearchResult(
            code=row[0],
            name_ja=row[1],
            slug=row[2],
            prefecture_name=row[3],
            prefecture_slug=row[4],
            total_transactions=int(row[5] or 0),
            recent_avg_price=row[6],
        )
        for row in rows
    ]


def get_rankings(
    db: Session, *, sort: str = "volume", limit: int = 50
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


def get_home_highlights(db: Session) -> HomeHighlights:
    from app.api.value_insights import get_feature_rankings

    prefectures = list_prefectures(db)
    total_tx = sum(p.total_transactions for p in prefectures)
    muni_count = sum(p.municipality_count for p in prefectures)
    top_by_price = _enrich_ranking_yoy(db, get_rankings(db, sort="price", limit=10))
    top_by_yoy = get_feature_rankings(db, kind="price-growth", limit=10)
    for item in top_by_yoy:
        if item.yoy_price_change_pct is None and item.metric_value is not None:
            item.yoy_price_change_pct = float(item.metric_value)
    return HomeHighlights(
        top_by_volume=get_rankings(db, sort="volume", limit=10),
        top_by_price=top_by_price,
        top_by_yoy=top_by_yoy,
        total_transactions=total_tx,
        municipality_count=muni_count,
    )


def _enrich_ranking_yoy(db: Session, items: list[RankingItem]) -> list[RankingItem]:
    if not items:
        return items
    codes = [item.code for item in items]
    yearly_rows = db.execute(
        select(
            MunicipalityTradeStat.municipality_code,
            MunicipalityTradeStat.trade_year,
            func.sum(MunicipalityTradeStat.transaction_count),
            func.sum(MunicipalityTradeStat.trade_price_sum),
        )
        .where(
            MunicipalityTradeStat.municipality_code.in_(codes),
            MunicipalityTradeStat.price_classification == "01",
        )
        .group_by(
            MunicipalityTradeStat.municipality_code,
            MunicipalityTradeStat.trade_year,
        )
        .order_by(
            MunicipalityTradeStat.municipality_code,
            MunicipalityTradeStat.trade_year,
        )
    ).all()
    by_code: dict[str, list[tuple[int, float]]] = {}
    for code, year, cnt, psum in yearly_rows:
        if not cnt or not psum:
            continue
        by_code.setdefault(code, []).append((int(year), float(psum) / float(cnt)))
    for item in items:
        series = by_code.get(item.code, [])
        if len(series) < 2:
            continue
        _prev_year, prev_avg = series[-2]
        _cur_year, cur_avg = series[-1]
        if prev_avg:
            item.yoy_price_change_pct = (cur_avg - prev_avg) / prev_avg * 100
    return items


_home_chart_cache: Optional[tuple[float, HomeChartData]] = None
_HOME_CHART_TTL_SEC = 600


def get_home_chart_data(db: Session) -> HomeChartData:
    global _home_chart_cache
    now = time_time()
    if _home_chart_cache and now - _home_chart_cache[0] < _HOME_CHART_TTL_SEC:
        return _home_chart_cache[1]

    quarterly = (
        select(
            MunicipalityTradeStat.trade_year,
            func.sum(MunicipalityTradeStat.transaction_count).label("cnt"),
            func.sum(MunicipalityTradeStat.trade_price_sum).label("psum"),
        )
        .where(MunicipalityTradeStat.price_classification == "01")
        .group_by(
            MunicipalityTradeStat.municipality_code,
            MunicipalityTradeStat.trade_year,
            MunicipalityTradeStat.trade_quarter,
        )
        .subquery()
    )
    rows = db.execute(
        select(
            quarterly.c.trade_year,
            func.sum(quarterly.c.cnt),
            func.sum(quarterly.c.psum),
        )
        .group_by(quarterly.c.trade_year)
        .order_by(quarterly.c.trade_year)
    ).all()
    yearly: list[YearlyStat] = []
    for row in rows:
        yearly.append(
            YearlyStat(
                trade_year=row[0],
                transaction_count=int(row[1] or 0),
                trade_price_avg=(int(row[2]) / int(row[1])) if row[1] else None,
            )
        )
    for i in range(1, len(yearly)):
        prev = yearly[i - 1]
        cur = yearly[i]
        if prev.transaction_count:
            cur.yoy_transaction_pct = (
                (cur.transaction_count - prev.transaction_count) / prev.transaction_count * 100
            )

    prefectures = _enrich_prefecture_price_stats(db, list_prefectures(db))
    with_price = [p for p in prefectures if p.avg_price]
    top_price = sorted(with_price, key=lambda p: p.avg_price or 0, reverse=True)[:10]
    top_yoy = sorted(
        [p for p in prefectures if p.yoy_price_change_pct is not None],
        key=lambda p: p.yoy_price_change_pct or 0,
        reverse=True,
    )[:10]
    top_vol = sorted(
        [p for p in prefectures if p.total_transactions > 0],
        key=lambda p: p.total_transactions,
        reverse=True,
    )[:10]

    result = HomeChartData(
        yearly_stats=yearly,
        land_price_yearly=get_national_land_price_yearly_stats(db),
        top_prefectures_volume=top_vol,
        top_prefectures_price=top_price,
        top_prefectures_yoy=top_yoy,
    )
    _home_chart_cache = (now, result)
    return result


def _attach_land_price_yoy(stats: list[LandPriceYearlyStat]) -> list[LandPriceYearlyStat]:
    for i in range(1, len(stats)):
        prev = stats[i - 1]
        cur = stats[i]
        if prev.avg_unit_price and cur.avg_unit_price:
            cur.yoy_avg_price_pct = (
                (cur.avg_unit_price - prev.avg_unit_price) / prev.avg_unit_price * 100
            )
    return stats


def _land_price_yearly_from_rows(rows) -> list[LandPriceYearlyStat]:
    stats = [
        LandPriceYearlyStat(
            survey_year=row[0],
            point_count=int(row[1]),
            avg_unit_price=row[2],
        )
        for row in rows
    ]
    return _attach_land_price_yoy(stats)


def _query_land_price_yearly_stats(db: Session, *filters) -> list[LandPriceYearlyStat]:
    rows = db.execute(
        select(
            LandPricePoint.survey_year,
            func.count(LandPricePoint.id),
            func.avg(LandPricePoint.unit_price),
        )
        .where(LandPricePoint.unit_price.isnot(None), *filters)
        .group_by(LandPricePoint.survey_year)
        .order_by(LandPricePoint.survey_year)
    ).all()
    return _land_price_yearly_from_rows(rows)


def get_national_land_price_yearly_stats(db: Session) -> list[LandPriceYearlyStat]:
    return _query_land_price_yearly_stats(db)


def get_prefecture_land_price_yearly_stats(
    db: Session, prefecture_code: str
) -> list[LandPriceYearlyStat]:
    return _query_land_price_yearly_stats(
        db, LandPricePoint.prefecture_code == prefecture_code
    )


def get_land_price_summary(db: Session, municipality_code: str) -> Optional[LandPriceSummary]:
    latest_year = db.scalar(
        select(func.max(LandPricePoint.survey_year)).where(
            LandPricePoint.municipality_code == municipality_code
        )
    )
    if not latest_year:
        return None
    rows = db.execute(
        select(
            func.count(LandPricePoint.id),
            func.avg(LandPricePoint.unit_price),
            func.max(LandPricePoint.unit_price),
            func.min(LandPricePoint.unit_price),
            func.avg(LandPricePoint.year_on_year_change_rate),
        ).where(
            LandPricePoint.municipality_code == municipality_code,
            LandPricePoint.survey_year == latest_year,
            LandPricePoint.unit_price.isnot(None),
        )
    ).one()
    if not rows[0]:
        return None
    return LandPriceSummary(
        point_count=int(rows[0]),
        latest_year=latest_year,
        avg_unit_price=rows[1],
        max_unit_price=rows[2],
        min_unit_price=rows[3],
        yoy_change_avg=rows[4],
    )


def get_land_price_yearly_stats(
    db: Session, municipality_code: str
) -> list[LandPriceYearlyStat]:
    return _query_land_price_yearly_stats(
        db, LandPricePoint.municipality_code == municipality_code
    )


def list_land_price_points(
    db: Session,
    municipality_code: str,
    survey_year: Optional[int] = None,
    limit: int = 200,
) -> list[LandPricePointItem]:
    if survey_year is None:
        survey_year = db.scalar(
            select(func.max(LandPricePoint.survey_year)).where(
                LandPricePoint.municipality_code == municipality_code
            )
        )
    if not survey_year:
        return []
    rows = db.scalars(
        select(LandPricePoint)
        .where(
            LandPricePoint.municipality_code == municipality_code,
            LandPricePoint.survey_year == survey_year,
            LandPricePoint.latitude.isnot(None),
            LandPricePoint.longitude.isnot(None),
        )
        .order_by(LandPricePoint.unit_price.desc().nullslast())
        .limit(limit)
    ).all()
    return [_land_point_to_item(row) for row in rows]


def _land_point_to_item(row: LandPricePoint) -> LandPricePointItem:
    return LandPricePointItem(
        id=row.id,
        point_id=row.point_id,
        survey_year=row.survey_year,
        location=row.location,
        standard_lot_number=row.standard_lot_number,
        unit_price=row.unit_price,
        year_on_year_change_rate=row.year_on_year_change_rate,
        area_sqm=row.area_sqm,
        latitude=row.latitude,
        longitude=row.longitude,
        nearest_station=row.nearest_station,
        use_category_name=row.use_category_name,
    )


def _tx_to_item(tx: TradeTransaction) -> TransactionItem:
    return TransactionItem(
        id=tx.id,
        trade_year=tx.trade_year,
        trade_quarter=tx.trade_quarter,
        property_type=tx.property_type,
        district_name=tx.district_name,
        trade_price=tx.trade_price,
        unit_price=tx.unit_price,
        area=tx.area,
        period_label=tx.period_label,
        building_year=tx.building_year,
        structure=tx.structure,
        city_planning=tx.city_planning,
        floor_plan=tx.floor_plan,
        renovation=renovation_from_raw(tx.raw_json),
    )


def get_transactions_page(
    db: Session,
    municipality_code: str,
    page: int = 1,
    page_size: int = 20,
    property_type: str = "",
    price_classification: str = "01",
) -> TransactionPage:
    page = max(1, page)
    page_size = min(max(1, page_size), 100)
    base = select(TradeTransaction).where(
        TradeTransaction.municipality_code == municipality_code,
        TradeTransaction.price_classification == price_classification,
    )
    if property_type:
        base = base.where(TradeTransaction.property_type == property_type)

    total = db.scalar(
        select(func.count(TradeTransaction.id)).where(
            TradeTransaction.municipality_code == municipality_code,
            TradeTransaction.price_classification == price_classification,
            *(
                [TradeTransaction.property_type == property_type]
                if property_type
                else []
            ),
        )
    ) or 0
    offset = (page - 1) * page_size
    rows = db.scalars(
        base.order_by(
            TradeTransaction.trade_year.desc(),
            TradeTransaction.trade_quarter.desc(),
            TradeTransaction.id.desc(),
        )
        .offset(offset)
        .limit(page_size)
    ).all()
    return TransactionPage(
        items=[_tx_to_item(tx) for tx in rows],
        total=total,
        page=page,
        page_size=page_size,
        has_more=offset + len(rows) < total,
    )


def search_districts(
    db: Session, query: str, limit: int = 20
) -> list[DistrictSearchResult]:
    q = query.strip()
    if not q:
        return []
    pattern = f"%{q}%"
    rows = db.execute(
        select(
            District.code,
            District.name,
            Municipality.name_ja,
            Municipality.slug,
            Prefecture.slug,
            func.count(TradeTransaction.id),
        )
        .join(Municipality, Municipality.code == District.municipality_code)
        .join(Prefecture, Prefecture.code == Municipality.prefecture_code)
        .outerjoin(
            TradeTransaction,
            TradeTransaction.district_code == District.code,
        )
        .where(District.name.like(pattern))
        .group_by(
            District.code,
            District.name,
            Municipality.name_ja,
            Municipality.slug,
            Prefecture.slug,
        )
        .having(func.count(TradeTransaction.id) >= DISTRICT_MIN_TRANSACTIONS)
        .order_by(func.count(TradeTransaction.id).desc())
        .limit(limit)
    ).all()
    used_by_muni: dict[str, set[str]] = {}
    result: list[DistrictSearchResult] = []
    for row in rows:
        muni_slug = row[3]
        used = used_by_muni.setdefault(muni_slug, set())
        result.append(
            DistrictSearchResult(
                code=row[0],
                name=row[1],
                municipality_name=row[2],
                municipality_slug=muni_slug,
                prefecture_slug=row[4],
                transaction_count=int(row[5] or 0),
                area_slug=district_area_slug(row[1], row[0], used=used),
            )
        )
    return result


REPORT_TYPE_LABELS = {
    "seller": "売主向け（周辺取引事例）",
    "buyer": "買主向け（エリア相場説明）",
    "appraisal": "査定用（価格根拠資料）",
}


def build_report_context(report_type: str = "seller", period_years: int = 2) -> ReportContext:
    report_type = report_type if report_type in REPORT_TYPE_LABELS else "seller"
    period_years = period_years if period_years in (1, 2, 3, 5) else 2
    period_label = {
        1: "直近1年 + 年次推移",
        2: "直近2年 + 年次推移",
        3: "直近3年 + 年次推移",
        5: "直近5年 + 年次推移",
    }[period_years]
    return ReportContext(
        report_type=report_type,
        period_years=period_years,
        report_type_label=REPORT_TYPE_LABELS[report_type],
        period_label=period_label,
    )


def _to_stat(row: MunicipalityTradeStat) -> StatBucket:
    return StatBucket(
        trade_year=row.trade_year,
        trade_quarter=row.trade_quarter,
        property_type=row.property_type,
        transaction_count=row.transaction_count,
        trade_price_avg=row.trade_price_avg,
        unit_price_avg=row.unit_price_avg,
        area_avg=row.area_avg,
    )


MUNICIPALITY_EMBED_TRANSACTION_LIMIT = 400
SIMULATOR_RECENT_YEARS = 5


def get_municipality_embed_transactions(
    db: Session,
    municipality_code: str,
    *,
    limit: int = MUNICIPALITY_EMBED_TRANSACTION_LIMIT,
    min_trade_year: Optional[int] = None,
) -> list[TransactionItem]:
    filters = [
        TradeTransaction.municipality_code == municipality_code,
        TradeTransaction.price_classification == "01",
        TradeTransaction.district_name.isnot(None),
        TradeTransaction.district_name != "",
    ]
    if min_trade_year is not None:
        filters.append(TradeTransaction.trade_year >= min_trade_year)
    rows = db.scalars(
        select(TradeTransaction)
        .where(*filters)
        .order_by(
            TradeTransaction.trade_year.desc(),
            TradeTransaction.trade_quarter.desc(),
            TradeTransaction.id.desc(),
        )
        .limit(limit)
    ).all()
    return [_tx_to_item(tx) for tx in rows]


def _aggregate_quarterly_stats(rows: list[MunicipalityTradeStat]) -> list[StatBucket]:
    buckets: dict[tuple[int, int], dict] = {}
    for row in rows:
        key = (row.trade_year, row.trade_quarter)
        if key not in buckets:
            buckets[key] = {"count": 0, "price_sum": 0, "unit_weighted": 0.0, "unit_count": 0}
        b = buckets[key]
        count = row.transaction_count or 0
        b["count"] += count
        if row.trade_price_sum:
            b["price_sum"] += int(row.trade_price_sum)
        elif row.trade_price_avg and count:
            b["price_sum"] += int(row.trade_price_avg * count)
        if row.unit_price_avg and count:
            b["unit_weighted"] += float(row.unit_price_avg) * count
            b["unit_count"] += count
    return [
        StatBucket(
            trade_year=year,
            trade_quarter=quarter,
            property_type="",
            transaction_count=b["count"],
            trade_price_avg=(b["price_sum"] / b["count"]) if b["count"] else None,
            unit_price_avg=(b["unit_weighted"] / b["unit_count"]) if b["unit_count"] else None,
        )
        for (year, quarter), b in sorted(buckets.items())
    ]


def _aggregate_yearly_stats(quarterly: list[StatBucket]) -> list[YearlyStat]:
    buckets: dict[int, dict] = {}
    for row in quarterly:
        year = row.trade_year
        if year not in buckets:
            buckets[year] = {"count": 0, "price_sum": 0.0, "unit_weighted": 0.0, "unit_count": 0}
        b = buckets[year]
        count = row.transaction_count or 0
        b["count"] += count
        if row.trade_price_avg and count:
            b["price_sum"] += float(row.trade_price_avg) * count
        if row.unit_price_avg and count:
            b["unit_weighted"] += float(row.unit_price_avg) * count
            b["unit_count"] += count
    return [
        YearlyStat(
            trade_year=year,
            transaction_count=b["count"],
            trade_price_avg=(b["price_sum"] / b["count"]) if b["count"] else None,
            unit_price_avg=(b["unit_weighted"] / b["unit_count"]) if b["unit_count"] else None,
        )
        for year, b in sorted(buckets.items())
    ]


def get_prefecture_chart_data(
    db: Session, prefecture: Prefecture, municipalities: list[MunicipalitySummary]
) -> PrefectureChartData:
    rows = db.execute(
        select(
            MunicipalityTradeStat.trade_year,
            func.sum(MunicipalityTradeStat.transaction_count),
            func.sum(MunicipalityTradeStat.trade_price_sum),
        )
        .join(Municipality, Municipality.code == MunicipalityTradeStat.municipality_code)
        .where(
            Municipality.prefecture_code == prefecture.code,
            MunicipalityTradeStat.price_classification == "01",
        )
        .group_by(MunicipalityTradeStat.trade_year)
        .order_by(MunicipalityTradeStat.trade_year)
    ).all()
    yearly = [
        YearlyStat(
            trade_year=row[0],
            transaction_count=int(row[1] or 0),
            trade_price_avg=(int(row[2]) / int(row[1])) if row[1] else None,
        )
        for row in rows
    ]
    top = sorted(municipalities, key=lambda m: m.total_transactions, reverse=True)[:12]
    return PrefectureChartData(
        yearly_stats=yearly,
        land_price_yearly=get_prefecture_land_price_yearly_stats(db, prefecture.code),
        top_municipalities=top,
        top_stations=list_stations_for_prefecture(db, prefecture.code, limit=12),
    )


def get_municipality_detail(
    db: Session, prefecture: Prefecture, municipality: Municipality
) -> MunicipalityDetail:
    meta = municipality.page_meta
    stat_rows = db.scalars(
        select(MunicipalityTradeStat)
        .where(
            MunicipalityTradeStat.municipality_code == municipality.code,
            MunicipalityTradeStat.price_classification == "01",
        )
        .order_by(
            MunicipalityTradeStat.trade_year.asc(),
            MunicipalityTradeStat.trade_quarter.asc(),
        )
    ).all()
    quarterly_chart = _aggregate_quarterly_stats(stat_rows)
    quarterly_stats = list(reversed(quarterly_chart[-12:]))
    yearly_stats = _aggregate_yearly_stats(quarterly_chart)

    latest_year = meta.latest_year if meta else None
    latest_quarter = meta.latest_quarter if meta else None
    property_stats = db.scalars(
        select(MunicipalityTradeStat)
        .where(
            MunicipalityTradeStat.municipality_code == municipality.code,
            MunicipalityTradeStat.price_classification == "01",
            MunicipalityTradeStat.property_type != "",
        )
        .order_by(
            MunicipalityTradeStat.trade_year.asc(),
            MunicipalityTradeStat.trade_quarter.asc(),
            MunicipalityTradeStat.transaction_count.desc(),
        )
    ).all()

    min_trade_year = (
        latest_year - (SIMULATOR_RECENT_YEARS - 1) if latest_year else None
    )
    transactions = get_municipality_embed_transactions(
        db, municipality.code, min_trade_year=min_trade_year
    )

    yoy = _compute_yoy_change(yearly_stats)
    related = get_related_municipalities(db, prefecture.code, municipality.code)

    def to_stat(row: MunicipalityTradeStat) -> StatBucket:
        return _to_stat(row)

    land_summary = get_land_price_summary(db, municipality.code)
    purchase_insights = get_purchase_insights(
        db,
        municipality.code,
        latest_year=latest_year,
        land_price_avg=float(land_summary.avg_unit_price)
        if land_summary and land_summary.avg_unit_price
        else None,
    )

    estat_raw = get_municipality_estat_insights(municipality.code)
    estat_insights = (
        MunicipalityEstatInsights.model_validate(estat_raw) if estat_raw else None
    )
    cross_metrics = build_cross_metrics(
        yoy_price_change_pct=yoy,
        purchase_insights=purchase_insights,
        estat=estat_insights,
    )
    similar_municipalities = get_similar_municipalities(
        db,
        prefecture_code=prefecture.code,
        municipality_code=municipality.code,
        recent_avg_price=meta.recent_avg_price if meta else None,
        estat=estat_insights,
    )

    return MunicipalityDetail(
        code=municipality.code,
        name_ja=municipality.name_ja,
        slug=municipality.slug,
        prefecture_code=prefecture.code,
        prefecture_name=prefecture.name_ja,
        prefecture_slug=prefecture.slug,
        total_transactions=meta.total_transactions if meta else 0,
        recent_avg_price=meta.recent_avg_price if meta else None,
        latest_year=latest_year,
        latest_quarter=latest_quarter,
        quarterly_stats=quarterly_stats,
        quarterly_chart=quarterly_chart,
        yearly_stats=yearly_stats,
        property_stats=[to_stat(row) for row in property_stats],
        recent_transactions=transactions,
        stats_updated_at=meta.stats_updated_at if meta else None,
        land_prices=land_summary,
        land_price_yearly=get_land_price_yearly_stats(db, municipality.code),
        related_municipalities=related,
        similar_municipalities=similar_municipalities,
        yoy_price_change_pct=yoy,
        purchase_insights=purchase_insights,
        estat_insights=estat_insights,
        cross_metrics=cross_metrics,
    )


POPULAR_AREAS: list[tuple[str, str, str]] = [
    ("tokyo", "shibuya-ku", "渋谷区"),
    ("tokyo", "shinjuku-ku", "新宿区"),
    ("tokyo", "minato-ku", "港区"),
    ("tokyo", "chiyoda-ku", "千代田区"),
    ("osaka", "kita-ku", "大阪市北区"),
    ("kanagawa", "naka-ku", "横浜市中区"),
    ("aichi", "naka-ku", "名古屋市中区"),
    ("fukuoka", "chuuou-ku", "福岡市中央区"),
]

# (a_pref, a_muni, b_pref, b_muni, a_label, b_label)
POPULAR_COMPARES: list[tuple[str, str, str, str, str, str]] = [
    ("tokyo", "shibuya-ku", "tokyo", "minato-ku", "渋谷区", "港区"),
    ("tokyo", "shinjuku-ku", "tokyo", "chiyoda-ku", "新宿区", "千代田区"),
    ("kanagawa", "naka-ku", "kanagawa", "nishi-ku", "横浜市中区", "横浜市西区"),
    ("osaka", "kita-ku", "aichi", "naka-ku", "大阪市北区", "名古屋市中区"),
    ("fukuoka", "chuuou-ku", "fukuoka", "fukuoka-shi", "福岡市中央区", "福岡市"),
]


def compare_path(
    a_pref: str, a_muni: str, b_pref: str, b_muni: str
) -> str:
    return f"/compare/{a_pref}/{a_muni}/vs/{b_pref}/{b_muni}"


def _compute_yoy_change(yearly_stats: list[YearlyStat]) -> Optional[float]:
    if len(yearly_stats) < 2:
        return None
    latest = yearly_stats[-1]
    prev = yearly_stats[-2]
    if not latest.trade_price_avg or not prev.trade_price_avg:
        return None
    return (latest.trade_price_avg - prev.trade_price_avg) / prev.trade_price_avg * 100


def get_related_municipalities(
    db: Session, prefecture_code: str, exclude_code: str, limit: int = 6
) -> list[MunicipalitySummary]:
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
        .join(MunicipalityPageMeta, MunicipalityPageMeta.municipality_code == Municipality.code)
        .where(
            Municipality.prefecture_code == prefecture_code,
            Municipality.code != exclude_code,
            MunicipalityPageMeta.total_transactions > 0,
        )
        .order_by(MunicipalityPageMeta.total_transactions.desc())
        .limit(limit)
    ).all()
    return [
        MunicipalitySummary(
            code=row[0],
            name_ja=row[1],
            slug=row[2],
            total_transactions=int(row[3] or 0),
            recent_avg_price=row[4],
            latest_year=row[5],
            latest_quarter=row[6],
        )
        for row in rows
    ]


def _latest_property_stats(
    rows: list[StatBucket],
    *,
    latest_year: Optional[int] = None,
    latest_quarter: Optional[int] = None,
) -> list[StatBucket]:
    if not rows:
        return []
    year = latest_year if latest_year is not None else max(r.trade_year for r in rows)
    quarter = (
        latest_quarter
        if latest_quarter is not None
        else max(r.trade_quarter for r in rows if r.trade_year == year)
    )
    return [r for r in rows if r.trade_year == year and r.trade_quarter == quarter]


def _municipality_to_compare_side(
    db: Session, prefecture: Prefecture, municipality: Municipality
) -> CompareSide:
    detail = get_municipality_detail(db, prefecture, municipality)
    return CompareSide(
        code=detail.code,
        name_ja=detail.name_ja,
        slug=detail.slug,
        prefecture_name=detail.prefecture_name,
        prefecture_slug=detail.prefecture_slug,
        total_transactions=detail.total_transactions,
        recent_avg_price=detail.recent_avg_price,
        yearly_stats=detail.yearly_stats,
        property_stats=_latest_property_stats(
            detail.property_stats,
            latest_year=detail.latest_year,
            latest_quarter=detail.latest_quarter,
        ),
        yoy_price_change_pct=detail.yoy_price_change_pct,
        land_prices=detail.land_prices,
        land_price_yearly=detail.land_price_yearly,
    )


def _prefecture_lookup(db: Session) -> dict[str, Prefecture]:
    return {p.code: p for p in db.scalars(select(Prefecture)).all()}


def _station_to_summary(row: StationPassenger, pref: Optional[Prefecture] = None) -> StationSummary:
    return StationSummary(
        id=row.id,
        station_name=row.station_name,
        line_name=row.line_name,
        operator_name=row.operator_name,
        prefecture_code=row.prefecture_code,
        prefecture_slug=pref.slug if pref else None,
        prefecture_name=pref.name_ja if pref else None,
        latest_year=row.latest_year,
        latest_passengers=row.latest_passengers,
    )


def _station_yearly_passengers(row: StationPassenger) -> list[StationYearlyPassenger]:
    counts = passengers_json_loads(row.passengers_json)
    years = sorted(counts)
    result: list[StationYearlyPassenger] = []
    for i, year in enumerate(years):
        yoy = None
        if i > 0:
            prev = counts[years[i - 1]]
            cur = counts[year]
            if prev:
                yoy = (cur - prev) / prev * 100
        result.append(StationYearlyPassenger(year=year, passengers=counts[year], yoy_pct=yoy))
    return result


def get_station_detail(db: Session, station_id: int) -> Optional[StationDetail]:
    row = db.get(StationPassenger, station_id)
    if not row:
        return None
    pref = None
    if row.prefecture_code:
        pref = db.scalar(select(Prefecture).where(Prefecture.code == row.prefecture_code))
    base = _station_to_summary(row, pref)

    nearby_municipalities: list[StationMunicipalityPrice] = []
    nearby_land_price_avg = None
    nearby_land_price_point_count = 0
    station_norm = normalize_station_name(row.station_name)

    land_filters = [
        LandPricePoint.nearest_station.isnot(None),
        LandPricePoint.unit_price.isnot(None),
    ]
    if row.prefecture_code:
        land_filters.append(
            LandPricePoint.municipality_code.startswith(row.prefecture_code)
        )

    land_rows = db.execute(
        select(
            LandPricePoint.municipality_code,
            LandPricePoint.nearest_station,
            LandPricePoint.unit_price,
            LandPricePoint.survey_year,
        ).where(*land_filters)
    ).all()

    matched_by_muni: dict[str, list[float]] = {}
    latest_year_by_muni: dict[str, int] = {}
    for muni_code, nearest, unit_price, survey_year in land_rows:
        if not nearest or unit_price is None:
            continue
        nearest_norm = normalize_station_name(nearest)
        if not (
            nearest_norm == station_norm
            or station_norm in nearest
            or nearest_norm in row.station_name
        ):
            continue
        matched_by_muni.setdefault(muni_code, []).append(float(unit_price))
        year = int(survey_year or 0)
        if year > latest_year_by_muni.get(muni_code, 0):
            latest_year_by_muni[muni_code] = year

    all_prices: list[float] = []
    for prices in matched_by_muni.values():
        all_prices.extend(prices)
    if all_prices:
        nearby_land_price_avg = sum(all_prices) / len(all_prices)
        nearby_land_price_point_count = len(all_prices)

    if matched_by_muni:
        muni_rows = db.execute(
            select(
                Municipality.code,
                Municipality.name_ja,
                Municipality.slug,
                Prefecture.name_ja,
                Prefecture.slug,
                MunicipalityPageMeta.recent_avg_price,
            )
            .join(Prefecture, Prefecture.code == Municipality.prefecture_code)
            .outerjoin(
                MunicipalityPageMeta,
                MunicipalityPageMeta.municipality_code == Municipality.code,
            )
            .where(Municipality.code.in_(list(matched_by_muni.keys())))
        ).all()
        for muni in muni_rows:
            prices = matched_by_muni.get(muni[0], [])
            nearby_municipalities.append(
                StationMunicipalityPrice(
                    code=muni[0],
                    name_ja=muni[1],
                    slug=muni[2],
                    prefecture_name=muni[3],
                    prefecture_slug=muni[4],
                    recent_avg_price=muni[5],
                    land_price_avg=(sum(prices) / len(prices)) if prices else None,
                    matched_point_count=len(prices),
                )
            )
        nearby_municipalities.sort(
            key=lambda item: item.matched_point_count, reverse=True
        )

    return StationDetail(
        **base.model_dump(),
        railway_type=row.railway_type,
        latitude=row.latitude,
        longitude=row.longitude,
        yearly_passengers=_station_yearly_passengers(row),
        nearby_municipalities=nearby_municipalities[:8],
        nearby_land_price_avg=nearby_land_price_avg,
        nearby_land_price_point_count=nearby_land_price_point_count,
    )


def list_stations_for_prefecture(
    db: Session, prefecture_code: str, *, limit: int = 30
) -> list[StationSummary]:
    pref = db.scalar(select(Prefecture).where(Prefecture.code == prefecture_code))
    rows = db.scalars(
        select(StationPassenger)
        .where(
            StationPassenger.prefecture_code == prefecture_code,
            StationPassenger.latest_passengers.isnot(None),
            StationPassenger.latest_passengers > 0,
        )
        .order_by(StationPassenger.latest_passengers.desc())
        .limit(limit)
    ).all()
    return [_station_to_summary(row, pref) for row in rows]


def list_stations_for_municipality(
    db: Session,
    municipality_code: str,
    prefecture_code: str,
    *,
    limit: int = 15,
) -> list[StationSummary]:
    pref = db.scalar(select(Prefecture).where(Prefecture.code == prefecture_code))
    pref_stations = db.scalars(
        select(StationPassenger).where(
            StationPassenger.prefecture_code == prefecture_code,
            StationPassenger.latest_passengers.isnot(None),
            StationPassenger.latest_passengers > 0,
        )
    ).all()
    if not pref_stations:
        return []

    matched: dict[int, StationPassenger] = {}

    nearest_names = db.scalars(
        select(LandPricePoint.nearest_station)
        .where(
            LandPricePoint.municipality_code == municipality_code,
            LandPricePoint.nearest_station.isnot(None),
        )
        .distinct()
    ).all()
    name_norms = {normalize_station_name(n) for n in nearest_names if n}

    for station in pref_stations:
        sname = normalize_station_name(station.station_name)
        for norm in name_norms:
            if sname == norm or norm in station.station_name or sname in norm:
                matched[station.id] = station
                break

    centroid = db.execute(
        select(
            func.avg(LandPricePoint.latitude),
            func.avg(LandPricePoint.longitude),
        ).where(
            LandPricePoint.municipality_code == municipality_code,
            LandPricePoint.latitude.isnot(None),
            LandPricePoint.longitude.isnot(None),
        )
    ).one()
    if centroid[0] is not None and centroid[1] is not None:
        lat0, lon0 = float(centroid[0]), float(centroid[1])
        for station in pref_stations:
            if station.latitude is None or station.longitude is None:
                continue
            if haversine_m(lat0, lon0, station.latitude, station.longitude) <= 2500:
                matched[station.id] = station

    items = sorted(
        matched.values(),
        key=lambda s: s.latest_passengers or 0,
        reverse=True,
    )[:limit]
    return [_station_to_summary(row, pref) for row in items]


def search_stations(db: Session, query: str, *, limit: int = 15) -> list[StationSummary]:
    q = query.strip()
    if not q:
        return []
    prefs = _prefecture_lookup(db)
    rows = db.scalars(
        select(StationPassenger)
        .where(StationPassenger.station_name.contains(q), StationPassenger.latest_passengers > 0)
        .order_by(StationPassenger.latest_passengers.desc().nullslast())
        .limit(limit)
    ).all()
    return [_station_to_summary(row, prefs.get(row.prefecture_code or "")) for row in rows]


def get_compare_view(
    db: Session,
    left_pref_slug: str,
    left_muni_slug: str,
    right_pref_slug: str,
    right_muni_slug: str,
) -> Optional[CompareView]:
    left_pref, left_muni = resolve_municipality(db, left_pref_slug, left_muni_slug)
    right_pref, right_muni = resolve_municipality(db, right_pref_slug, right_muni_slug)
    if not all([left_pref, left_muni, right_pref, right_muni]):
        return None
    return CompareView(
        left=_municipality_to_compare_side(db, left_pref, left_muni),
        right=_municipality_to_compare_side(db, right_pref, right_muni),
    )
