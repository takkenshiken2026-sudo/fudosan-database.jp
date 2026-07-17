from __future__ import annotations

import argparse

from sqlalchemy import func, select

from app.estat.client import EstatClient
from app.estat.db import (
    EstatAreaCodeMap,
    EstatClassCode,
    EstatClassObject,
    EstatStatValue,
    EstatStatsTable,
    EstatSurvey,
    EstatSyncCheckpoint,
    EstatSessionLocal,
    init_estat_db,
)
from app.estat.sync import (
    estimate_plan,
    fill_pipeline,
    mark_sync_targets,
    retry_failed,
    seed_surveys,
    sync_catalog,
    sync_meta,
    sync_meta_all,
    sync_values,
    sync_values_batch,
    sync_values_prefecture,
)
from app.estat.targets import (
    apply_real_estate_targets,
    compact_to_targets,
    prune_non_target_data,
    replace_estat_database,
)


def print_status(db) -> None:
    print(
        {
            "surveys": db.scalar(select(func.count(EstatSurvey.stats_code))),
            "stats_tables": db.scalar(select(func.count(EstatStatsTable.stats_data_id))),
            "sync_targets": db.scalar(
                select(func.count(EstatStatsTable.stats_data_id)).where(
                    EstatStatsTable.is_sync_target == 1
                )
            ),
            "class_objects": db.scalar(select(func.count(EstatClassObject.id))),
            "class_codes": db.scalar(select(func.count(EstatClassCode.id))),
            "area_codes": db.scalar(select(func.count(EstatAreaCodeMap.estat_area_code))),
            "stat_values": db.scalar(select(func.count(EstatStatValue.id))),
            "checkpoints_done": db.scalar(
                select(func.count(EstatSyncCheckpoint.id)).where(
                    EstatSyncCheckpoint.status == "done"
                )
            ),
            "checkpoints_failed": db.scalar(
                select(func.count(EstatSyncCheckpoint.id)).where(
                    EstatSyncCheckpoint.status == "failed"
                )
            ),
        }
    )


