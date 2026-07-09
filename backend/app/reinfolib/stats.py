from __future__ import annotations

from datetime import datetime

from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from app.db import Municipality, MunicipalityPageMeta, MunicipalityTradeStat, TradeTransaction


def rebuild_trade_stats(db: Session, municipality_code: str | None = None) -> dict[str, int]:
    filters = []
    if municipality_code:
        filters.append(TradeTransaction.municipality_code == municipality_code)

    db.execute(delete(MunicipalityTradeStat).where(*filters) if filters else delete(MunicipalityTradeStat))

    query = (
        select(
            TradeTransaction.municipality_code,
            TradeTransaction.trade_year,
            TradeTransaction.trade_quarter,
            TradeTransaction.price_classification,
            TradeTransaction.property_type,
            func.count(TradeTransaction.id),
            func.sum(TradeTransaction.trade_price),
            func.avg(TradeTransaction.trade_price),
            func.min(TradeTransaction.trade_price),
            func.max(TradeTransaction.trade_price),
            func.avg(TradeTransaction.unit_price),
            func.avg(TradeTransaction.area),
        )
        .where(*filters)
        .group_by(
            TradeTransaction.municipality_code,
            TradeTransaction.trade_year,
            TradeTransaction.trade_quarter,
            TradeTransaction.price_classification,
            TradeTransaction.property_type,
        )
    )

    stat_rows = 0
    for row in db.execute(query):
        db.add(
            MunicipalityTradeStat(
                municipality_code=row[0],
                trade_year=row[1],
                trade_quarter=row[2],
                price_classification=row[3] or "",
                property_type=row[4] or "",
                transaction_count=row[5],
                trade_price_sum=row[6],
                trade_price_avg=row[7],
                trade_price_min=row[8],
                trade_price_max=row[9],
                unit_price_avg=row[10],
                area_avg=row[11],
                updated_at=datetime.utcnow(),
            )
        )
        stat_rows += 1
    db.commit()
    return {"stat_rows": stat_rows}


def rebuild_page_meta(db: Session, municipality_code: str | None = None) -> dict[str, int]:
    municipality_codes = []
    if municipality_code:
        municipality_codes = [municipality_code]
    else:
        municipality_codes = db.scalars(select(Municipality.code)).all()

    updated = 0
    for code in municipality_codes:
        latest = db.execute(
            select(
                TradeTransaction.trade_year,
                TradeTransaction.trade_quarter,
            )
            .where(TradeTransaction.municipality_code == code)
            .order_by(
                TradeTransaction.trade_year.desc(),
                TradeTransaction.trade_quarter.desc(),
            )
            .limit(1)
        ).first()

        total = db.scalar(
            select(func.count(TradeTransaction.id)).where(
                TradeTransaction.municipality_code == code
            )
        ) or 0

        recent_avg = db.scalar(
            select(func.avg(TradeTransaction.trade_price)).where(
                TradeTransaction.municipality_code == code,
                TradeTransaction.trade_price.is_not(None),
            )
        )

        meta = db.get(MunicipalityPageMeta, code) or MunicipalityPageMeta(
            municipality_code=code
        )
        if latest:
            meta.latest_year = latest[0]
            meta.latest_quarter = latest[1]
        meta.total_transactions = total
        meta.recent_avg_price = recent_avg
        meta.stats_updated_at = datetime.utcnow()
        db.add(meta)
        updated += 1

    db.commit()
    return {"page_meta_rows": updated}
