from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import delete, func, insert, select
from sqlalchemy.orm import Session

from app.estat.db import (
    EstatAreaCodeMap,
    EstatClassCode,
    EstatClassObject,
    EstatStatValue,
    EstatStatsTable,
    EstatSurvey,
    EstatSyncCheckpoint,
)

# 集計単位が市区町村以外、または不動産分析に直接使いにくい表
EXCLUDE_TITLE_PATTERNS: tuple[str, ...] = (
    "21大都市",
    "特別区",
    "人口集中",
    "大都市圏",
    "都市圏",
    "人口50万以上",
    "人口1万以上",
    "国籍",
    "産業",
    "職業",
    "学歴",
    "移動人口",
    "5年前の常住",
    "通勤",
    "通学",
    "不詳補完",
    "組替",
    "2000年（平成12年）",
    "労働力",
    "教育",
    "母子世帯",
    "父子世帯",
    "社会経済",
    "都市計画",
    "家族類型",
    "配偶関係",
    "経済構成",
    "昼夜間",
    "旧市区町村",
)

# 社会・人口統計体系: 最新年度バッチ (00000203*) の主要カテゴリのみ
SOCIAL_STATS_CODE = "00200502"
SOCIAL_LATEST_ID_PREFIX = "00000203"
SOCIAL_INCLUDE_TITLES: tuple[str, ...] = (
    "Ａ\u3000人口・世帯",
    "Ｈ\u3000居住",
    "Ｃ\u3000経済基盤",
)

# 国勢調査: 市区町村 × コア指標
CENSUS_STATS_CODE = "00200521"
CENSUS_TITLE_PREFIXES: tuple[str, ...] = (
    "男女別人口",
    "住宅の所有関係・住宅の建て方",
    "65歳以上世帯員に係る世帯の状態 世帯人員の人数別65歳以上一般世帯人員",
    "65歳以上世帯員に係る世帯の状態 住宅の所有の関係別65歳以上一般世帯人員",
)

# 住宅・土地統計: 市区町村 × コア指標
HOUSING_STATS_CODE = "00200522"
HOUSING_TITLE_PREFIXES: tuple[str, ...] = (
    "住宅及び世帯総数",
    "住宅の種類、建て方、建築の時期、建物の構造、階数 住宅の所有の関係(5区分)、建築の時期",
    "住宅の種類、建て方、建築の時期、建物の構造、階数 住宅の建て方(4区分)、構造(2区分)、階数(4区分)別住宅数",
    "住宅の種類、建て方、建築の時期、建物の構造、階数 住宅の所有の関係(5区分)、建て方(4区分)別専用住宅数",
    "借家の家賃 住宅の種類(2区分)別借家の住宅の１か月当たり家賃",
    "借家の家賃 住宅の種類(2区分)別住宅の１か月当たり家賃(10区分)別借家数",
    "借家の家賃・間代 住宅の種類(2区分)別借家の１か月当たり家賃・間代",
    "借家の家賃・間代 住宅の種類(2区分)別１か月当たり家賃・間代(10区分)別借家数",
    "居住世帯のない住宅",
    "腐朽･破損の有無",
    "持ち家の購入",
    "一戸建・長屋建住宅の敷地面積、建築面積、延べ面積 住宅の所有の関係(5区分)、建て方(2区分)別延べ面積",
)


def _title_excluded(title: str) -> bool:
    return any(pattern in title for pattern in EXCLUDE_TITLE_PATTERNS)


def _matches_prefix(title: str, prefixes: tuple[str, ...]) -> bool:
    return any(title.startswith(prefix) for prefix in prefixes)


def _survey_year_key(table: EstatStatsTable) -> int:
    year = (table.survey_year or "").strip()
    if year.isdigit():
        return int(year)
    return 0


