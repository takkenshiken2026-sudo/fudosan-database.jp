from __future__ import annotations

import json
import re
from datetime import datetime
from typing import Optional

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import LandPricePoint, SyncCheckpoint
from app.reinfolib.client import ReinfolibClient, parse_float, parse_int
from app.reinfolib.tiles import iter_prefecture_tiles, tile_key

_PRICE_RE = re.compile(r"([\d,]+)")
_CADASTRAL_RE = re.compile(r"([\d,.]+)")


def parse_unit_price(value: object) -> Optional[int]:
    if value is None:
        return None
    match = _PRICE_RE.search(str(value))
    if not match:
        return None
    return parse_int(match.group(1))


def parse_area_sqm(value: object) -> Optional[float]:
    if value is None:
        return None
    match = _CADASTRAL_RE.search(str(value))
    if not match:
        return None
    return parse_float(match.group(1))


def parse_change_rate(value: object) -> Optional[float]:
    if value is None:
        return None
    text = str(value).strip().replace("%", "")
    if not text:
        return None
    try:
        return float(text)
    except ValueError:
        return None


def _record_to_land_price(
    props: dict,
    *,
    survey_year: int,
    longitude: Optional[float],
    latitude: Optional[float],
) -> Optional[LandPricePoint]:
    point_id = parse_int(props.get("point_id"))
    if point_id is None:
        return None
    return LandPricePoint(
        point_id=point_id,
        survey_year=survey_year,
        land_price_type=parse_int(props.get("land_price_type")),
        prefecture_code=str(props.get("prefecture_code") or ""),
        municipality_code=str(props.get("city_code") or ""),
        use_category_name=props.get("use_category_name_ja") or None,
        standard_lot_number=props.get("standard_lot_number_ja") or None,
        location=props.get("location") or props.get("location_number_ja") or None,
        ward_name=props.get("ward_town_village_name_ja") or None,
        place_name=props.get("place_name_ja") or None,
        unit_price=parse_unit_price(props.get("u_current_years_price_ja")),
        last_years_price=parse_int(props.get("last_years_price")),
        year_on_year_change_rate=parse_change_rate(props.get("year_on_year_change_rate")),
        area_sqm=parse_area_sqm(props.get("u_cadastral_ja")),
        latitude=latitude,
        longitude=longitude,
        target_year_label=props.get("target_year_name_ja") or None,
        regulations_use_category=props.get("regulations_use_category_name_ja") or None,
        nearest_station=props.get("nearest_station_name_ja") or None,
        raw_json=json.dumps(props, ensure_ascii=False),
        synced_at=datetime.utcnow(),
    )


def sync_land_prices_for_tile_year(
    db: Session,
    client: ReinfolibClient,
    *,
    zoom: int,
    x: int,
    y: int,
    year: int,
    prefecture_code: Optional[str] = None,
) -> dict[str, int]:
    key = tile_key(zoom, x, y)
    checkpoint = db.scalar(
        select(SyncCheckpoint).where(
            SyncCheckpoint.sync_type == "land_prices",
            SyncCheckpoint.municipality_code == key,
            SyncCheckpoint.trade_year == year,
            SyncCheckpoint.trade_quarter == 0,
        )
    )
    if checkpoint and checkpoint.status in ("done", "empty"):
        return {"skipped": 1, "inserted": 0, "duplicates": 0, "fetched": 0}

    started = datetime.utcnow()
    status = "done"
    error_message: Optional[str] = None
    inserted = 0
    duplicates = 0
    fetched = 0

    try:
        features = client.fetch_land_prices(zoom=zoom, x=x, y=y, year=year)
    except Exception as exc:
        status = "failed"
        error_message = str(exc)
        features = []

    if status == "done" and not features:
        status = "empty"

    point_ids = [
        parse_int(feature.get("properties", {}).get("point_id"))
        for feature in features
    ]
    point_ids = [pid for pid in point_ids if pid is not None]
    existing_ids: set[int] = set()
    if point_ids:
        existing_ids = set(
            db.scalars(
                select(LandPricePoint.point_id).where(
                    LandPricePoint.survey_year == year,
                    LandPricePoint.point_id.in_(point_ids),
                )
            ).all()
        )

    for feature in features:
        props = feature.get("properties", {})
        geometry = feature.get("geometry", {})
        coords = geometry.get("coordinates") or [None, None]
        longitude = parse_float(coords[0]) if len(coords) > 0 else None
        latitude = parse_float(coords[1]) if len(coords) > 1 else None
        record = _record_to_land_price(
            props,
            survey_year=year,
            longitude=longitude,
            latitude=latitude,
        )
        if record is None:
            continue
        fetched += 1
        if record.point_id in existing_ids:
            duplicates += 1
            continue
        db.add(record)
        existing_ids.add(record.point_id)
        inserted += 1

    if checkpoint:
        checkpoint.prefecture_code = prefecture_code
        checkpoint.status = status
        checkpoint.record_count = fetched
        checkpoint.error_message = error_message
        checkpoint.started_at = started
        checkpoint.finished_at = datetime.utcnow()
    else:
        db.add(
            SyncCheckpoint(
                sync_type="land_prices",
                prefecture_code=prefecture_code,
                municipality_code=key,
                trade_year=year,
                trade_quarter=0,
                status=status,
                record_count=fetched,
                error_message=error_message,
                started_at=started,
                finished_at=datetime.utcnow(),
            )
        )
    db.commit()
    return {"skipped": 0, "inserted": inserted, "duplicates": duplicates, "fetched": fetched}


