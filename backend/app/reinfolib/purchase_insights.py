from __future__ import annotations

import json
from collections import defaultdict
from typing import Optional

from sqlalchemy import func, select, text
from sqlalchemy.orm import Session

from app.api.schemas import (
    InsightBucket,
    LandTradeGap,
    MarketSummary,
    PriceClassComparison,
    PurchaseInsights,
)
from app.db import TradeTransaction
from app.reinfolib.purchase_insights_cache import get_cached
from app.utils.building_year import AGE_BUCKET_ORDER, building_age_bucket, parse_building_year

INSIGHT_YEARS = 5
MIN_BUCKET_COUNT = 3

PRICE_BRACKETS: list[tuple[int, int | None, str]] = [
    (0, 10_000_000, "〜1,000万"),
    (10_000_000, 20_000_000, "1,000〜2,000万"),
    (20_000_000, 30_000_000, "2,000〜3,000万"),
    (30_000_000, 50_000_000, "3,000〜5,000万"),
    (50_000_000, 80_000_000, "5,000〜8,000万"),
    (80_000_000, 100_000_000, "8,000万〜1億"),
    (100_000_000, None, "1億以上"),
]


def _period_label(min_year: int, max_year: int) -> str:
    if min_year == max_year:
        return f"{min_year}年"
    return f"{min_year}〜{max_year}年"


def _avg(values: list[float]) -> Optional[float]:
    if not values:
        return None
    return sum(values) / len(values)


def _percentile(sorted_values: list[float], pct: float) -> Optional[float]:
    if not sorted_values:
        return None
    if len(sorted_values) == 1:
        return sorted_values[0]
    rank = (len(sorted_values) - 1) * pct
    low = int(rank)
    high = min(low + 1, len(sorted_values) - 1)
    weight = rank - low
    return sorted_values[low] * (1 - weight) + sorted_values[high] * weight


def get_purchase_insights(
    db: Session,
    municipality_code: str,
    *,
    latest_year: Optional[int] = None,
    land_price_avg: Optional[float] = None,
    years: int = INSIGHT_YEARS,
) -> PurchaseInsights:
    cached = get_cached(municipality_code)
    if cached is not None:
        return cached

    max_year = latest_year or db.scalar(
        select(func.max(TradeTransaction.trade_year)).where(
            TradeTransaction.municipality_code == municipality_code
        )
    )
    if not max_year:
        return PurchaseInsights(period_label="データなし")

    min_year = max(2005, int(max_year) - years + 1)
    period = _period_label(min_year, int(max_year))
    reference_year = int(max_year)

    market_summary, price_bracket_stats = _market_and_bracket_stats(
        db, municipality_code, min_year
    )
    floor_plan_stats = _floor_plan_stats(db, municipality_code, min_year)
    age_bucket_stats = _age_bucket_stats(db, municipality_code, min_year, reference_year)
    structure_stats = _structure_stats(db, municipality_code, min_year)
    renovation_stats = _renovation_stats(db, municipality_code, min_year)
    region_stats = _region_stats(db, municipality_code, min_year)
    city_planning_stats = _city_planning_stats(db, municipality_code, min_year)
    district_hotspots = _district_stats(db, municipality_code, min_year)
    price_comparison = _price_class_comparison(db, municipality_code, min_year)
    land_trade_gap = _land_trade_gap(db, municipality_code, min_year, land_price_avg)

    return PurchaseInsights(
        period_label=period,
        sample_years=years,
        market_summary=market_summary,
        price_bracket_stats=price_bracket_stats,
        floor_plan_stats=floor_plan_stats,
        age_bucket_stats=age_bucket_stats,
        structure_stats=structure_stats,
        renovation_stats=renovation_stats,
        region_stats=region_stats,
        city_planning_stats=city_planning_stats,
        district_hotspots=district_hotspots,
        price_comparison=price_comparison,
        land_trade_gap=land_trade_gap,
    )


def _mansion_prices(db: Session, code: str, min_year: int) -> list[float]:
    rows = db.execute(
        select(TradeTransaction.trade_price).where(
            TradeTransaction.municipality_code == code,
            TradeTransaction.price_classification == "01",
            TradeTransaction.trade_year >= min_year,
            TradeTransaction.trade_price.isnot(None),
            TradeTransaction.trade_price > 0,
            _mansion_filter(),
        )
    ).all()
    return [float(row[0]) for row in rows]