def is_real_estate_target(table: EstatStatsTable) -> bool:
    if table.collect_area != 3:
        return False

    title = table.title or ""
    if _title_excluded(title):
        return False

    code = table.stats_code
    if code == SOCIAL_STATS_CODE:
        return (
            table.stats_data_id.startswith(SOCIAL_LATEST_ID_PREFIX)
            and title in SOCIAL_INCLUDE_TITLES
        )
    if code == "00200241":
        return False
    if code == CENSUS_STATS_CODE:
        if "市区町村" not in title:
            return False
        return _matches_prefix(title, CENSUS_TITLE_PREFIXES)
    if code == HOUSING_STATS_CODE:
        if "市区町村" not in title:
            return False
        return _matches_prefix(title, HOUSING_TITLE_PREFIXES)
    return False


def select_real_estate_targets(tables: list[EstatStatsTable]) -> list[EstatStatsTable]:
    candidates = [table for table in tables if is_real_estate_target(table)]
    latest: dict[tuple[str, str], EstatStatsTable] = {}
    for table in candidates:
        key = (table.stats_code, table.title)
        current = latest.get(key)
        if current is None:
            latest[key] = table
            continue
        if _survey_year_key(table) > _survey_year_key(current):
            latest[key] = table
        elif (
            _survey_year_key(table) == _survey_year_key(current)
            and table.stats_data_id > current.stats_data_id
        ):
            latest[key] = table
    return sorted(latest.values(), key=lambda row: (row.stats_code, row.title))


@dataclass
class TargetFilterResult:
    marked: int
    unmarked: int
    total_targets: int
    target_ids: list[str]


def apply_real_estate_targets(
    db: Session,
    *,
    stats_code: str | None = None,
) -> TargetFilterResult:
    filters = []
    if stats_code:
        filters.append(EstatStatsTable.stats_code == stats_code)
    tables = db.scalars(select(EstatStatsTable).where(*filters)).all()
    selected = select_real_estate_targets(tables)
    target_ids = {table.stats_data_id for table in selected}

    marked = 0
    unmarked = 0
    for table in tables:
        should_target = table.stats_data_id in target_ids
        if should_target and not table.is_sync_target:
            table.is_sync_target = 1
            marked += 1
        elif not should_target and table.is_sync_target:
            table.is_sync_target = 0
            unmarked += 1

    db.commit()
    return TargetFilterResult(
        marked=marked,
        unmarked=unmarked,
        total_targets=len(selected),
        target_ids=sorted(target_ids),
    )


def prune_non_target_data(db: Session) -> dict[str, int]:
    target_ids = list(
        db.scalars(
            select(EstatStatsTable.stats_data_id).where(
                EstatStatsTable.is_sync_target == 1
            )
        ).all()
    )
    if not target_ids:
        return {"stat_values_deleted": 0, "checkpoints_deleted": 0}

    deleted_values = 0
    deleted_checkpoints = 0
    non_target_ids = list(
        db.scalars(
            select(EstatStatsTable.stats_data_id).where(
                EstatStatsTable.is_sync_target == 0
            )
        ).all()
    )
    for stats_data_id in non_target_ids:
        values_result = db.execute(
            delete(EstatStatValue).where(
                EstatStatValue.stats_data_id == stats_data_id
            )
        )
        deleted_values += values_result.rowcount or 0
        checkpoints_result = db.execute(
            delete(EstatSyncCheckpoint).where(
                EstatSyncCheckpoint.stats_data_id == stats_data_id
            )
        )
        deleted_checkpoints += checkpoints_result.rowcount or 0
        db.execute(
            delete(EstatClassCode).where(
                EstatClassCode.stats_data_id == stats_data_id
            )
        )
        db.execute(
            delete(EstatClassObject).where(
                EstatClassObject.stats_data_id == stats_data_id
            )
        )
        db.commit()

    return {
        "stat_values_deleted": deleted_values,
        "checkpoints_deleted": deleted_checkpoints,
    }