def _load_empty_tiles(db: Session, reference_year: int) -> set[str]:
    rows = db.execute(
        select(SyncCheckpoint.municipality_code).where(
            SyncCheckpoint.sync_type == "land_prices",
            SyncCheckpoint.trade_year == reference_year,
            SyncCheckpoint.status == "empty",
        )
    ).all()
    return {row[0] for row in rows if row[0]}


def _sync_land_prices_for_year(
    db: Session,
    client: ReinfolibClient,
    totals: dict[str, int],
    *,
    year: int,
    prefecture_code: Optional[str],
    zoom: int,
    skip_done: bool,
    done_keys: set[tuple[str, int]],
    empty_tiles: set[str],
    skip_empty_tiles: bool,
    reference_year: int,
) -> None:
    for zoom_level, x, y in iter_prefecture_tiles(prefecture_code, zoom=zoom):
        key = tile_key(zoom_level, x, y)
        if skip_empty_tiles and year != reference_year and key in empty_tiles:
            totals["skipped_empty_tiles"] += 1
            continue
        if skip_done and (key, year) in done_keys:
            totals["skipped"] += 1
            continue
        totals["jobs"] += 1
        try:
            result = sync_land_prices_for_tile_year(
                db,
                client,
                zoom=zoom_level,
                x=x,
                y=y,
                year=year,
                prefecture_code=prefecture_code,
            )
        except Exception:
            db.rollback()
            totals["errors"] += 1
            continue
        totals["skipped"] += result.get("skipped", 0)
        totals["inserted"] += result.get("inserted", 0)
        totals["duplicates"] += result.get("duplicates", 0)
        totals["fetched"] += result.get("fetched", 0)


def sync_land_prices(
    db: Session,
    client: ReinfolibClient,
    *,
    from_year: int,
    to_year: int,
    prefecture_code: Optional[str] = None,
    zoom: int = 13,
    skip_done: bool = True,
    skip_empty_tiles: bool = True,
    reference_year: Optional[int] = None,
) -> dict[str, int]:
    ref_year = reference_year if reference_year is not None else min(to_year, 2024)
    if ref_year < from_year or ref_year > to_year:
        ref_year = to_year

    totals: dict[str, int] = {
        "jobs": 0,
        "skipped": 0,
        "skipped_empty_tiles": 0,
        "inserted": 0,
        "duplicates": 0,
        "fetched": 0,
        "errors": 0,
        "reference_year": ref_year,
    }

    done_keys: set[tuple[str, int]] = set()
    if skip_done:
        rows = db.execute(
            select(
                SyncCheckpoint.municipality_code,
                SyncCheckpoint.trade_year,
            ).where(
                SyncCheckpoint.sync_type == "land_prices",
                SyncCheckpoint.status.in_(("done", "empty")),
            )
        ).all()
        done_keys = {(row[0], row[1]) for row in rows if row[0] and row[1]}

    if skip_empty_tiles:
        _sync_land_prices_for_year(
            db,
            client,
            totals,
            year=ref_year,
            prefecture_code=prefecture_code,
            zoom=zoom,
            skip_done=skip_done,
            done_keys=done_keys,
            empty_tiles=set(),
            skip_empty_tiles=False,
            reference_year=ref_year,
        )
        empty_tiles = _load_empty_tiles(db, ref_year)
        totals["empty_tiles"] = len(empty_tiles)
    else:
        empty_tiles = set()

    for year in range(from_year, to_year + 1):
        if skip_empty_tiles and year == ref_year:
            continue
        _sync_land_prices_for_year(
            db,
            client,
            totals,
            year=year,
            prefecture_code=prefecture_code,
            zoom=zoom,
            skip_done=skip_done,
            done_keys=done_keys,
            empty_tiles=empty_tiles,
            skip_empty_tiles=skip_empty_tiles,
            reference_year=ref_year,
        )
    return totals