def _market_and_bracket_stats(
    db: Session, code: str, min_year: int
) -> tuple[Optional[MarketSummary], list[InsightBucket]]:
    prices = sorted(_mansion_prices(db, code, min_year))
    if len(prices) < MIN_BUCKET_COUNT:
        return None, []

    market = MarketSummary(
        property_label="中古マンション",
        sample_count=len(prices),
        median_price=_percentile(prices, 0.5),
        p25_price=_percentile(prices, 0.25),
        p75_price=_percentile(prices, 0.75),
        min_price=prices[0],
        max_price=prices[-1],
    )

    brackets: list[InsightBucket] = []
    for low, high, label in PRICE_BRACKETS:
        if high is None:
            bucket = [p for p in prices if p >= low]
        else:
            bucket = [p for p in prices if low <= p < high]
        if len(bucket) < MIN_BUCKET_COUNT:
            continue
        brackets.append(
            InsightBucket(
                label=label,
                transaction_count=len(bucket),
                trade_price_avg=_avg(bucket),
            )
        )
    return market, brackets


def _mansion_filter():
    return TradeTransaction.property_type.like("%マンション%")


def _structure_stats(db: Session, code: str, min_year: int) -> list[InsightBucket]:
    rows = db.execute(
        text(
            """
            SELECT structure,
                   COUNT(*) AS cnt,
                   AVG(trade_price) AS avg_price,
                   AVG(unit_price) AS avg_unit
            FROM trade_transactions
            WHERE municipality_code = :code
              AND price_classification = '01'
              AND trade_year >= :min_year
              AND structure IS NOT NULL AND structure != ''
              AND property_type LIKE '%マンション%'
            GROUP BY structure
            HAVING COUNT(*) >= :min_cnt
            ORDER BY cnt DESC
            LIMIT 8
            """
        ),
        {"code": code, "min_year": min_year, "min_cnt": MIN_BUCKET_COUNT},
    ).all()
    return [
        InsightBucket(
            label=row[0],
            transaction_count=int(row[1]),
            trade_price_avg=float(row[2]) if row[2] is not None else None,
            unit_price_avg=float(row[3]) if row[3] is not None else None,
        )
        for row in rows
    ]


def _floor_plan_stats(db: Session, code: str, min_year: int) -> list[InsightBucket]:
    rows = db.execute(
        text(
            """
            SELECT floor_plan,
                   COUNT(*) AS cnt,
                   AVG(trade_price) AS avg_price,
                   AVG(unit_price) AS avg_unit
            FROM trade_transactions
            WHERE municipality_code = :code
              AND price_classification = '01'
              AND trade_year >= :min_year
              AND floor_plan IS NOT NULL AND floor_plan != ''
              AND property_type LIKE '%マンション%'
            GROUP BY floor_plan
            HAVING COUNT(*) >= :min_cnt
            ORDER BY cnt DESC
            LIMIT 10
            """
        ),
        {"code": code, "min_year": min_year, "min_cnt": MIN_BUCKET_COUNT},
    ).all()
    return [
        InsightBucket(
            label=row[0],
            transaction_count=int(row[1]),
            trade_price_avg=float(row[2]) if row[2] is not None else None,
            unit_price_avg=float(row[3]) if row[3] is not None else None,
        )
        for row in rows
    ]