def compact_to_targets(
    db: Session,
    *,
    destination_path: str,
) -> dict[str, int]:
    import shutil
    from pathlib import Path

    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker

    from app.config import settings
    from app.estat.db import EstatBase

    source_url = settings.estat_database_url
    if not source_url.startswith("sqlite:///"):
        raise RuntimeError("compact-targets は SQLite のみ対応しています。")

    destination = Path(destination_path)
    if destination.exists():
        raise RuntimeError(f"出力先が既に存在します: {destination}")

    target_ids = list(
        db.scalars(
            select(EstatStatsTable.stats_data_id).where(
                EstatStatsTable.is_sync_target == 1
            )
        ).all()
    )
    if not target_ids:
        raise RuntimeError("同期対象の統計表がありません。mark-targets を先に実行してください。")

    destination.parent.mkdir(parents=True, exist_ok=True)
    dest_url = f"sqlite:///{destination}"
    dest_engine = create_engine(
        dest_url,
        connect_args={"check_same_thread": False, "timeout": 60},
    )
    EstatBase.metadata.create_all(bind=dest_engine)
    DestSession = sessionmaker(bind=dest_engine, autoflush=False, autocommit=False)
    dest_db = DestSession()

    copied = {
        "surveys": 0,
        "stats_tables": 0,
        "class_objects": 0,
        "class_codes": 0,
        "area_codes": 0,
        "stat_values": 0,
        "checkpoints": 0,
    }

    target_id_set = set(target_ids)
    try:
        survey_codes = {
            row.stats_code
            for row in db.scalars(select(EstatStatsTable)).all()
            if row.stats_data_id in target_id_set
        }
        for survey in db.scalars(select(EstatSurvey)).all():
            if survey.stats_code in survey_codes:
                dest_db.merge(survey)
                copied["surveys"] += 1

        for table in db.scalars(select(EstatStatsTable)).all():
            if table.stats_data_id in target_id_set:
                dest_db.merge(table)
                copied["stats_tables"] += 1

        for row in db.scalars(select(EstatClassObject)).all():
            if row.stats_data_id in target_id_set:
                dest_db.merge(row)
                copied["class_objects"] += 1

        for row in db.scalars(select(EstatClassCode)).all():
            if row.stats_data_id in target_id_set:
                dest_db.merge(row)
                copied["class_codes"] += 1

        dest_db.commit()

        area_codes = {
            row.estat_area_code
            for row in db.scalars(select(EstatAreaCodeMap)).all()
        }
        for row in db.scalars(select(EstatAreaCodeMap)).all():
            dest_db.merge(row)
        copied["area_codes"] = len(area_codes)

        for stats_data_id in target_ids:
            rows = db.scalars(
                select(EstatStatValue).where(
                    EstatStatValue.stats_data_id == stats_data_id
                )
            ).all()
            for row in rows:
                payload = {
                    key: getattr(row, key)
                    for key in EstatStatValue.__table__.columns.keys()
                    if key != "id"
                }
                dest_db.execute(insert(EstatStatValue).values(**payload))
            copied["stat_values"] += len(rows)
            dest_db.commit()

        for checkpoint in db.scalars(select(EstatSyncCheckpoint)).all():
            if checkpoint.stats_data_id in target_id_set:
                payload = {
                    key: getattr(checkpoint, key)
                    for key in EstatSyncCheckpoint.__table__.columns.keys()
                    if key != "id"
                }
                dest_db.execute(insert(EstatSyncCheckpoint).values(**payload))
                copied["checkpoints"] += 1
        dest_db.commit()
    finally:
        dest_db.close()
        dest_engine.dispose()

    return copied


def replace_estat_database(destination_path: str) -> None:
    import shutil
    from pathlib import Path

    from app.config import settings

    if not settings.estat_database_url.startswith("sqlite:///"):
        raise RuntimeError("replace は SQLite のみ対応しています。")

    source_path = Path(settings.estat_database_url.replace("sqlite:///", "", 1))
    compact_path = Path(destination_path)
    backup_path = source_path.with_suffix(".db.bak")

    for suffix in ("-wal", "-shm"):
        sidecar = Path(str(source_path) + suffix)
        if sidecar.exists():
            sidecar.unlink()

    if source_path.exists():
        if backup_path.exists():
            backup_path.unlink()
        source_path.rename(backup_path)

    shutil.move(str(compact_path), str(source_path))
    if backup_path.exists():
        backup_path.unlink()
