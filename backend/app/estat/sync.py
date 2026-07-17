from __future__ import annotations

from datetime import datetime
from typing import Any, Optional

import time

from sqlalchemy import delete, func, select
from sqlalchemy.dialects.sqlite import insert
from sqlalchemy.orm import Session

from app.estat.client import EstatClient, ensure_list, estat_code, estat_text
from app.estat.db import (
    EstatAreaCodeMap,
    EstatClassCode,
    EstatClassObject,
    EstatStatValue,
    EstatStatsTable,
    EstatSurvey,
    EstatSyncCheckpoint,
)
from app.reinfolib.prefectures import PREFECTURES

DEFAULT_SURVEYS: list[dict[str, str]] = [
    {
        "stats_code": "00200502",
        "survey_name": "社会・人口統計体系",
        "update_cycle": "annual",
    },
    {
        "stats_code": "00200521",
        "survey_name": "国勢調査",
        "update_cycle": "quinquennial",
    },
    {
        "stats_code": "00200522",
        "survey_name": "住宅・土地統計調査",
        "update_cycle": "annual",
    },
    {
        "stats_code": "00200241",
        "survey_name": "住民基本台帳人口",
        "update_cycle": "annual",
    },
]

VALUE_BATCH_SIZE = 500


def seed_surveys(db: Session) -> int:
    now = datetime.utcnow()
    count = 0
    for row in DEFAULT_SURVEYS:
        existing = db.get(EstatSurvey, row["stats_code"])
        if existing:
            existing.survey_name = row["survey_name"]
            existing.update_cycle = row["update_cycle"]
            existing.is_active = 1
            existing.synced_at = now
        else:
            db.add(EstatSurvey(synced_at=now, **row))
        count += 1
    db.commit()
    return count


def _parse_collect_area(value: Any) -> Optional[int]:
    text = estat_text(value)
    if text.isdigit():
        return int(text)
    mapping = {"全国": 1, "都道府県": 2, "市区町村": 3}
    return mapping.get(text)


def _parse_table_row(table: dict[str, Any]) -> dict[str, Any]:
    stats_name = table.get("STAT_NAME", {})
    return {
        "stats_data_id": estat_text(table.get("@id")),
        "stats_code": estat_code(stats_name) or estat_text(stats_name),
        "title": estat_text(table.get("TITLE")),
        "survey_year": estat_text(table.get("SURVEY_DATE")),
        "collect_area": _parse_collect_area(table.get("COLLECT_AREA")),
        "statistics_name": estat_text(table.get("STATISTICS_NAME")),
        "updated_date": estat_text(table.get("UPDATED_DATE")),
    }


def sync_catalog(
    db: Session,
    client: EstatClient,
    *,
    stats_code: Optional[str] = None,
    collect_area: int = 3,
) -> dict[str, int]:
    surveys = db.scalars(
        select(EstatSurvey).where(EstatSurvey.is_active == 1)
    ).all()
    if stats_code:
        surveys = [s for s in surveys if s.stats_code == stats_code]
    if not surveys:
        raise RuntimeError("同期対象の政府統計がありません。seed-surveys を実行してください。")

    now = datetime.utcnow()
    inserted = 0
    updated = 0
    for survey in surveys:
        start_position = 1
        has_tables = False
        while True:
            payload = client.get_stats_list(
                statsCode=survey.stats_code,
                collectArea=str(collect_area),
                explanationGetFlg="N",
                startPosition=start_position,
                limit=100000,
            )
            tables = ensure_list(payload.get("DATALIST_INF", {}).get("TABLE_INF"))
            if not tables:
                break
            has_tables = True
            for table in tables:
                parsed = _parse_table_row(table)
                if not parsed["stats_data_id"]:
                    continue
                existing = db.get(EstatStatsTable, parsed["stats_data_id"])
                if existing:
                    for key, value in parsed.items():
                        if key != "stats_data_id":
                            setattr(existing, key, value)
                    existing.synced_at = now
                    updated += 1
                else:
                    db.add(
                        EstatStatsTable(
                            synced_at=now,
                            is_sync_target=0,
                            **parsed,
                        )
                    )
                    inserted += 1
            next_key = payload.get("DATALIST_INF", {}).get("NEXT_KEY")
            if not next_key:
                break
            start_position = int(next_key)
        if has_tables:
            survey.synced_at = now
    db.commit()
    return {"inserted": inserted, "updated": updated}