def _age_bucket_stats(
    db: Session, code: str, min_year: int, reference_year: int
) -> list[InsightBucket]:
    rows = db.execute(
        select(TradeTransaction.building_year, TradeTransaction.trade_price, TradeTransaction.unit_price).where(
            TradeTransaction.municipality_code == code,
            TradeTransaction.price_classification == "01",
            TradeTransaction.trade_year >= min_year,
            TradeTransaction.building_year.isnot(None),
            TradeTransaction.building_year != "",
            TradeTransaction.property_type.like("%マンション%"),
        )
    ).all()

    buckets: dict[str, list[tuple[Optional[int], Optional[int]]]] = defaultdict(list)
    for building_year, trade_price, unit_price in rows:
        built = parse_building_year(building_year)
        if built is None:
            continue
        age = reference_year - built
        if age < 0:
            continue
        label = building_age_bucket(age)
        buckets[label].append((trade_price, unit_price))

    result: list[InsightBucket] = []
    for label in AGE_BUCKET_ORDER:
        items = buckets.get(label, [])
        if len(items) < MIN_BUCKET_COUNT:
            continue
        prices = [p for p, _ in items if p is not None]
        units = [u for _, u in items if u is not None]
        result.append(
            InsightBucket(
                label=label,
                transaction_count=len(items),
                trade_price_avg=_avg([float(p) for p in prices]),
                unit_price_avg=_avg([float(u) for u in units]),
            )
        )
    return result


def _renovation_stats(db: Session, code: str, min_year: int) -> list[InsightBucket]:
    rows = db.execute(
        text(
            """
            SELECT json_extract(raw_json, '$.Renovation') AS renov,
                   COUNT(*) AS cnt,
                   AVG(trade_price) AS avg_price,
                   AVG(unit_price) AS avg_unit
            FROM trade_transactions
            WHERE municipality_code = :code
              AND price_classification = '01'
              AND trade_year >= :min_year
              AND property_type LIKE '%マンション%'
              AND json_extract(raw_json, '$.Renovation') IS NOT NULL
              AND json_extract(raw_json, '$.Renovation') != ''
            GROUP BY renov
            HAVING COUNT(*) >= :min_cnt
            ORDER BY cnt DESC
            """
        ),
        {"code": code, "min_year": min_year, "min_cnt": MIN_BUCKET_COUNT},
    ).all()
    return [
        InsightBucket(
            label=row[0] or "不明",
            transaction_count=int(row[1]),
            trade_price_avg=float(row[2]) if row[2] is not None else None,
            unit_price_avg=float(row[3]) if row[3] is not None else None,
        )
        for row in rows
    ]


def _region_stats(db: Session, code: str, min_year: int) -> list[InsightBucket]:
    rows = db.execute(
        text(
            """
            SELECT region,
                   COUNT(*) AS cnt,
                   AVG(trade_price) AS avg_price,
                   AVG(unit_price) AS avg_unit
            FROM trade_transactions
            WHERE municipality_code = :code
              AND price_classification = '01'
              AND trade_year >= :min_year
              AND region IS NOT NULL AND region != ''
              AND (property_type LIKE '%土地%' OR property_type LIKE '%宅地%')
            GROUP BY region
            HAVING COUNT(*) >= :min_cnt
            ORDER BY cnt DESC
            LIMIT 8
            """
        ),
        {"code": code, "min_year": min_year, "min_cnt": MIN_BUCKET_COUNT},
    ).all()
    return [
        InsightBucket(
            label=row[0],
            transaction_count=int(row[1]),
            trade_price_avg=float(row[2]) if row[2] is not None else None,
            unit_price_avg=float(row[3]) if row[3] is not None else None,
        )
        for row in rows
    ]


def _city_planning_stats(db: Session, code: str, min_year: int) -> list[InsightBucket]:
    rows = db.execute(
        text(
            """
            SELECT city_planning,
                   COUNT(*) AS cnt,
                   AVG(trade_price) AS avg_price,
                   AVG(unit_price) AS avg_unit
            FROM trade_transactions
            WHERE municipality_code = :code
              AND price_classification = '01'
              AND trade_year >= :min_year
              AND city_planning IS NOT NULL AND city_planning != ''
            GROUP BY city_planning
            HAVING COUNT(*) >= :min_cnt
            ORDER BY cnt DESC
            LIMIT 8
            """
        ),
        {"code": code, "min_year": min_year, "min_cnt": MIN_BUCKET_COUNT},
    ).all()
    return [
        InsightBucket(
            label=row[0],
            transaction_count=int(row[1]),
            trade_price_avg=float(row[2]) if row[2] is not None else None,
            unit_price_avg=float(row[3]) if row[3] is not None else None,
        )
        for row in rows
    ]


