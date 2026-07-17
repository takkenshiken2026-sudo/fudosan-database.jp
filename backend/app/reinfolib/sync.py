from __future__ import annotations

import json
from datetime import datetime
from typing import Optional

from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from app.db import (
    District,
    Municipality,
    MunicipalityPageMeta,
    MunicipalityTradeStat,
    Prefecture,
    SyncCheckpoint,
    TradeTransaction,
)
from app.reinfolib.client import (
    ReinfolibClient,
    classify_price_category,
    compute_record_hash,
    parse_float,
    parse_int,
)
from app.reinfolib.prefectures import PREFECTURES


def seed_prefectures(db: Session) -> int:
    count = 0
    for item in PREFECTURES:
        prefecture = db.get(Prefecture, item["code"]) or Prefecture(code=item["code"])
        prefecture.name_ja = item["name_ja"]
        prefecture.name_en = item["name_en"]
        prefecture.slug = item["slug"]
        db.add(prefecture)
        count += 1
    db.commit()
    return count


def sync_municipalities(db: Session, client: ReinfolibClient) -> dict[str, int]:
    stats = {"prefectures": 0, "municipalities": 0, "errors": 0}
    for item in PREFECTURES:
        code = item["code"]
        try:
            rows = client.fetch_municipalities(code)
        except Exception as exc:
            stats["errors"] += 1
            checkpoint = SyncCheckpoint(
                sync_type="municipalities",
                prefecture_code=code,
                status="failed",
                error_message=str(exc),
                finished_at=datetime.utcnow(),
            )
            db.add(checkpoint)
            db.commit()
            continue

        stats["prefectures"] += 1
        for row in rows:
            municipality_code = str(row.get("id") or row.get("code") or "").strip()
            name_ja = str(row.get("name") or row.get("name_ja") or "").strip()
            if not municipality_code or not name_ja:
                continue
            municipality = db.get(Municipality, municipality_code) or Municipality(
                code=municipality_code
            )
            municipality.prefecture_code = code
            municipality.name_ja = name_ja
            municipality.name_en = row.get("name_en")
            municipality.slug = municipality.slug or municipality_code
            db.add(municipality)
            stats["municipalities"] += 1

        checkpoint = SyncCheckpoint(
            sync_type="municipalities",
            prefecture_code=code,
            status="done",
            record_count=len(rows),
            finished_at=datetime.utcnow(),
        )
        db.add(checkpoint)
        db.commit()
    return stats


def _upsert_district(
    db: Session,
    municipality_code: str,
    district_code: str,
    district_name: str,
    *,
    pending: set[str],
) -> None:
    if not district_code or district_code in pending:
        return
    pending.add(district_code)
    district = db.get(District, district_code)
    if district is None:
        district = District(code=district_code)
        district.municipality_code = municipality_code
        district.name = district_name or ""
        db.add(district)
        return
    district.municipality_code = municipality_code
    if district_name:
        district.name = district_name


def _record_to_transaction(
    record: dict,
    *,
    trade_year: int,
    trade_quarter: int,
) -> TradeTransaction:
    price_category = str(record.get("PriceCategory") or "")
    return TradeTransaction(
        record_hash=compute_record_hash(
            record, trade_year=trade_year, trade_quarter=trade_quarter
        ),
        price_category=price_category,
        price_classification=classify_price_category(price_category),
        trade_year=trade_year,
        trade_quarter=trade_quarter,
        property_type=record.get("Type") or None,
        region=record.get("Region") or None,
        municipality_code=str(record.get("MunicipalityCode") or "").zfill(5),
        prefecture_name=record.get("Prefecture") or None,
        municipality_name=record.get("Municipality") or None,
        district_code=record.get("DistrictCode") or None,
        district_name=record.get("DistrictName") or None,
        trade_price=parse_int(record.get("TradePrice")),
        price_per_unit=parse_int(record.get("PricePerUnit")),
        unit_price=parse_int(record.get("UnitPrice")),
        area=parse_float(record.get("Area")),
        total_floor_area=parse_float(record.get("TotalFloorArea")),
        floor_plan=record.get("FloorPlan") or None,
        building_year=record.get("BuildingYear") or None,
        structure=record.get("Structure") or None,
        city_planning=record.get("CityPlanning") or None,
        coverage_ratio=parse_float(record.get("CoverageRatio")),
        floor_area_ratio=parse_float(record.get("FloorAreaRatio")),
        period_label=record.get("Period") or None,
        remarks=record.get("Remarks") or None,
        raw_json=json.dumps(record, ensure_ascii=False),
        synced_at=datetime.utcnow(),
    )


