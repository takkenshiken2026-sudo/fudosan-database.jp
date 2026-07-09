from __future__ import annotations

import json
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from typing import Optional

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import StationPassenger, SyncCheckpoint
from app.reinfolib.client import ReinfolibClient
from app.reinfolib.station_passengers import (
    geometry_centroid,
    latest_passenger_year,
    parse_passengers_by_year,
    passengers_json_dumps,
    prefecture_code_for_point,
)
from app.reinfolib.tiles import iter_prefecture_tiles, tile_key


def _record_key(group_code: str, line_name: str) -> tuple[str, str]:
    return group_code, line_name or ""


def _feature_to_station(feature: dict) -> Optional[StationPassenger]:
    props = feature.get("properties", {})
    group_code = str(props.get("S12_001g") or props.get("S12_001c") or "").strip()
    line_name = str(props.get("S12_003_ja") or "").strip()
    station_name = str(props.get("S12_001_ja") or "").strip()
    if not group_code or not station_name:
        return None

    latitude, longitude = geometry_centroid(feature.get("geometry", {}))
    counts = parse_passengers_by_year(props)
    latest_year, latest_passengers = latest_passenger_year(counts)

    return StationPassenger(
        station_code=str(props.get("S12_001c") or group_code),
        group_code=group_code,
        station_name=station_name,
        operator_name=props.get("S12_002_ja") or None,
        line_name=line_name,
        railway_type=str(props.get("S12_004") or "") or None,
        prefecture_code=prefecture_code_for_point(latitude, longitude),
        latitude=latitude,
        longitude=longitude,
        passengers_json=passengers_json_dumps(counts),
        latest_year=latest_year,
        latest_passengers=latest_passengers,
        raw_json=json.dumps(props, ensure_ascii=False),
        synced_at=datetime.utcnow(),
    )


def _persist_stations_for_tile(
    db: Session,
    *,
    zoom: int,
    x: int,
    y: int,
    features: list[dict],
    error_message: Optional[str],
    prefecture_code: Optional[str] = None,
    existing_checkpoint: Optional[SyncCheckpoint] = None,
) -> dict[str, int]:
    key = tile_key(zoom, x, y)
    started = datetime.utcnow()
    status = "failed" if error_message else "done"
    inserted = 0
    updated = 0
    fetched = 0

    if not error_message and not features:
        status = "empty"

    group_codes = [
        _record_key(
            str(f.get("properties", {}).get("S12_001g") or f.get("properties", {}).get("S12_001c") or ""),
            str(f.get("properties", {}).get("S12_003_ja") or ""),
        )
        for f in features
    ]
    group_codes = [k for k in group_codes if k[0]]

    existing: dict[tuple[str, str], StationPassenger] = {}
    if group_codes:
        gc_set = {g[0] for g in group_codes}
        rows = db.scalars(
            select(StationPassenger).where(StationPassenger.group_code.in_(gc_set))
        ).all()
        existing = {(r.group_code, r.line_name): r for r in rows}

    for feature in features:
        record = _feature_to_station(feature)
        if record is None:
            continue
        fetched += 1
        rk = _record_key(record.group_code, record.line_name)
        if rk in existing:
            row = existing[rk]
            row.station_code = record.station_code
            row.station_name = record.station_name
            row.operator_name = record.operator_name
            row.railway_type = record.railway_type
            row.prefecture_code = record.prefecture_code or row.prefecture_code
            row.latitude = record.latitude
            row.longitude = record.longitude
            row.passengers_json = record.passengers_json
            row.latest_year = record.latest_year
            row.latest_passengers = record.latest_passengers
            row.raw_json = record.raw_json
            row.synced_at = record.synced_at
            updated += 1
        else:
            db.add(record)
            existing[rk] = record
            inserted += 1

    if existing_checkpoint:
        existing_checkpoint.prefecture_code = prefecture_code
        existing_checkpoint.status = status
        existing_checkpoint.record_count = fetched
        existing_checkpoint.error_message = error_message
        existing_checkpoint.started_at = started
        existing_checkpoint.finished_at = datetime.utcnow()
    else:
        db.add(
            SyncCheckpoint(
                sync_type="station_passengers",
                prefecture_code=prefecture_code,
                municipality_code=key,
                trade_year=0,
                trade_quarter=0,
                status=status,
                record_count=fetched,
                error_message=error_message,
                started_at=started,
                finished_at=datetime.utcnow(),
            )
        )
    db.commit()
    return {"skipped": 0, "inserted": inserted, "updated": updated, "fetched": fetched}


def _fetch_tile_features(
    api_key: str,
    sleep_seconds: float,
    zoom: int,
    x: int,
    y: int,
) -> tuple[int, int, int, list[dict], Optional[str]]:
    client = ReinfolibClient(api_key=api_key, sleep_seconds=sleep_seconds)
    try:
        features = client.fetch_station_passengers(zoom=zoom, x=x, y=y)
        return zoom, x, y, features, None
    except Exception as exc:
        return zoom, x, y, [], str(exc)


