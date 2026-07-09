from __future__ import annotations

import json
from datetime import datetime
from typing import Any, Optional

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import EstatStatValue, SyncCheckpoint
from app.estat.client import EstatClient
from app.estat.parse import iter_table_list, iter_values, next_key, result_status

# 取得候補の統計表。statsDataId は e-Stat 側で更新されるため、実行前に
# `estat-search` （getStatsList）で最新IDを確認してから使うこと（要検証）。
# 汎用の --stats-data-id 指定なら任意の表を取得できる。
KNOWN_TABLES: dict[str, dict[str, str]] = {
    # 例: 住民基本台帳人口移動報告（市区町村別 転入超過）
    # "migration": {"stats_data_id": "＜要確認＞", "note": "住民基本台帳人口移動報告 市区町村別"},
    # 例: 国勢調査（市区町村別 男女別人口・世帯）
    # "population": {"stats_data_id": "＜要確認＞", "note": "国勢調査 男女別人口－市区町村"},
    # 例: 住宅・土地統計調査（空き家率）
    # "vacancy": {"stats_data_id": "＜要確認＞", "note": "住宅・土地統計調査 空き家"},
}

_PAGE_LIMIT = 100_000  # e-Stat の1リクエスト最大取得数

# 調査コード（statsCode）は安定。--survey 名で指定できるようにする。
# title_match は市区町村レベルの該当表を絞り込むためのタイトル語（スペース区切りAND）。
KNOWN_SURVEYS: dict[str, dict[str, str]] = {
    "census": {
        "stats_code": "00200521",
        "dataset": "population",
        "title_match": "男女別人口 市区町村",
        "note": "国勢調査 男女別人口・世帯（市区町村）",
    },
    "migration": {
        "stats_code": "00200523",
        "dataset": "migration",
        "title_match": "市区町村",
        "note": "住民基本台帳人口移動報告（転入・転出・転入超過）",
    },
    "housing": {
        "stats_code": "00200522",
        "dataset": "vacancy",
        "title_match": "市区町村",
        "note": "住宅・土地統計調査（空き家・持ち家・家賃）",
    },
}


def _is_municipality_area(code: str) -> bool:
    """5桁の市区町村コードか（全国 '00000' と都道府県 'XX000' を除外）。"""
    if len(code) != 5 or not code.isdigit():
        return False
    if code == "00000" or code.endswith("000"):
        return False
    return True


def sync_estat_table(
    db: Session,
    client: EstatClient,
    *,
    stats_data_id: str,
    dataset: str,
    municipality_only: bool = False,
    max_pages: Optional[int] = None,
    filters: Optional[dict[str, Any]] = None,
) -> dict[str, int]:
    """1つの e-Stat 統計表を全ページ取得し EstatStatValue に upsert する。"""
    started = datetime.utcnow()
    status = "done"
    error_message: Optional[str] = None
    inserted = 0
    updated = 0
    skipped = 0
    fetched = 0

    # 既存キーを一括ロードして dedup（同一表の再実行に対応）
    existing: dict[tuple[str, str, str], int] = {}
    for row in db.execute(
        select(
            EstatStatValue.area_code,
            EstatStatValue.cat_key,
            EstatStatValue.period_code,
            EstatStatValue.id,
        ).where(EstatStatValue.stats_data_id == stats_data_id)
    ).all():
        existing[(row[0], row[1], row[2])] = row[3]

    start_position: Optional[int] = None
    page = 0
    try:
        while True:
            payload = client.get_stats_data(
                stats_data_id=stats_data_id,
                start_position=start_position,
                limit=_PAGE_LIMIT,
                **(filters or {}),
            )
            st, msg = result_status(payload)
            if st not in (0, None):
                status = "failed"
                error_message = f"e-Stat STATUS={st}: {msg}"
                break

            for cell in iter_values(payload):
                area = cell["area_code"]
                if municipality_only and not _is_municipality_area(area):
                    skipped += 1
                    continue
                fetched += 1
                key = (area, cell["cat_key"], cell["time_code"] or "")
                record_id = existing.get(key)
                if record_id is not None:
                    obj = db.get(EstatStatValue, record_id)
                    obj.value = cell["value"]
                    obj.stat_label = cell["stat_label"]
                    obj.area_name = cell["area_name"]
                    obj.period_year = cell["period_year"]
                    obj.unit = cell["unit"]
                    obj.dataset = dataset
                    obj.raw_json = json.dumps(cell["raw"], ensure_ascii=False)
                    obj.synced_at = datetime.utcnow()
                    updated += 1
                else:
                    db.add(
                        EstatStatValue(
                            stats_data_id=stats_data_id,
                            dataset=dataset,
                            area_code=area,
                            area_name=cell["area_name"],
                            cat_key=cell["cat_key"],
                            stat_label=cell["stat_label"],
                            period_code=cell["time_code"] or "",
                            period_year=cell["period_year"],
                            value=cell["value"],
                            unit=cell["unit"],
                            raw_json=json.dumps(cell["raw"], ensure_ascii=False),
                            synced_at=datetime.utcnow(),
                        )
                    )
                    existing[key] = -1  # 同一バッチ内の重複挿入を防ぐマーカー
                    inserted += 1

            db.commit()
            page += 1
            nk = next_key(payload)
            if nk is None or (max_pages is not None and page >= max_pages):
                break
            start_position = nk
    except Exception as exc:  # noqa: BLE001 - 進捗を checkpoint に残して次へ
        db.rollback()
        status = "failed"
        error_message = str(exc)

    _upsert_checkpoint(
        db,
        stats_data_id=stats_data_id,
        status=status,
        record_count=fetched,
        error_message=error_message,
        started=started,
    )
    db.commit()
    return {
        "inserted": inserted,
        "updated": updated,
        "skipped": skipped,
        "fetched": fetched,
        "pages": page,
    }


