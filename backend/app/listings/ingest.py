from __future__ import annotations

import csv
import json
from datetime import date, datetime
from pathlib import Path
from typing import Iterable, Optional

from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from app.db import ListingSnapshot, Municipality, MunicipalityListingStat

# CSV に最低限必要な列
REQUIRED_COLUMNS = {"source", "external_id", "municipality_code", "listing_price", "observed_date"}


def _parse_date(value: str) -> Optional[date]:
    value = (value or "").strip()
    if not value:
        return None
    for fmt in ("%Y-%m-%d", "%Y/%m/%d", "%Y%m%d"):
        try:
            return datetime.strptime(value, fmt).date()
        except ValueError:
            continue
    return None


def _quarter(d: date) -> int:
    return (d.month - 1) // 3 + 1


def _parse_int(value: str) -> Optional[int]:
    value = (value or "").strip().replace(",", "")
    if not value:
        return None
    try:
        return int(float(value))
    except ValueError:
        return None


def _parse_float(value: str) -> Optional[float]:
    value = (value or "").strip().replace(",", "")
    if not value:
        return None
    try:
        return float(value)
    except ValueError:
        return None


def _parse_bool(value: str, default: bool = True) -> bool:
    value = (value or "").strip().lower()
    if not value:
        return default
    return value in ("1", "true", "yes", "y", "active", "on")


def _row_to_snapshot(
    row: dict[str, str], valid_codes: set[str]
) -> tuple[Optional[ListingSnapshot], Optional[str]]:
    source = (row.get("source") or "").strip()
    external_id = (row.get("external_id") or "").strip()
    muni = (row.get("municipality_code") or "").strip()
    if not source or not external_id or not muni:
        return None, "source/external_id/municipality_code は必須です"
    if muni not in valid_codes:
        return None, f"未知の市区町村コード: {muni}"

    observed = _parse_date(row.get("observed_date", ""))
    if observed is None:
        return None, "observed_date が不正です"

    listing_price = _parse_int(row.get("listing_price", ""))
    if not listing_price or listing_price <= 0:
        return None, "listing_price が不正です"

    area = _parse_float(row.get("area", ""))
    unit_price = _parse_int(row.get("unit_price", ""))
    if unit_price is None and area and area > 0:
        unit_price = int(listing_price / area)

    snapshot = ListingSnapshot(
        source=source,
        external_id=external_id,
        municipality_code=muni,
        property_type=(row.get("property_type") or "").strip() or None,
        district_name=(row.get("district_name") or "").strip() or None,
        observed_date=observed,
        observed_year=observed.year,
        observed_quarter=_quarter(observed),
        listing_price=listing_price,
        area=area,
        unit_price=unit_price,
        building_year=(row.get("building_year") or "").strip() or None,
        floor_plan=(row.get("floor_plan") or "").strip() or None,
        first_listed_date=_parse_date(row.get("first_listed_date", "")),
        is_active=_parse_bool(row.get("is_active", ""), default=True),
        raw_json=json.dumps(row, ensure_ascii=False),
        synced_at=datetime.utcnow(),
    )
    return snapshot, None


def import_listings_csv(db: Session, csv_path: str | Path) -> dict[str, int]:
    """CSV から募集価格スナップショットを取り込む（(source, external_id, observed_date) で upsert）。"""
    path = Path(csv_path)
    if not path.exists():
        raise FileNotFoundError(f"CSV が見つかりません: {path}")

    valid_codes = set(db.scalars(select(Municipality.code)).all())

    inserted = 0
    updated = 0
    skipped = 0
    with path.open("r", encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f)
        missing = REQUIRED_COLUMNS - set(reader.fieldnames or [])
        if missing:
            raise ValueError(f"CSV に必須列がありません: {sorted(missing)}")
        for row in reader:
            snapshot, error = _row_to_snapshot(row, valid_codes)
            if snapshot is None:
                skipped += 1
                continue
            existing = db.scalar(
                select(ListingSnapshot).where(
                    ListingSnapshot.source == snapshot.source,
                    ListingSnapshot.external_id == snapshot.external_id,
                    ListingSnapshot.observed_date == snapshot.observed_date,
                )
            )
            if existing:
                for attr in (
                    "municipality_code",
                    "property_type",
                    "district_name",
                    "observed_year",
                    "observed_quarter",
                    "listing_price",
                    "area",
                    "unit_price",
                    "building_year",
                    "floor_plan",
                    "first_listed_date",
                    "is_active",
                    "raw_json",
                ):
                    setattr(existing, attr, getattr(snapshot, attr))
                existing.synced_at = snapshot.synced_at
                updated += 1
            else:
                db.add(snapshot)
                inserted += 1
    db.commit()
    return {"inserted": inserted, "updated": updated, "skipped": skipped}


def rebuild_listing_stats(
    db: Session, municipality_code: Optional[str] = None
) -> dict[str, int]:
    """listing_snapshots から市区町村×観測四半期×物件種別の集計を作り直す。"""
    filters = []
    if municipality_code:
        filters.append(ListingSnapshot.municipality_code == municipality_code)

    db.execute(
        delete(MunicipalityListingStat).where(
            MunicipalityListingStat.municipality_code == municipality_code
        )
        if municipality_code
        else delete(MunicipalityListingStat)
    )

    query = (
        select(
            ListingSnapshot.municipality_code,
            ListingSnapshot.observed_year,
            ListingSnapshot.observed_quarter,
            ListingSnapshot.property_type,
            func.count(ListingSnapshot.id),
            func.avg(ListingSnapshot.listing_price),
            func.min(ListingSnapshot.listing_price),
            func.max(ListingSnapshot.listing_price),
            func.avg(ListingSnapshot.unit_price),
            func.avg(ListingSnapshot.area),
        )
        .where(ListingSnapshot.is_active.is_(True), *filters)
        .group_by(
            ListingSnapshot.municipality_code,
            ListingSnapshot.observed_year,
            ListingSnapshot.observed_quarter,
            ListingSnapshot.property_type,
        )
    )

    stat_rows = 0
    for row in db.execute(query):
        db.add(
            MunicipalityListingStat(
                municipality_code=row[0],
                observed_year=row[1],
                observed_quarter=row[2],
                property_type=row[3] or "",
                listing_count=row[4],
                listing_price_avg=row[5],
                listing_price_min=row[6],
                listing_price_max=row[7],
                unit_price_avg=row[8],
                area_avg=row[9],
                updated_at=datetime.utcnow(),
            )
        )
        stat_rows += 1
    db.commit()
    return {"listing_stat_rows": stat_rows}


def iter_sources(db: Session) -> Iterable[str]:
    return db.scalars(select(ListingSnapshot.source).distinct()).all()
