from __future__ import annotations

from time import time as time_time
from typing import Optional

from sqlalchemy import func, select
from sqlalchemy.orm import Session, joinedload

from app.api.schemas import (
    AppraisalArea,
    AppraisalDataset,
    AppraisalPrefecture,
    CompareSide,
    CompareView,
    DistrictSearchResult,
    HomeChartData,
    HomeHighlights,
    LandPricePointItem,
    LandPriceSummary,
    LandPriceYearlyStat,
    MunicipalityDetail,
    MunicipalitySummary,
    PrefectureChartData,
    PrefectureSummary,
    RankingItem,
    ReportContext,
    SearchResult,
    StationDetail,
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
from app.reinfolib.purchase_insights import get_purchase_insights, renovation_from_raw
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
            avg_price=row[5],
        )
        for row in rows
    ]


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
    prefectures = list_prefectures(db)
    total_tx = sum(p.total_transactions for p in prefectures)
    muni_count = sum(p.municipality_count for p in prefectures)
    return HomeHighlights(
        top_by_volume=get_rankings(db, sort="volume", limit=10),
        top_by_price=get_rankings(db, sort="price", limit=10),
        total_transactions=total_tx,
        municipality_count=muni_count,
    )


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

    prefectures = list_prefectures(db)
    with_tx = [p for p in prefectures if p.total_transactions > 0]
    top_vol = sorted(with_tx, key=lambda p: p.total_transactions, reverse=True)[:10]
    with_price = [p for p in prefectures if p.avg_price]
    top_price = sorted(with_price, key=lambda p: p.avg_price or 0, reverse=True)[:10]

    result = HomeChartData(
        yearly_stats=yearly,
        land_price_yearly=get_national_land_price_yearly_stats(db),
        top_prefectures_volume=top_vol,
        top_prefectures_price=top_price,
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
        .order_by(func.count(TradeTransaction.id).desc())
        .limit(limit)
    ).all()
    return [
        DistrictSearchResult(
            code=row[0],
            name=row[1],
            municipality_name=row[2],
            municipality_slug=row[3],
            prefecture_slug=row[4],
            transaction_count=int(row[5] or 0),
        )
        for row in rows
    ]


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
    )


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
    property_stats: list[MunicipalityTradeStat] = []
    if latest_year and latest_quarter:
        property_stats = db.scalars(
            select(MunicipalityTradeStat)
            .where(
                MunicipalityTradeStat.municipality_code == municipality.code,
                MunicipalityTradeStat.trade_year == latest_year,
                MunicipalityTradeStat.trade_quarter == latest_quarter,
                MunicipalityTradeStat.price_classification == "01",
                MunicipalityTradeStat.property_type != "",
            )
            .order_by(MunicipalityTradeStat.transaction_count.desc())
        ).all()

    transactions = get_transactions_page(db, municipality.code, page=1, page_size=50).items

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
        yoy_price_change_pct=yoy,
        purchase_insights=purchase_insights,
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
        property_stats=detail.property_stats,
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
    return StationDetail(
        **base.model_dump(),
        railway_type=row.railway_type,
        latitude=row.latitude,
        longitude=row.longitude,
        yearly_passengers=_station_yearly_passengers(row),
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


_APPRAISAL_CACHE: dict[str, tuple[float, AppraisalDataset]] = {}
_APPRAISAL_TTL = 3600.0


def get_appraisal_dataset(db: Session, *, years: int = 3) -> AppraisalDataset:
    """市区町村別の㎡単価（中古マンション・土地）を価格査定用にまとめて返す。

    直近 ``years`` 年の取引価格情報（price_classification="01"）を取引件数で
    加重平均した㎡単価を、種別ごと（中古マンション / 宅地(土地)）に集計する。
    """
    cached = _APPRAISAL_CACHE.get("data")
    if cached and (time_time() - cached[0]) < _APPRAISAL_TTL:
        return cached[1]

    max_year = db.scalar(
        select(func.max(MunicipalityTradeStat.trade_year)).where(
            MunicipalityTradeStat.price_classification == "01"
        )
    )
    if not max_year:
        dataset = AppraisalDataset()
        _APPRAISAL_CACHE["data"] = (time_time(), dataset)
        return dataset

    min_year = max_year - (years - 1)
    rows = db.execute(
        select(
            MunicipalityTradeStat.municipality_code,
            MunicipalityTradeStat.property_type,
            func.sum(
                MunicipalityTradeStat.unit_price_avg
                * MunicipalityTradeStat.transaction_count
            ),
            func.sum(MunicipalityTradeStat.transaction_count),
        )
        .where(
            MunicipalityTradeStat.price_classification == "01",
            MunicipalityTradeStat.trade_year >= min_year,
            MunicipalityTradeStat.unit_price_avg.isnot(None),
            MunicipalityTradeStat.transaction_count > 0,
        )
        .group_by(
            MunicipalityTradeStat.municipality_code,
            MunicipalityTradeStat.property_type,
        )
    ).all()

    # code -> {"mansion": [weighted_sum, count], "land": [...]}
    acc: dict[str, dict[str, list[float]]] = {}
    for code, ptype, weighted, count in rows:
        if not weighted or not count:
            continue
        name = ptype or ""
        if "マンション" in name:
            key = "mansion"
        elif name == "宅地(土地)":
            key = "land"
        else:
            continue
        entry = acc.setdefault(code, {}).setdefault(key, [0.0, 0])
        entry[0] += float(weighted)
        entry[1] += int(count)

    if not acc:
        dataset = AppraisalDataset(base_year=max_year)
        _APPRAISAL_CACHE["data"] = (time_time(), dataset)
        return dataset

    muni_rows = db.execute(
        select(
            Municipality.code,
            Municipality.name_ja,
            Municipality.slug,
            Prefecture.name_ja,
            Prefecture.slug,
        )
        .join(Prefecture, Prefecture.code == Municipality.prefecture_code)
        .where(Municipality.code.in_(list(acc.keys())))
        .order_by(Prefecture.code, Municipality.code)
    ).all()

    pref_map: dict[str, AppraisalPrefecture] = {}
    for code, muni_name, muni_slug, pref_name, pref_slug in muni_rows:
        bucket = acc.get(code)
        if not bucket:
            continue
        mansion = bucket.get("mansion")
        land = bucket.get("land")
        mansion_unit = (
            round(mansion[0] / mansion[1]) if mansion and mansion[1] else None
        )
        land_unit = round(land[0] / land[1]) if land and land[1] else None
        if not mansion_unit and not land_unit:
            continue
        pref = pref_map.get(pref_slug)
        if pref is None:
            pref = AppraisalPrefecture(slug=pref_slug, name=pref_name, areas=[])
            pref_map[pref_slug] = pref
        pref.areas.append(
            AppraisalArea(
                slug=muni_slug,
                name=muni_name,
                mansion_unit_price=mansion_unit,
                mansion_samples=int(mansion[1]) if mansion else 0,
                land_unit_price=land_unit,
                land_samples=int(land[1]) if land else 0,
            )
        )

    prefectures = sorted(pref_map.values(), key=lambda p: p.slug)
    area_count = sum(len(p.areas) for p in prefectures)
    dataset = AppraisalDataset(
        prefectures=prefectures, base_year=max_year, area_count=area_count
    )
    _APPRAISAL_CACHE["data"] = (time_time(), dataset)
    return dataset
