from __future__ import annotations

from typing import Optional

from sqlalchemy import func, select, text
from sqlalchemy.orm import Session

from app.api.schemas import (
    DistrictDetail,
    DistrictSummary,
    StatBucket,
    TransactionItem,
    TransactionPage,
    YearlyStat,
)
from app.db import District, Municipality, Prefecture, TradeTransaction
from app.reinfolib.purchase_insights import renovation_from_raw
from app.utils.slugify import district_slug

DISTRICT_MIN_TRANSACTIONS = 10


def district_area_slug(name: str, code: str, *, used: Optional[set[str]] = None) -> str:
    base = district_slug(name, code)
    slug = base or code
    if used is None:
        return slug
    if slug not in used:
        used.add(slug)
        return slug
    unique = f"{slug}-{code}"
    used.add(unique)
    return unique


def _municipality_publishable_districts(
    db: Session,
    municipality_code: str,
    *,
    min_transactions: int = DISTRICT_MIN_TRANSACTIONS,
    exclude_code: Optional[str] = None,
    limit: Optional[int] = None,
) -> list[tuple[str, str, int]]:
    """district_code, name, transaction_count（市区町村内・取引件数下限以上）"""
    exclude_sql = "AND district_code != :exclude_code" if exclude_code else ""
    limit_sql = f"LIMIT {int(limit)}" if limit else ""
    rows = db.execute(
        text(
            f"""
            SELECT t.district_code,
                   COALESCE(MAX(d.name), MAX(t.district_name), t.district_code) AS name,
                   COUNT(*) AS cnt
            FROM trade_transactions t
            LEFT JOIN districts d ON d.code = t.district_code
            WHERE t.municipality_code = :muni_code
              AND t.price_classification = '01'
              AND t.district_code IS NOT NULL AND t.district_code != ''
              {exclude_sql}
            GROUP BY t.district_code
            HAVING cnt >= :min_tx
            ORDER BY cnt DESC
            {limit_sql}
            """
        ),
        {
            "muni_code": municipality_code,
            "min_tx": min_transactions,
            "exclude_code": exclude_code or "",
        },
    ).all()
    return [(row[0], row[1], int(row[2])) for row in rows]


def _find_publishable_district_by_slug(
    db: Session,
    municipality_code: str,
    area_slug: str,
) -> Optional[District]:
    rows = db.execute(
        select(District.code, District.name)
        .where(District.municipality_code == municipality_code)
        .order_by(District.code)
    ).all()
    used: set[str] = set()
    for code, name in rows:
        slug = district_area_slug(name, code, used=used)
        if slug != area_slug and code != area_slug:
            continue
        if _district_transaction_count(db, municipality_code, code) >= DISTRICT_MIN_TRANSACTIONS:
            return db.get(District, code)
    return None


def _district_transaction_count(
    db: Session,
    municipality_code: str,
    district_code: str,
) -> int:
    return int(
        db.scalar(
            select(func.count(TradeTransaction.id)).where(
                TradeTransaction.municipality_code == municipality_code,
                TradeTransaction.district_code == district_code,
                TradeTransaction.price_classification == "01",
            )
        )
        or 0
    )


def _district_tx_filters(
    municipality_code: str,
    district_code: str,
    *,
    price_classification: str = "01",
) -> tuple:
    return (
        TradeTransaction.municipality_code == municipality_code,
        TradeTransaction.district_code == district_code,
        TradeTransaction.price_classification == price_classification,
    )


def _tx_count_subquery(min_transactions: int = DISTRICT_MIN_TRANSACTIONS):
    return (
        select(
            TradeTransaction.district_code.label("district_code"),
            func.count(TradeTransaction.id).label("cnt"),
        )
        .where(
            TradeTransaction.district_code.isnot(None),
            TradeTransaction.district_code != "",
        )
        .group_by(TradeTransaction.district_code)
        .having(func.count(TradeTransaction.id) >= min_transactions)
        .subquery()
    )


def list_publishable_district_rows(db: Session) -> list[tuple[str, str, str, str, str]]:
    """pref_slug, muni_slug, area_slug, district_code, district_name"""
    tx = _tx_count_subquery()
    rows = db.execute(
        select(
            Prefecture.slug,
            Municipality.slug,
            District.code,
            District.name,
        )
        .join(District, District.municipality_code == Municipality.code)
        .join(Prefecture, Prefecture.code == Municipality.prefecture_code)
        .join(tx, tx.c.district_code == District.code)
        .order_by(Municipality.code, District.code)
    ).all()

    result: list[tuple[str, str, str, str, str]] = []
    used_by_muni: dict[str, set[str]] = {}
    for pref_slug, muni_slug, code, name in rows:
        used = used_by_muni.setdefault(muni_slug, set())
        area_slug = district_area_slug(name, code, used=used)
        result.append((pref_slug, muni_slug, area_slug, code, name))
    return result