def mark_sync_targets(
    db: Session,
    *,
    stats_code: Optional[str] = None,
    collect_area: int = 3,
    mode: str = "real-estate",
) -> dict[str, int]:
    if mode == "real-estate":
        from app.estat.targets import apply_real_estate_targets

        result = apply_real_estate_targets(db, stats_code=stats_code)
        return {
            "mode": mode,
            "marked": result.marked,
            "unmarked": result.unmarked,
            "total_targets": result.total_targets,
        }

    filters = [EstatStatsTable.collect_area == collect_area]
    if stats_code:
        filters.append(EstatStatsTable.stats_code == stats_code)
    tables = db.scalars(select(EstatStatsTable).where(*filters)).all()
    marked = 0
    for table in tables:
        if not table.is_sync_target:
            table.is_sync_target = 1
            marked += 1
    db.commit()
    return {"mode": mode, "marked": marked, "unmarked": 0, "total_targets": len(tables)}


def _infer_area_mapping(code: str, name: str) -> tuple[str, Optional[str], Optional[str]]:
    if code == "00000":
        return "national", None, None
    if len(code) == 5 and code.endswith("000"):
        return "prefecture", code[:2], None
    if len(code) == 5:
        return "municipality", code[:2], code
    return "other", None, None


def sync_meta(db: Session, client: EstatClient, stats_data_id: str) -> dict[str, int]:
    table = db.get(EstatStatsTable, stats_data_id)
    if not table:
        raise RuntimeError(f"統計表 {stats_data_id} が見つかりません。sync-catalog を先に実行してください。")

    checkpoint = _get_or_create_checkpoint(
        db,
        sync_type="meta",
        stats_data_id=stats_data_id,
        area_code="",
    )
    checkpoint.status = "pending"
    checkpoint.started_at = datetime.utcnow()
    checkpoint.error_message = None
    db.commit()

    try:
        payload = client.get_meta_info(stats_data_id)
        class_inf = payload.get("METADATA_INF", {}).get("CLASS_INF", {})
        objects = ensure_list(class_inf.get("CLASS_OBJ"))

        db.execute(
            delete(EstatClassCode).where(EstatClassCode.stats_data_id == stats_data_id)
        )
        db.execute(
            delete(EstatClassObject).where(EstatClassObject.stats_data_id == stats_data_id)
        )

        object_count = 0
        code_count = 0
        area_count = 0
        for obj in objects:
            object_id = estat_text(obj.get("@id"))
            if not object_id:
                continue
            db.add(
                EstatClassObject(
                    stats_data_id=stats_data_id,
                    object_id=object_id,
                    object_name=estat_text(obj.get("@name")),
                )
            )
            object_count += 1
            for cls in ensure_list(obj.get("CLASS")):
                code = estat_text(cls.get("@code"))
                if not code:
                    continue
                name = estat_text(cls.get("@name"))
                db.add(
                    EstatClassCode(
                        stats_data_id=stats_data_id,
                        object_id=object_id,
                        code=code,
                        name=name,
                        level=int(cls.get("@level") or 0) or None,
                        parent_code=estat_text(cls.get("@parentCode")) or None,
                        unit=estat_text(cls.get("@unit")) or None,
                    )
                )
                code_count += 1
                if object_id == "area":
                    area_level, pref_code, muni_code = _infer_area_mapping(code, name)
                    existing = db.get(EstatAreaCodeMap, code)
                    if existing:
                        existing.area_level = area_level
                        existing.prefecture_code = pref_code
                        existing.municipality_code = muni_code
                        existing.area_name = name
                    else:
                        db.add(
                            EstatAreaCodeMap(
                                estat_area_code=code,
                                area_level=area_level,
                                prefecture_code=pref_code,
                                municipality_code=muni_code,
                                area_name=name,
                            )
                        )
                        area_count += 1
        table.synced_at = datetime.utcnow()
        checkpoint.status = "done"
        checkpoint.record_count = code_count
        checkpoint.finished_at = datetime.utcnow()
        db.commit()
        return {
            "objects": object_count,
            "codes": code_count,
            "area_codes": area_count,
        }
    except Exception as exc:
        checkpoint.status = "failed"
        checkpoint.error_message = str(exc)
        checkpoint.finished_at = datetime.utcnow()
        db.commit()
        raise


def _filter_worker_items(items: list, worker_id: int, worker_count: int) -> list:
    if worker_count <= 1:
        return items
    return [item for index, item in enumerate(items) if index % worker_count == worker_id]