def sync_transactions_for_city_period(
    db: Session,
    client: ReinfolibClient,
    *,
    city_code: str,
    year: int,
    quarter: int,
    prefecture_code: Optional[str] = None,
) -> dict[str, int]:
    checkpoint = db.scalar(
        select(SyncCheckpoint).where(
            SyncCheckpoint.sync_type == "transactions",
            SyncCheckpoint.municipality_code == city_code,
            SyncCheckpoint.trade_year == year,
            SyncCheckpoint.trade_quarter == quarter,
        )
    )
    if checkpoint and checkpoint.status in ("done", "empty"):
        return {"skipped": 1, "inserted": 0, "duplicates": 0, "fetched": 0}

    started = datetime.utcnow()
    status = "done"
    error_message: Optional[str] = None
    inserted = 0
    duplicates = 0

    try:
        records = client.fetch_transactions(
            city_code=city_code, year=year, quarter=quarter
        )
    except Exception as exc:
        status = "failed"
        error_message = str(exc)
        records = []

    if status == "done" and not records:
        status = "empty"

    batch_hashes = [
        compute_record_hash(record, trade_year=year, trade_quarter=quarter)
        for record in records
    ]
    existing_hashes = set()
    if batch_hashes:
        existing_hashes = set(
            db.scalars(
                select(TradeTransaction.record_hash).where(
                    TradeTransaction.record_hash.in_(batch_hashes)
                )
            ).all()
        )

    pending_districts: set[str] = set()
    for record in records:
        municipality_code = str(record.get("MunicipalityCode") or city_code).zfill(5)
        _upsert_district(
            db,
            municipality_code,
            str(record.get("DistrictCode") or ""),
            str(record.get("DistrictName") or ""),
            pending=pending_districts,
        )
        tx = _record_to_transaction(record, trade_year=year, trade_quarter=quarter)
        if tx.record_hash in existing_hashes:
            duplicates += 1
            continue
        db.add(tx)
        existing_hashes.add(tx.record_hash)
        inserted += 1

    if checkpoint:
        checkpoint.prefecture_code = prefecture_code
        checkpoint.status = status
        checkpoint.record_count = len(records)
        checkpoint.error_message = error_message
        checkpoint.started_at = started
        checkpoint.finished_at = datetime.utcnow()
    else:
        db.add(
            SyncCheckpoint(
                sync_type="transactions",
                prefecture_code=prefecture_code,
                municipality_code=city_code,
                trade_year=year,
                trade_quarter=quarter,
                status=status,
                record_count=len(records),
                error_message=error_message,
                started_at=started,
                finished_at=datetime.utcnow(),
            )
        )
    db.commit()
    return {"skipped": 0, "inserted": inserted, "duplicates": duplicates, "fetched": len(records)}


def sync_transactions(
    db: Session,
    client: ReinfolibClient,
    *,
    municipality_codes: list[str],
    from_year: int,
    to_year: int,
    prefecture_code: Optional[str] = None,
    skip_done: bool = True,
) -> dict[str, int]:
    totals = {
        "jobs": 0,
        "skipped": 0,
        "inserted": 0,
        "duplicates": 0,
        "fetched": 0,
        "errors": 0,
    }

    done_keys: set[tuple[str, int, int]] = set()
    if skip_done:
        rows = db.execute(
            select(
                SyncCheckpoint.municipality_code,
                SyncCheckpoint.trade_year,
                SyncCheckpoint.trade_quarter,
            ).where(
                SyncCheckpoint.sync_type == "transactions",
                SyncCheckpoint.status.in_(("done", "empty")),
            )
        ).all()
        done_keys = {(row[0], row[1], row[2]) for row in rows if row[0] and row[1] and row[2]}

    for city_code in municipality_codes:
        municipality = db.get(Municipality, city_code)
        pref_code = prefecture_code or (municipality.prefecture_code if municipality else None)
        for year in range(from_year, to_year + 1):
            start_quarter = 3 if year == 2005 else 1
            for quarter in range(start_quarter, 5):
                key = (city_code, year, quarter)
                if skip_done and key in done_keys:
                    totals["skipped"] += 1
                    continue
                totals["jobs"] += 1
                try:
                    result = sync_transactions_for_city_period(
                        db,
                        client,
                        city_code=city_code,
                        year=year,
                        quarter=quarter,
                        prefecture_code=pref_code,
                    )
                except Exception:
                    db.rollback()
                    totals["errors"] += 1
                    continue
                totals["skipped"] += result.get("skipped", 0)
                totals["inserted"] += result.get("inserted", 0)
                totals["duplicates"] += result.get("duplicates", 0)
                totals["fetched"] += result.get("fetched", 0)
    return totals
