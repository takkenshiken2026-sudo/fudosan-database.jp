from __future__ import annotations

from typing import Optional

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.api.schemas import ListingGapBucket, MunicipalityListingGap
from app.db import (
    ListingSnapshot,
    Municipality,
    MunicipalityListingStat,
    MunicipalityTradeStat,
    Prefecture,
)

# 募集・成約それぞれこの件数以上あるときだけギャップを表示する
MIN_SAMPLE = 3
# 成約側の集計に使う遡り年数
TRADE_WINDOW_YEARS = 3


def has_listing_data(db: Session, municipality_code: str) -> bool:
    return bool(
        db.scalar(
            select(func.count(MunicipalityListingStat.id)).where(
                MunicipalityListingStat.municipality_code == municipality_code
            )
        )
    )


def municipality_codes_with_listings(db: Session) -> list[str]:
    return db.scalars(
        select(MunicipalityListingStat.municipality_code).distinct()
    ).all()


def _latest_observed_period(
    db: Session, municipality_code: str
) -> Optional[tuple[int, int]]:
    year = db.scalar(
        select(func.max(MunicipalityListingStat.observed_year)).where(
            MunicipalityListingStat.municipality_code == municipality_code
        )
    )
    if not year:
        return None
    quarter = db.scalar(
        select(func.max(MunicipalityListingStat.observed_quarter)).where(
            MunicipalityListingStat.municipality_code == municipality_code,
            MunicipalityListingStat.observed_year == year,
        )
    )
    return int(year), int(quarter or 1)


def _trade_window(db: Session, municipality_code: str) -> Optional[tuple[int, int]]:
    max_year = db.scalar(
        select(func.max(MunicipalityTradeStat.trade_year)).where(
            MunicipalityTradeStat.municipality_code == municipality_code,
            MunicipalityTradeStat.price_classification == "01",
        )
    )
    if not max_year:
        return None
    max_year = int(max_year)
    return max_year - TRADE_WINDOW_YEARS + 1, max_year


def _trade_aggregate(
    db: Session,
    municipality_code: str,
    property_type: str,
    min_year: int,
    max_year: int,
) -> tuple[int, Optional[float], Optional[float]]:
    """指定物件種別・期間の成約集計（件数, 総額平均, ㎡単価平均）を重み付きで返す。"""
    rows = db.scalars(
        select(MunicipalityTradeStat).where(
            MunicipalityTradeStat.municipality_code == municipality_code,
            MunicipalityTradeStat.price_classification == "01",
            MunicipalityTradeStat.property_type == property_type,
            MunicipalityTradeStat.trade_year >= min_year,
            MunicipalityTradeStat.trade_year <= max_year,
        )
    ).all()
    count = 0
    price_sum = 0.0
    unit_weighted = 0.0
    unit_count = 0
    for row in rows:
        c = row.transaction_count or 0
        count += c
        if row.trade_price_sum:
            price_sum += float(row.trade_price_sum)
        elif row.trade_price_avg and c:
            price_sum += float(row.trade_price_avg) * c
        if row.unit_price_avg and c:
            unit_weighted += float(row.unit_price_avg) * c
            unit_count += c
    price_avg = (price_sum / count) if count else None
    unit_avg = (unit_weighted / unit_count) if unit_count else None
    return count, price_avg, unit_avg


def _build_bucket(
    property_type: str,
    listing: MunicipalityListingStat,
    trade_count: int,
    trade_price_avg: Optional[float],
    trade_unit_avg: Optional[float],
) -> Optional[ListingGapBucket]:
    if (listing.listing_count or 0) < MIN_SAMPLE or trade_count < MIN_SAMPLE:
        return None

    listing_unit = listing.unit_price_avg
    listing_price = listing.listing_price_avg

    gap_pct: Optional[float] = None
    implied_discount_pct: Optional[float] = None
    basis = ""
    # ㎡単価が両側にあれば単価ベース、なければ総額ベースで比較
    if listing_unit and trade_unit_avg:
        basis = "unit"
        gap_pct = (listing_unit - trade_unit_avg) / trade_unit_avg * 100
        implied_discount_pct = (listing_unit - trade_unit_avg) / listing_unit * 100
    elif listing_price and trade_price_avg:
        basis = "total"
        gap_pct = (listing_price - trade_price_avg) / trade_price_avg * 100
        implied_discount_pct = (listing_price - trade_price_avg) / listing_price * 100
    else:
        return None

    return ListingGapBucket(
        property_type=property_type or "全体",
        listing_count=listing.listing_count or 0,
        listing_price_avg=listing_price,
        listing_unit_price_avg=listing_unit,
        trade_count=trade_count,
        trade_price_avg=trade_price_avg,
        trade_unit_price_avg=trade_unit_avg,
        gap_pct=gap_pct,
        implied_discount_pct=implied_discount_pct,
        basis=basis,
    )


def _pick_headline(buckets: list[ListingGapBucket]) -> Optional[ListingGapBucket]:
    if not buckets:
        return None
    mansion = [b for b in buckets if "マンション" in b.property_type]
    if mansion:
        return max(mansion, key=lambda b: b.listing_count)
    return max(buckets, key=lambda b: b.listing_count)


def get_municipality_listing_gap(
    db: Session, prefecture: Prefecture, municipality: Municipality
) -> Optional[MunicipalityListingGap]:
    period = _latest_observed_period(db, municipality.code)
    window = _trade_window(db, municipality.code)
    if period is None or window is None:
        return None
    obs_year, obs_quarter = period
    min_year, max_year = window

    listing_rows = db.scalars(
        select(MunicipalityListingStat)
        .where(
            MunicipalityListingStat.municipality_code == municipality.code,
            MunicipalityListingStat.observed_year == obs_year,
            MunicipalityListingStat.observed_quarter == obs_quarter,
        )
        .order_by(MunicipalityListingStat.listing_count.desc())
    ).all()
    if not listing_rows:
        return None

    buckets: list[ListingGapBucket] = []
    total_listings = 0
    for listing in listing_rows:
        total_listings += listing.listing_count or 0
        if not listing.property_type:
            continue
        trade_count, trade_price_avg, trade_unit_avg = _trade_aggregate(
            db, municipality.code, listing.property_type, min_year, max_year
        )
        bucket = _build_bucket(
            listing.property_type,
            listing,
            trade_count,
            trade_price_avg,
            trade_unit_avg,
        )
        if bucket:
            buckets.append(bucket)

    if not buckets:
        return None

    observed_date = db.scalar(
        select(func.max(ListingSnapshot.observed_date)).where(
            ListingSnapshot.municipality_code == municipality.code
        )
    )
    updated_at = db.scalar(
        select(func.max(MunicipalityListingStat.updated_at)).where(
            MunicipalityListingStat.municipality_code == municipality.code
        )
    )

    return MunicipalityListingGap(
        code=municipality.code,
        name_ja=municipality.name_ja,
        slug=municipality.slug,
        prefecture_name=prefecture.name_ja,
        prefecture_slug=prefecture.slug,
        listing_period_label=f"{obs_year}年 第{obs_quarter}四半期",
        trade_period_label=f"{min_year}〜{max_year}年",
        observed_date=observed_date.isoformat() if observed_date else None,
        total_listings=total_listings,
        headline=_pick_headline(buckets),
        buckets=buckets,
        updated_at=updated_at,
    )