def sync_meta_all(
    db: Session,
    client: EstatClient,
    *,
    stats_code: Optional[str] = None,
    force: bool = False,
    worker_id: int = 0,
    worker_count: int = 1,
) -> dict[str, int]:
    filters = [EstatStatsTable.is_sync_target == 1]
    if stats_code:
        filters.append(EstatStatsTable.stats_code == stats_code)
    tables = db.scalars(
        select(EstatStatsTable).where(*filters).order_by(EstatStatsTable.stats_data_id)
    ).all()
    tables = _filter_worker_items(tables, worker_id, worker_count)

    synced = 0
    skipped = 0
    failed = 0
    for table in tables:
        checkpoint = db.scalars(
            select(EstatSyncCheckpoint).where(
                EstatSyncCheckpoint.sync_type == "meta",
                EstatSyncCheckpoint.stats_data_id == table.stats_data_id,
                EstatSyncCheckpoint.area_code == "",
            )
        ).first()
        if checkpoint and checkpoint.status == "done" and not force:
            skipped += 1
            continue
        try:
            sync_meta(db, client, table.stats_data_id)
            synced += 1
            print(f"[meta] {table.stats_data_id} {table.title}")
        except Exception as exc:
            failed += 1
            print(f"[meta-failed] {table.stats_data_id}: {exc}")
    return {"synced": synced, "skipped": skipped, "failed": failed}


def _parse_value(stats_data_id: str, row: dict[str, Any]) -> Optional[EstatStatValue]:
    raw = estat_text(row.get("$"))
    annotation = estat_text(row.get("@annotation")) or None
    value: Optional[float]
    if raw in ("", "-", "…", "..."):
        value = None
    else:
        try:
            value = float(raw.replace(",", ""))
        except ValueError:
            value = None
    if annotation in ("*", "-", "x", "X"):
        value = None
    return EstatStatValue(
        stats_data_id=stats_data_id,
        tab_code=estat_text(row.get("@tab")),
        area_code=estat_text(row.get("@area")),
        time_code=estat_text(row.get("@time")),
        cat01=estat_text(row.get("@cat01")),
        cat02=estat_text(row.get("@cat02")),
        cat03=estat_text(row.get("@cat03")),
        cat04=estat_text(row.get("@cat04")),
        cat05=estat_text(row.get("@cat05")),
        value=value,
        unit=estat_text(row.get("@unit")) or None,
        annotation=annotation,
        synced_at=datetime.utcnow(),
    )


def _prefecture_area_range(prefecture_code: str) -> tuple[str, str]:
    pref = prefecture_code.zfill(2)
    return f"{pref}000", f"{pref}999"


def _get_or_create_checkpoint(
    db: Session,
    *,
    sync_type: str,
    stats_data_id: str,
    area_code: str,
) -> EstatSyncCheckpoint:
    checkpoint = db.scalars(
        select(EstatSyncCheckpoint).where(
            EstatSyncCheckpoint.sync_type == sync_type,
            EstatSyncCheckpoint.stats_data_id == stats_data_id,
            EstatSyncCheckpoint.area_code == area_code,
        )
    ).first()
    if checkpoint:
        return checkpoint
    checkpoint = EstatSyncCheckpoint(
        sync_type=sync_type,
        stats_data_id=stats_data_id,
        area_code=area_code,
        status="pending",
    )
    db.add(checkpoint)
    db.flush()
    return checkpoint


def _flush_value_batch(db: Session, batch: list[EstatStatValue]) -> int:
    if not batch:
        return 0
    synced_at = datetime.utcnow()
    rows = [
        {
            "stats_data_id": row.stats_data_id,
            "tab_code": row.tab_code,
            "area_code": row.area_code,
            "time_code": row.time_code,
            "cat01": row.cat01,
            "cat02": row.cat02,
            "cat03": row.cat03,
            "cat04": row.cat04,
            "cat05": row.cat05,
            "value": row.value,
            "unit": row.unit,
            "annotation": row.annotation,
            "synced_at": synced_at,
        }
        for row in batch
    ]
    stmt = insert(EstatStatValue).values(rows)
    stmt = stmt.on_conflict_do_nothing(
        index_elements=[
            "stats_data_id",
            "tab_code",
            "area_code",
            "time_code",
            "cat01",
            "cat02",
            "cat03",
            "cat04",
            "cat05",
        ],
    )
    for attempt in range(5):
        try:
            db.execute(stmt)
            db.commit()
            return len(batch)
        except Exception as exc:
            db.rollback()
            if "locked" not in str(exc).lower() or attempt == 4:
                raise
            time.sleep(0.2 * (attempt + 1))
    return len(batch)