def list_district_paths(db: Session) -> list[str]:
    return [
        f"/price/{pref_slug}/{muni_slug}/area/{area_slug}"
        for pref_slug, muni_slug, area_slug, *_ in list_publishable_district_rows(db)
    ]


def resolve_district(
    db: Session,
    prefecture_slug: str,
    municipality_slug: str,
    area_slug: str,
) -> tuple[Optional[Prefecture], Optional[Municipality], Optional[District]]:
    from app.api.services import resolve_municipality

    prefecture, municipality = resolve_municipality(db, prefecture_slug, municipality_slug)
    if not prefecture or not municipality:
        return None, None, None

    district = db.scalar(
        select(District).where(
            District.municipality_code == municipality.code,
            District.code == area_slug,
        )
    )
    if district and _district_transaction_count(db, municipality.code, district.code) >= DISTRICT_MIN_TRANSACTIONS:
        return prefecture, municipality, district

    district = _find_publishable_district_by_slug(db, municipality.code, area_slug)
    if district:
        return prefecture, municipality, district
    return prefecture, municipality, None


def _district_tx_to_item(tx: TradeTransaction) -> TransactionItem:
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


def get_district_transactions_page(
    db: Session,
    municipality_code: str,
    district_code: str,
    *,
    page: int = 1,
    page_size: int = 50,
    price_classification: str = "01",
) -> TransactionPage:
    page = max(1, page)
    page_size = min(max(1, page_size), 100)
    filters = _district_tx_filters(
        municipality_code, district_code, price_classification=price_classification
    )
    total = db.scalar(select(func.count(TradeTransaction.id)).where(*filters)) or 0
    offset = (page - 1) * page_size
    rows = db.scalars(
        select(TradeTransaction)
        .where(*filters)
        .order_by(
            TradeTransaction.trade_year.desc(),
            TradeTransaction.trade_quarter.desc(),
            TradeTransaction.id.desc(),
        )
        .offset(offset)
        .limit(page_size)
    ).all()
    return TransactionPage(
        items=[_district_tx_to_item(tx) for tx in rows],
        total=total,
        page=page,
        page_size=page_size,
        has_more=offset + len(rows) < total,
    )