def main() -> None:
    parser = argparse.ArgumentParser(description="e-Stat DB同期")
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("init-db", help="e-Stat DB初期化")
    sub.add_parser("test-api", help="API接続テスト（キーは表示しない）")
    sub.add_parser("seed-surveys", help="対象政府統計を登録")
    sub.add_parser("status", help="DB件数サマリー")

    catalog = sub.add_parser("sync-catalog", help="統計表カタログ同期")
    catalog.add_argument("--stats-code", help="政府統計コード（例: 00200502）")

    mark = sub.add_parser("mark-targets", help="同期対象の統計表を設定")
    mark.add_argument("--stats-code", help="政府統計コード")
    mark.add_argument(
        "--mode",
        choices=["real-estate", "all"],
        default="real-estate",
        help="real-estate=不動産向けに絞り込み, all=市区町村表をすべて対象",
    )

    preview = sub.add_parser("preview-targets", help="不動産向け同期対象の一覧")
    preview.add_argument("--stats-code", help="政府統計コード")

    prune = sub.add_parser(
        "prune-non-targets",
        help="同期対象外の統計値・チェックポイントを削除",
    )

    compact = sub.add_parser(
        "compact-targets",
        help="同期対象データだけを新しいDBファイルにコピー",
    )
    compact.add_argument(
        "--output",
        default="../data/estat_compact.db",
        help="出力先DBパス",
    )
    compact.add_argument(
        "--replace",
        action="store_true",
        help="完了後に元DBを置き換える",
    )

    meta = sub.add_parser("sync-meta", help="メタ情報同期（1表）")
    meta.add_argument("--stats-data-id", required=True, help="統計表ID")

    meta_all = sub.add_parser("sync-meta-all", help="同期対象のメタ情報を一括取得")
    meta_all.add_argument("--stats-code", help="政府統計コード")
    meta_all.add_argument("--force", action="store_true")
    meta_all.add_argument("--worker-id", type=int, default=0)
    meta_all.add_argument("--worker-count", type=int, default=1)
    meta_all.add_argument("--sleep", type=float)

    values = sub.add_parser("sync-values", help="統計値同期（1地域）")
    values.add_argument("--stats-data-id", required=True, help="統計表ID")
    values.add_argument("--area-code", required=True, help="地域コード（例: 13101）")
    values.add_argument("--force", action="store_true")

    values_pref = sub.add_parser("sync-values-prefecture", help="統計値同期（都道府県単位）")
    values_pref.add_argument("--stats-data-id", required=True, help="統計表ID")
    values_pref.add_argument("--prefecture", required=True, help="都道府県コード（例: 13）")
    values_pref.add_argument("--force", action="store_true")

    values_batch = sub.add_parser("sync-values-batch", help="統計値を都道府県×統計表で一括同期")
    values_batch.add_argument("--stats-code", help="政府統計コード")
    values_batch.add_argument("--prefecture", help="都道府県コード（例: 13）")
    values_batch.add_argument("--force", action="store_true")
    values_batch.add_argument("--worker-id", type=int, default=0)
    values_batch.add_argument("--worker-count", type=int, default=1)
    values_batch.add_argument("--table-worker-id", type=int, default=0)
    values_batch.add_argument("--table-worker-count", type=int, default=1)
    values_batch.add_argument("--sleep", type=float)

    fill = sub.add_parser("fill", help="カタログ→メタ→値の一括パイプライン")
    fill.add_argument("--stats-code", help="政府統計コード（省略時は全統計）")
    fill.add_argument("--skip-catalog", action="store_true")
    fill.add_argument("--skip-meta", action="store_true")
    fill.add_argument("--skip-values", action="store_true")
    fill.add_argument("--force", action="store_true")

    plan = sub.add_parser("plan", help="残りAPIリクエスト数の見積もり")
    plan.add_argument("--stats-code", help="政府統計コード")

    retry = sub.add_parser("retry-failed", help="failed チェックポイントを再実行")
    retry.add_argument("--sync-type", choices=["meta", "values"])

    args = parser.parse_args()
    db = EstatSessionLocal()
    try:
        if args.command == "init-db":
            init_estat_db()
            print("estat DB initialized")
            return

        if args.command == "test-api":
            client = EstatClient()
            payload = client.get_stats_list(
                statsCode="00200502",
                collectArea="3",
                limit=1,
                explanationGetFlg="N",
            )
            tables = payload.get("DATALIST_INF", {}).get("TABLE_INF")
            table_id = None
            if isinstance(tables, dict):
                table_id = tables.get("@id")
            elif isinstance(tables, list) and tables:
                table_id = tables[0].get("@id")
            print({"api": "ok", "sample_table_id": table_id})
            return

        if args.command == "seed-surveys":
            count = seed_surveys(db)
            print({"seeded_surveys": count})
            return

        if args.command == "status":
            print_status(db)
            return

        if args.command == "plan":
            print(estimate_plan(db, stats_code=args.stats_code))
            return

        client = EstatClient(sleep_seconds=args.sleep) if getattr(args, "sleep", None) else EstatClient()
        if args.command == "sync-catalog":
            result = sync_catalog(db, client, stats_code=args.stats_code)
            print(result)
            return

        if args.command == "mark-targets":
            result = mark_sync_targets(
                db,
                stats_code=args.stats_code,
                mode=args.mode,
            )
            print(result)
            return

        if args.command == "preview-targets":
            from sqlalchemy import select

            from app.estat.db import EstatStatsTable
            from app.estat.targets import select_real_estate_targets

            filters = []
            if args.stats_code:
                filters.append(EstatStatsTable.stats_code == args.stats_code)
            tables = db.scalars(select(EstatStatsTable).where(*filters)).all()
            selected = select_real_estate_targets(tables)
            print(
                {
                    "total_targets": len(selected),
                    "values_requests": len(selected) * 47,
                    "tables": [
                        {
                            "stats_code": table.stats_code,
                            "stats_data_id": table.stats_data_id,
                            "survey_year": table.survey_year,
                            "title": table.title,
                        }
                        for table in selected
                    ],
                }
            )
            return

        if args.command == "prune-non-targets":
            result = prune_non_target_data(db)
            print(result)
            return

        if args.command == "compact-targets":
            result = compact_to_targets(db, destination_path=args.output)
            print(result)
            if args.replace:
                db.close()
                replace_estat_database(args.output)
                print({"replaced": True, "path": args.output})
            return

        if args.command == "sync-meta":
            result = sync_meta(db, client, args.stats_data_id)
            print(result)
            return

        if args.command == "sync-meta-all":
            result = sync_meta_all(
                db,
                client,
                stats_code=args.stats_code,
                force=args.force,
                worker_id=args.worker_id,
                worker_count=args.worker_count,
            )
            print(result)
            return

        if args.command == "sync-values":
            result = sync_values(
                db,
                client,
                stats_data_id=args.stats_data_id,
                area_code=args.area_code,
                force=args.force,
            )
            print(result)
            return

        if args.command == "sync-values-prefecture":
            result = sync_values_prefecture(
                db,
                client,
                stats_data_id=args.stats_data_id,
                prefecture_code=args.prefecture,
                force=args.force,
            )
            print(result)
            return

        if args.command == "sync-values-batch":
            result = sync_values_batch(
                db,
                client,
                stats_code=args.stats_code,
                prefecture_code=args.prefecture,
                force=args.force,
                worker_id=args.worker_id,
                worker_count=args.worker_count,
                table_worker_id=args.table_worker_id,
                table_worker_count=args.table_worker_count,
            )
            print(result)
            return

        if args.command == "fill":
            result = fill_pipeline(
                db,
                client,
                stats_code=args.stats_code,
                skip_catalog=args.skip_catalog,
                skip_meta=args.skip_meta,
                skip_values=args.skip_values,
                force=args.force,
            )
            print(result)
            return

        if args.command == "retry-failed":
            result = retry_failed(db, client, sync_type=args.sync_type)
            print(result)
            return
    finally:
        db.close()


if __name__ == "__main__":
    main()