def sync_values(
    db: Session,
    client: EstatClient,
    *,
    stats_data_id: str,
    area_code: str,
    force: bool = False,
) -> dict[str, int]:
    return _sync_values_impl(
        db,
        client,
        stats_data_id=stats_data_id,
        checkpoint_area_code=area_code,
        request_params={"cdArea": area_code},
        delete_filter=EstatStatValue.area_code == area_code,
        force=force,
    )


def sync_values_prefecture(
    db: Session,
    client: EstatClient,
    *,
    stats_data_id: str,
    prefecture_code: str,
    force: bool = False,
) -> dict[str, int]:
    pref = prefecture_code.zfill(2)
    area_from, area_to = _prefecture_area_range(pref)
    return _sync_values_impl(
        db,
        client,
        stats_data_id=stats_data_id,
        checkpoint_area_code=pref,
        request_params={"cdAreaFrom": area_from, "cdAreaTo": area_to},
        delete_filter=EstatStatValue.area_code.startswith(pref),
        force=force,
        log_label=f"pref={pref}",
    )


def _sync_values_impl(
    db: Session,
    client: EstatClient,
    *,
    stats_data_id: str,
    checkpoint_area_code: str,
    request_params: dict[str, str],
    delete_filter,
    force: bool = False,
    log_label: str = "",
) -> dict[str, int]:
    table = db.get(EstatStatsTable, stats_data_id)
    if not table:
        raise RuntimeError(f"統計表 {stats_data_id} が見つかりません。")

    checkpoint = _get_or_create_checkpoint(
        db,
        sync_type="values",
        stats_data_id=stats_data_id,
        area_code=checkpoint_area_code,
    )
    if checkpoint.status == "done" and not force:
        return {"skipped": 1, "inserted": 0}

    checkpoint.status = "pending"
    checkpoint.started_at = datetime.utcnow()
    checkpoint.error_message = None
    db.commit()

    inserted = 0
    try:
        if force:
            db.execute(
                delete(EstatStatValue).where(
                    EstatStatValue.stats_data_id == stats_data_id,
                    delete_filter,
                )
            )
            db.commit()

        batch: list[EstatStatValue] = []
        for values, result_inf in client.iter_stats_data(
            statsDataId=stats_data_id,
            limit=100000,
            **request_params,
        ):
            if not values:
                break
            for row in values:
                parsed = _parse_value(stats_data_id, row)
                if not parsed or not parsed.area_code:
                    continue
                batch.append(parsed)
                if len(batch) >= VALUE_BATCH_SIZE:
                    inserted += _flush_value_batch(db, batch)
                    batch.clear()
            checkpoint.start_position = int(result_inf.get("NEXT_KEY") or 0) or None
            checkpoint.record_count = inserted + len(batch)
            db.commit()

        if batch:
            inserted += _flush_value_batch(db, batch)

        checkpoint.status = "done"
        checkpoint.finished_at = datetime.utcnow()
        checkpoint.record_count = inserted
        table.synced_at = datetime.utcnow()
        db.commit()
        if inserted == 0:
            return {"skipped": 0, "inserted": 0, "empty": 1}
        if log_label:
            print(f"[values] {stats_data_id} {log_label} inserted={inserted}")
        return {"skipped": 0, "inserted": inserted}
    except Exception as exc:
        checkpoint.status = "failed"
        checkpoint.error_message = str(exc)
        checkpoint.finished_at = datetime.utcnow()
        db.commit()
        raise


def sync_values_batch(
    db: Session,
    client: EstatClient,
    *,
    stats_code: Optional[str] = None,
    prefecture_code: Optional[str] = None,
    prefecture_codes: Optional[list[str]] = None,
    force: bool = False,
    worker_id: int = 0,
    worker_count: int = 1,
    table_worker_id: int = 0,
    table_worker_count: int = 1,
) -> dict[str, int]:
    filters = [EstatStatsTable.is_sync_target == 1]
    if stats_code:
        filters.append(EstatStatsTable.stats_code == stats_code)
    tables = db.scalars(
        select(EstatStatsTable)
        .where(*filters)
        .order_by(EstatStatsTable.stats_data_id)
    ).all()
    prefectures = list(PREFECTURES)
    if prefecture_codes:
        codes = {code.zfill(2) for code in prefecture_codes}
        prefectures = [p for p in prefectures if p["code"] in codes]
    elif prefecture_code:
        prefectures = [p for p in prefectures if p["code"] == prefecture_code.zfill(2)]

    if table_worker_count > 1:
        tables = _filter_worker_items(tables, table_worker_id, table_worker_count)

    pairs: list[tuple[EstatStatsTable, dict[str, str]]] = [
        (table, pref) for table in tables for pref in prefectures
    ]
    if not prefecture_code and not prefecture_codes:
        pairs = _filter_worker_items(pairs, worker_id, worker_count)

    synced = 0
    skipped = 0
    failed = 0
    for table, pref in pairs:
        try:
            result = sync_values_prefecture(
                db,
                client,
                stats_data_id=table.stats_data_id,
                prefecture_code=pref["code"],
                force=force,
            )
            if result.get("skipped"):
                skipped += 1
            else:
                synced += 1
        except Exception as exc:
            failed += 1
            print(
                f"[values-failed] {table.stats_data_id} pref={pref['code']}: {exc}"
            )
    return {"synced": synced, "skipped": skipped, "failed": failed}