def _district_stats(db: Session, code: str, min_year: int) -> list[InsightBucket]:
    from app.reinfolib.district_pages import DISTRICT_MIN_TRANSACTIONS, district_area_slug

    rows = db.execute(
        text(
            """
            SELECT district_code,
                   MAX(district_name) AS name,
                   COUNT(*) AS cnt,
                   AVG(trade_price) AS avg_price,
                   AVG(unit_price) AS avg_unit
            FROM trade_transactions
            WHERE municipality_code = :code
              AND price_classification = '01'
              AND trade_year >= :min_year
              AND district_code IS NOT NULL AND district_code != ''
            GROUP BY district_code
            HAVING COUNT(*) >= :min_cnt
            ORDER BY cnt DESC
            LIMIT 10
            """
        ),
        {"code": code, "min_year": min_year, "min_cnt": MIN_BUCKET_COUNT},
    ).all()
    used: set[str] = set()
    result: list[InsightBucket] = []
    for row in rows:
        district_code = row[0]
        name = row[1] or district_code
        slug = (
            district_area_slug(name, district_code, used=used)
            if int(row[2]) >= DISTRICT_MIN_TRANSACTIONS
            else None
        )
        result.append(
            InsightBucket(
                label=name,
                code=district_code,
                slug=slug,
                transaction_count=int(row[2]),
                trade_price_avg=float(row[3]) if row[3] is not None else None,
                unit_price_avg=float(row[4]) if row[4] is not None else None,
            )
        )
    return result


def _price_class_comparison(db: Session, code: str, min_year: int) -> Optional[PriceClassComparison]:
    by_class: dict[str, tuple[int, float]] = {}
    for price_class in ("01", "02"):
        row = db.execute(
            text(
                """
                SELECT COUNT(*) AS cnt,
                       AVG(trade_price) AS avg_price
                FROM trade_transactions
                WHERE municipality_code = :code
                  AND trade_year >= :min_year
                  AND price_classification = :price_class
                  AND trade_price IS NOT NULL AND trade_price > 0
                """
            ),
            {"code": code, "min_year": min_year, "price_class": price_class},
        ).one()
        cnt = int(row[0] or 0)
        if cnt > 0 and row[1] is not None:
            by_class[price_class] = (cnt, float(row[1]))

    trade = by_class.get("01")
    contract = by_class.get("02")
    if not trade or not contract or contract[0] < MIN_BUCKET_COUNT:
        return None
    trade_avg, contract_avg = trade[1], contract[1]
    discount = None
    if trade_avg > 0:
        discount = (trade_avg - contract_avg) / trade_avg * 100
    return PriceClassComparison(
        trade_count=trade[0],
        trade_price_avg=trade_avg,
        contract_count=contract[0],
        contract_price_avg=contract_avg,
        discount_pct=discount,
    )


def _land_trade_gap(
    db: Session,
    code: str,
    min_year: int,
    land_price_avg: Optional[float],
) -> Optional[LandTradeGap]:
    if not land_price_avg:
        return None
    row = db.execute(
        text(
            """
            SELECT AVG(unit_price) AS avg_unit, COUNT(*) AS cnt
            FROM trade_transactions
            WHERE municipality_code = :code
              AND price_classification = '01'
              AND trade_year >= :min_year
              AND unit_price IS NOT NULL AND unit_price > 0
              AND (property_type LIKE '%土地%' OR property_type LIKE '%宅地%')
            """
        ),
        {"code": code, "min_year": min_year},
    ).one()
    trade_unit = float(row[0]) if row[0] is not None else None
    cnt = int(row[1] or 0)
    if not trade_unit or cnt < MIN_BUCKET_COUNT:
        return None
    gap = (trade_unit - land_price_avg) / land_price_avg * 100 if land_price_avg else None
    return LandTradeGap(
        trade_unit_price_avg=trade_unit,
        land_price_avg=land_price_avg,
        gap_pct=gap,
        sample_count=cnt,
    )


def renovation_from_raw(raw_json: Optional[str]) -> Optional[str]:
    if not raw_json:
        return None
    try:
        data = json.loads(raw_json)
    except json.JSONDecodeError:
        return None
    value = data.get("Renovation")
    return str(value) if value else None