def discover_tables(
    client: EstatClient,
    *,
    stats_code: str,
    title_match: Optional[str] = None,
    limit: int = 100,
) -> list[dict[str, str]]:
    """調査コードから統計表を検索し、タイトル語で絞り込んだ一覧を返す。"""
    payload = client.get_stats_list(stats_code=stats_code, limit=limit)
    st, msg = result_status(payload)
    if st not in (0, None):
        raise RuntimeError(f"getStatsList STATUS={st}: {msg}")
    tables = list(iter_table_list(payload))
    if title_match:
        needles = [n for n in title_match.split() if n]
        tables = [
            t for t in tables if all(n in t["search_text"] for n in needles)
        ]
    return tables


def sync_estat_survey(
    db: Session,
    client: EstatClient,
    *,
    stats_code: str,
    dataset: str,
    title_match: Optional[str] = None,
    municipality_only: bool = False,
    max_tables: Optional[int] = None,
    max_pages: Optional[int] = None,
    list_limit: int = 100,
) -> dict[str, Any]:
    """調査コードで該当する統計表を自動発見し、各表を取得してDB格納する。

    statsDataId を手で調べる必要をなくす turnkey な一括取り込み。
    """
    tables = discover_tables(
        client, stats_code=stats_code, title_match=title_match, limit=list_limit
    )
    if max_tables is not None:
        tables = tables[:max_tables]

    totals: dict[str, Any] = {
        "stats_code": stats_code,
        "matched_tables": len(tables),
        "tables": [],
        "inserted": 0,
        "updated": 0,
        "skipped": 0,
        "fetched": 0,
        "errors": 0,
    }
    for t in tables:
        try:
            result = sync_estat_table(
                db,
                client,
                stats_data_id=t["id"],
                dataset=dataset,
                municipality_only=municipality_only,
                max_pages=max_pages,
            )
        except Exception as exc:  # noqa: BLE001
            db.rollback()
            totals["errors"] += 1
            totals["tables"].append({"id": t["id"], "title": t["title"], "error": str(exc)})
            continue
        for key in ("inserted", "updated", "skipped", "fetched"):
            totals[key] += result.get(key, 0)
        totals["tables"].append(
            {"id": t["id"], "title": t["title"], **{k: result.get(k, 0) for k in ("inserted", "updated", "fetched")}}
        )
    return totals


def _upsert_checkpoint(
    db: Session,
    *,
    stats_data_id: str,
    status: str,
    record_count: int,
    error_message: Optional[str],
    started: datetime,
) -> None:
    checkpoint = db.scalar(
        select(SyncCheckpoint).where(
            SyncCheckpoint.sync_type == "estat",
            SyncCheckpoint.municipality_code == stats_data_id,
            SyncCheckpoint.trade_year == 0,
            SyncCheckpoint.trade_quarter == 0,
        )
    )
    if checkpoint:
        checkpoint.status = status
        checkpoint.record_count = record_count
        checkpoint.error_message = error_message
        checkpoint.started_at = started
        checkpoint.finished_at = datetime.utcnow()
    else:
        db.add(
            SyncCheckpoint(
                sync_type="estat",
                prefecture_code=None,
                municipality_code=stats_data_id,
                trade_year=0,
                trade_quarter=0,
                status=status,
                record_count=record_count,
                error_message=error_message,
                started_at=started,
                finished_at=datetime.utcnow(),
            )
        )