def retry_failed(
    db: Session,
    client: EstatClient,
    *,
    sync_type: Optional[str] = None,
) -> dict[str, int]:
    filters = [EstatSyncCheckpoint.status == "failed"]
    if sync_type:
        filters.append(EstatSyncCheckpoint.sync_type == sync_type)
    checkpoints = db.scalars(select(EstatSyncCheckpoint).where(*filters)).all()

    retried = 0
    failed = 0
    for checkpoint in checkpoints:
        try:
            if checkpoint.sync_type == "meta" and checkpoint.stats_data_id:
                sync_meta(db, client, checkpoint.stats_data_id)
            elif checkpoint.sync_type == "values" and checkpoint.stats_data_id:
                if len(checkpoint.area_code or "") == 2:
                    sync_values_prefecture(
                        db,
                        client,
                        stats_data_id=checkpoint.stats_data_id,
                        prefecture_code=checkpoint.area_code,
                        force=True,
                    )
                else:
                    sync_values(
                        db,
                        client,
                        stats_data_id=checkpoint.stats_data_id,
                        area_code=checkpoint.area_code or "",
                        force=True,
                    )
            retried += 1
        except Exception as exc:
            failed += 1
            print(f"[retry-failed] {checkpoint.sync_type} {checkpoint.stats_data_id}: {exc}")
    return {"retried": retried, "failed": failed}


def estimate_plan(
    db: Session,
    *,
    stats_code: Optional[str] = None,
) -> dict[str, int]:
    filters = [EstatStatsTable.is_sync_target == 1]
    if stats_code:
        filters.append(EstatStatsTable.stats_code == stats_code)
    target_tables = db.scalar(select(func.count(EstatStatsTable.stats_data_id)).where(*filters)) or 0
    target_ids = db.scalars(select(EstatStatsTable.stats_data_id).where(*filters)).all()
    prefectures = len(PREFECTURES)

    meta_done = db.scalar(
        select(func.count(EstatSyncCheckpoint.id)).where(
            EstatSyncCheckpoint.sync_type == "meta",
            EstatSyncCheckpoint.status == "done",
            EstatSyncCheckpoint.stats_data_id.in_(target_ids),
        )
    ) or 0
    values_done = db.scalar(
        select(func.count(EstatSyncCheckpoint.id)).where(
            EstatSyncCheckpoint.sync_type == "values",
            EstatSyncCheckpoint.status == "done",
            EstatSyncCheckpoint.stats_data_id.in_(target_ids),
        )
    ) or 0

    return {
        "target_tables": target_tables,
        "prefectures": prefectures,
        "meta_requests_total": target_tables,
        "meta_requests_pending": max(target_tables - meta_done, 0),
        "values_requests_total": target_tables * prefectures,
        "values_requests_pending": max(target_tables * prefectures - values_done, 0),
    }


def fill_pipeline(
    db: Session,
    client: EstatClient,
    *,
    stats_code: Optional[str] = None,
    skip_catalog: bool = False,
    skip_meta: bool = False,
    skip_values: bool = False,
    force: bool = False,
) -> dict[str, Any]:
    results: dict[str, Any] = {}
    seed_surveys(db)
    results["seed_surveys"] = len(DEFAULT_SURVEYS)

    if not skip_catalog:
        results["catalog"] = sync_catalog(db, client, stats_code=stats_code)
    results["mark_targets"] = mark_sync_targets(db, stats_code=stats_code)

    if not skip_meta:
        results["meta"] = sync_meta_all(db, client, stats_code=stats_code, force=force)

    if not skip_values:
        results["values"] = sync_values_batch(
            db, client, stats_code=stats_code, force=force
        )

    results["plan"] = estimate_plan(db, stats_code=stats_code)
    return results