def sync_stations_for_tile(
    db: Session,
    client: ReinfolibClient,
    *,
    zoom: int,
    x: int,
    y: int,
    prefecture_code: Optional[str] = None,
) -> dict[str, int]:
    key = tile_key(zoom, x, y)
    checkpoint = db.scalar(
        select(SyncCheckpoint).where(
            SyncCheckpoint.sync_type == "station_passengers",
            SyncCheckpoint.municipality_code == key,
            SyncCheckpoint.trade_year == 0,
            SyncCheckpoint.trade_quarter == 0,
        )
    )
    if checkpoint and checkpoint.status in ("done", "empty"):
        return {"skipped": 1, "inserted": 0, "updated": 0, "fetched": 0}

    try:
        features = client.fetch_station_passengers(zoom=zoom, x=x, y=y)
        error_message = None
    except Exception as exc:
        features = []
        error_message = str(exc)

    return _persist_stations_for_tile(
        db,
        zoom=zoom,
        x=x,
        y=y,
        features=features,
        error_message=error_message,
        prefecture_code=prefecture_code,
        existing_checkpoint=checkpoint,
    )


def sync_station_passengers(
    db: Session,
    client: ReinfolibClient,
    *,
    prefecture_code: Optional[str] = None,
    zoom: int = 14,
    skip_done: bool = True,
    workers: int = 1,
    api_key: Optional[str] = None,
    sleep_seconds: Optional[float] = None,
) -> dict[str, int]:
    totals: dict[str, int] = {
        "jobs": 0,
        "skipped": 0,
        "inserted": 0,
        "updated": 0,
        "fetched": 0,
        "errors": 0,
        "workers": max(1, workers),
    }

    done_tiles: set[str] = set()
    if skip_done:
        rows = db.execute(
            select(SyncCheckpoint.municipality_code).where(
                SyncCheckpoint.sync_type == "station_passengers",
                SyncCheckpoint.status.in_(("done", "empty")),
            )
        ).all()
        done_tiles = {row[0] for row in rows if row[0]}

    pending: list[tuple[int, int, int]] = []
    for zoom_level, x, y in iter_prefecture_tiles(prefecture_code, zoom=zoom):
        key = tile_key(zoom_level, x, y)
        if skip_done and key in done_tiles:
            totals["skipped"] += 1
            continue
        pending.append((zoom_level, x, y))

    if not pending:
        return totals

    key = api_key or client.api_key
    per_thread_sleep = (sleep_seconds if sleep_seconds is not None else client.sleep_seconds)
    if workers > 1:
        per_thread_sleep = per_thread_sleep / workers

    if workers <= 1:
        for zoom_level, x, y in pending:
            totals["jobs"] += 1
            try:
                result = sync_stations_for_tile(
                    db,
                    client,
                    zoom=zoom_level,
                    x=x,
                    y=y,
                    prefecture_code=prefecture_code,
                )
            except Exception:
                db.rollback()
                totals["errors"] += 1
                continue
            totals["skipped"] += result.get("skipped", 0)
            totals["inserted"] += result.get("inserted", 0)
            totals["updated"] += result.get("updated", 0)
            totals["fetched"] += result.get("fetched", 0)
        return totals

    batch_size = workers * 4
    for i in range(0, len(pending), batch_size):
        batch = pending[i : i + batch_size]
        totals["jobs"] += len(batch)
        fetched_tiles: dict[tuple[int, int, int], tuple[list[dict], Optional[str]]] = {}

        with ThreadPoolExecutor(max_workers=workers) as pool:
            futures = [
                pool.submit(_fetch_tile_features, key, per_thread_sleep, z, x, y)
                for z, x, y in batch
            ]
            for fut in as_completed(futures):
                z, x, y, features, err = fut.result()
                fetched_tiles[(z, x, y)] = (features, err)

        for zoom_level, x, y in batch:
            features, err = fetched_tiles.get((zoom_level, x, y), ([], "missing fetch result"))
            tile_key_str = tile_key(zoom_level, x, y)
            checkpoint = db.scalar(
                select(SyncCheckpoint).where(
                    SyncCheckpoint.sync_type == "station_passengers",
                    SyncCheckpoint.municipality_code == tile_key_str,
                    SyncCheckpoint.trade_year == 0,
                    SyncCheckpoint.trade_quarter == 0,
                )
            )
            if checkpoint and checkpoint.status in ("done", "empty"):
                totals["skipped"] += 1
                continue
            try:
                result = _persist_stations_for_tile(
                    db,
                    zoom=zoom_level,
                    x=x,
                    y=y,
                    features=features,
                    error_message=err,
                    prefecture_code=prefecture_code,
                    existing_checkpoint=checkpoint,
                )
            except Exception:
                db.rollback()
                totals["errors"] += 1
                continue
            totals["inserted"] += result.get("inserted", 0)
            totals["updated"] += result.get("updated", 0)
            totals["fetched"] += result.get("fetched", 0)

    return totals