def get_district_detail(
    db: Session,
    prefecture: Prefecture,
    municipality: Municipality,
    district: District,
) -> DistrictDetail:
    muni_code = municipality.code
    dist_code = district.code
    tx_filters = _district_tx_filters(muni_code, dist_code)

    total = db.scalar(select(func.count(TradeTransaction.id)).where(*tx_filters)) or 0

    price_row = db.execute(
        select(
            func.avg(TradeTransaction.trade_price),
            func.max(TradeTransaction.trade_year),
            func.max(TradeTransaction.trade_quarter),
        ).where(
            *tx_filters,
            TradeTransaction.trade_price.isnot(None),
        )
    ).one()
    recent_avg_price = float(price_row[0]) if price_row[0] is not None else None
    latest_year = int(price_row[1]) if price_row[1] is not None else None
    latest_quarter = int(price_row[2]) if price_row[2] is not None else None

    yearly_rows = db.execute(
        select(
            TradeTransaction.trade_year,
            func.count(TradeTransaction.id),
            func.sum(TradeTransaction.trade_price),
            func.avg(TradeTransaction.unit_price),
        )
        .where(*tx_filters)
        .group_by(TradeTransaction.trade_year)
        .order_by(TradeTransaction.trade_year)
    ).all()
    yearly_stats: list[YearlyStat] = []
    for row in yearly_rows:
        cnt = int(row[1] or 0)
        yearly_stats.append(
            YearlyStat(
                trade_year=int(row[0]),
                transaction_count=cnt,
                trade_price_avg=(int(row[2]) / cnt) if cnt and row[2] else None,
            )
        )
    for i in range(1, len(yearly_stats)):
        prev, cur = yearly_stats[i - 1], yearly_stats[i]
        if prev.transaction_count:
            cur.yoy_transaction_pct = (
                (cur.transaction_count - prev.transaction_count)
                / prev.transaction_count
                * 100
            )

    property_rows = db.execute(
        text(
            """
            SELECT property_type,
                   COUNT(*) AS cnt,
                   AVG(trade_price) AS avg_price,
                   AVG(unit_price) AS avg_unit
            FROM trade_transactions
            WHERE municipality_code = :muni_code
              AND district_code = :code
              AND price_classification = '01'
              AND property_type IS NOT NULL AND property_type != ''
            GROUP BY property_type
            ORDER BY cnt DESC
            LIMIT 8
            """
        ),
        {"muni_code": muni_code, "code": dist_code},
    ).all()
    property_stats = [
        StatBucket(
            trade_year=latest_year or 0,
            trade_quarter=latest_quarter or 0,
            property_type=row[0],
            transaction_count=int(row[1]),
            trade_price_avg=float(row[2]) if row[2] is not None else None,
            unit_price_avg=float(row[3]) if row[3] is not None else None,
        )
        for row in property_rows
    ]

    sibling_candidates = _municipality_publishable_districts(
        db,
        municipality.code,
        exclude_code=district.code,
        limit=8,
    )
    used: set[str] = set()
    sibling_districts: list[DistrictSummary] = []
    for code, name, cnt in sibling_candidates:
        sibling_districts.append(
            DistrictSummary(
                code=code,
                name=name,
                slug=district_area_slug(name, code, used=used),
                transaction_count=cnt,
            )
        )

    recent_rows = db.scalars(
        select(TradeTransaction)
        .where(*tx_filters)
        .order_by(
            TradeTransaction.trade_year.desc(),
            TradeTransaction.trade_quarter.desc(),
            TradeTransaction.id.desc(),
        )
        .limit(50)
    ).all()

    used_current: set[str] = set()
    area_slug = district_area_slug(district.name, district.code, used=used_current)

    yoy_price_change_pct = None
    if len(yearly_stats) >= 2:
        latest, prev = yearly_stats[-1], yearly_stats[-2]
        if latest.trade_price_avg and prev.trade_price_avg:
            yoy_price_change_pct = (
                (latest.trade_price_avg - prev.trade_price_avg) / prev.trade_price_avg * 100
            )

    muni_price_row = db.execute(
        select(
            func.avg(TradeTransaction.trade_price),
            func.avg(TradeTransaction.unit_price),
        ).where(
            TradeTransaction.municipality_code == muni_code,
            TradeTransaction.price_classification == "01",
            TradeTransaction.trade_price.isnot(None),
        )
    ).one()
    municipality_avg_price = (
        float(muni_price_row[0]) if muni_price_row[0] is not None else None
    )
    municipality_avg_unit_price = (
        float(muni_price_row[1]) if muni_price_row[1] is not None else None
    )
    price_gap_pct = None
    if recent_avg_price and municipality_avg_price:
        price_gap_pct = (
            (recent_avg_price - municipality_avg_price) / municipality_avg_price * 100
        )
    unit_price_gap_pct = None
    district_unit_avg = db.scalar(
        select(func.avg(TradeTransaction.unit_price)).where(
            *tx_filters,
            TradeTransaction.unit_price.isnot(None),
        )
    )
    if district_unit_avg is not None and municipality_avg_unit_price:
        unit_price_gap_pct = (
            (float(district_unit_avg) - municipality_avg_unit_price)
            / municipality_avg_unit_price
            * 100
        )

    muni_yearly_rows = db.execute(
        select(
            TradeTransaction.trade_year,
            func.count(TradeTransaction.id),
            func.sum(TradeTransaction.trade_price),
        )
        .where(
            TradeTransaction.municipality_code == muni_code,
            TradeTransaction.price_classification == "01",
        )
        .group_by(TradeTransaction.trade_year)
        .order_by(TradeTransaction.trade_year)
    ).all()
    municipality_yearly_stats: list[YearlyStat] = []
    for row in muni_yearly_rows:
        cnt = int(row[1] or 0)
        municipality_yearly_stats.append(
            YearlyStat(
                trade_year=int(row[0]),
                transaction_count=cnt,
                trade_price_avg=(int(row[2]) / cnt) if cnt and row[2] else None,
            )
        )

    return DistrictDetail(
        code=district.code,
        name=district.name,
        slug=area_slug,
        municipality_code=municipality.code,
        municipality_name=municipality.name_ja,
        municipality_slug=municipality.slug,
        prefecture_code=prefecture.code,
        prefecture_name=prefecture.name_ja,
        prefecture_slug=prefecture.slug,
        total_transactions=int(total),
        recent_avg_price=recent_avg_price,
        latest_year=latest_year,
        latest_quarter=latest_quarter,
        yearly_stats=yearly_stats,
        property_stats=property_stats,
        recent_transactions=[_district_tx_to_item(tx) for tx in recent_rows],
        sibling_districts=sibling_districts,
        yoy_price_change_pct=yoy_price_change_pct,
        municipality_avg_price=municipality_avg_price,
        price_gap_pct=price_gap_pct,
        municipality_avg_unit_price=municipality_avg_unit_price,
        unit_price_gap_pct=unit_price_gap_pct,
        municipality_yearly_stats=municipality_yearly_stats,
    )
