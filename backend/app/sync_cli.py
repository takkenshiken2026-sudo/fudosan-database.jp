from __future__ import annotations

import argparse

from sqlalchemy import func, select

from app.config import settings
from app.db import (
    LandPricePoint,
    ListingSnapshot,
    Municipality,
    MunicipalityListingStat,
    MunicipalityPageMeta,
    Prefecture,
    SessionLocal,
    StationPassenger,
    SyncCheckpoint,
    TradeTransaction,
    init_db,
)
from app.listings.ingest import import_listings_csv, rebuild_listing_stats
from app.reinfolib.client import ReinfolibClient
from app.reinfolib.land_price_sync import sync_land_prices
from app.reinfolib.station_sync import sync_station_passengers
from app.reinfolib.stats import rebuild_page_meta, rebuild_trade_stats
from app.reinfolib.sync import seed_prefectures, sync_municipalities, sync_transactions
from app.reinfolib.sync_plan import estimate_transaction_requests
from app.reinfolib.tiles import count_land_price_requests


def _resolve_municipality_codes(db, prefecture: str | None, city: str | None) -> list[str]:
    if city:
        return [city]
    if prefecture:
        return db.scalars(
            select(Municipality.code).where(Municipality.prefecture_code == prefecture)
        ).all()
    return db.scalars(select(Municipality.code)).all()


def print_status(db) -> None:
    failed = db.scalar(
        select(func.count(SyncCheckpoint.id)).where(SyncCheckpoint.status == "failed")
    )
    print(
        {
            "prefectures": db.scalar(select(func.count(Prefecture.code))),
            "municipalities": db.scalar(select(func.count(Municipality.code))),
            "transactions": db.scalar(select(func.count(TradeTransaction.id))),
            "land_price_points": db.scalar(select(func.count(LandPricePoint.id))),
            "station_passengers": db.scalar(select(func.count(StationPassenger.id))),
            "listing_snapshots": db.scalar(select(func.count(ListingSnapshot.id))),
            "listing_stats": db.scalar(select(func.count(MunicipalityListingStat.id))),
            "sync_checkpoints_done": db.scalar(
                select(func.count(SyncCheckpoint.id)).where(
                    SyncCheckpoint.status.in_(("done", "empty"))
                )
            ),
            "sync_checkpoints_failed": failed,
            "page_meta_rows": db.scalar(select(func.count(MunicipalityPageMeta.municipality_code))),
        }
    )


def main() -> None:
    parser = argparse.ArgumentParser(description="不動産情報ライブラリ DB同期")
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("init-db", help="DB初期化")
    sub.add_parser("seed-prefectures", help="都道府県マスタ投入（API不要）")
    sub.add_parser("status", help="DB件数サマリー")

    municipalities = sub.add_parser("sync-municipalities", help="市区町村マスタ同期（XIT002）")
    municipalities.add_argument("--api-key", default=settings.reinfolib_api_key)

    transactions = sub.add_parser("sync-transactions", help="取引価格同期（XIT001）")
    transactions.add_argument("--prefecture", help="都道府県コード（例: 13）")
    transactions.add_argument("--city", help="市区町村コード（例: 13101）")
    transactions.add_argument("--from-year", type=int, default=2023)
    transactions.add_argument("--to-year", type=int, default=2025)
    transactions.add_argument("--api-key", default=settings.reinfolib_api_key)
    transactions.add_argument("--sleep", type=float, default=settings.sync_sleep_seconds)
    transactions.add_argument("--force", action="store_true", help="完了済みも再取得")

    land_prices = sub.add_parser("sync-land-prices", help="地価公示同期（XPT002）")
    land_prices.add_argument("--prefecture", help="都道府県コード（例: 13）")
    land_prices.add_argument("--from-year", type=int, default=1995)
    land_prices.add_argument("--to-year", type=int, default=2025)
    land_prices.add_argument("--zoom", type=int, default=13)
    land_prices.add_argument("--api-key", default=settings.reinfolib_api_key)
    land_prices.add_argument("--sleep", type=float, default=settings.sync_sleep_seconds)
    land_prices.add_argument("--force", action="store_true", help="完了済みも再取得")
    land_prices.add_argument(
        "--reference-year",
        type=int,
        help="空タイル判定に使う基準年（省略時: min(to_year, 2024)）",
    )
    land_prices.add_argument(
        "--no-skip-empty-tiles",
        action="store_true",
        help="空タイルスキップを無効化",
    )

    stations = sub.add_parser("sync-stations", help="駅別乗降客数同期（XKT015）")
    stations.add_argument("--prefecture", help="都道府県コード（例: 13）")
    stations.add_argument("--zoom", type=int, default=14)
    stations.add_argument("--api-key", default=settings.reinfolib_api_key)
    stations.add_argument("--sleep", type=float, default=settings.sync_sleep_seconds)
    stations.add_argument("--workers", type=int, default=1, help="タイル取得の並列数（I/O）")
    stations.add_argument("--force", action="store_true", help="完了済みも再取得")

    plan = sub.add_parser("plan", help="API呼び出し見積もり")
    plan.add_argument("--prefecture", help="都道府県コード")
    plan.add_argument("--city", help="市区町村コード")
    plan.add_argument("--from-year", type=int, default=2023)
    plan.add_argument("--to-year", type=int, default=2025)
    plan.add_argument("--sleep", type=float, default=settings.sync_sleep_seconds)

    plan_land = sub.add_parser("plan-land-prices", help="地価公示API呼び出し見積もり")
    plan_land.add_argument("--prefecture", help="都道府県コード")
    plan_land.add_argument("--from-year", type=int, default=1995)
    plan_land.add_argument("--to-year", type=int, default=2025)
    plan_land.add_argument("--zoom", type=int, default=13)
    plan_land.add_argument("--sleep", type=float, default=settings.sync_sleep_seconds)
    plan_land.add_argument("--reference-year", type=int)
    plan_land.add_argument(
        "--no-skip-empty-tiles",
        action="store_true",
        help="空タイルスキップを見積もりに含めない",
    )

    rebuild = sub.add_parser("rebuild-stats", help="集計テーブル再計算")
    rebuild.add_argument("--city", help="市区町村コード（省略時は全市区町村）")

    import_listings = sub.add_parser(
        "import-listings",
        help="募集価格CSVの取込（提携・オープンデータ・手動。スクレイピング不可）",
    )
    import_listings.add_argument("--csv", required=True, help="取込むCSVファイルパス")
    import_listings.add_argument(
        "--no-rebuild",
        action="store_true",
        help="取込後の集計再計算をスキップ",
    )

    rebuild_listings = sub.add_parser(
        "rebuild-listing-stats", help="募集価格の集計テーブル再計算"
    )
    rebuild_listings.add_argument(
        "--city", help="市区町村コード（省略時は全市区町村）"
    )

    retry = sub.add_parser("retry-failed", help="failed チェックポイントを再同期")
    retry.add_argument(
        "--sync-type",
        choices=("transactions", "land_prices", "station_passengers"),
        default="transactions",
    )
    retry.add_argument("--api-key", default=settings.reinfolib_api_key)
    retry.add_argument("--sleep", type=float, default=settings.sync_sleep_seconds)
    retry.add_argument("--dry-run", action="store_true", help="対象件数のみ表示")

    args = parser.parse_args()
    init_db()
    db = SessionLocal()

    try:
        if args.command == "init-db":
            print("DB initialized")
            return

        if args.command == "seed-prefectures":
            count = seed_prefectures(db)
            print(f"都道府県 {count} 件を投入しました")
            return

        if args.command == "status":
            print_status(db)
            return

        if args.command == "plan":
            codes = _resolve_municipality_codes(db, args.prefecture, args.city)
            if not codes and args.prefecture:
                print(
                    "市区町村マスタが空です。先に seed-prefectures → sync-municipalities を実行してください。"
                )
                return
            if not codes and not args.prefecture and not args.city:
                print("--prefecture または --city を指定してください")
                return
            print(
                estimate_transaction_requests(
                    len(codes),
                    args.from_year,
                    args.to_year,
                    sleep_seconds=args.sleep,
                )
            )
            return

        if args.command == "plan-land-prices":
            estimate = count_land_price_requests(
                args.from_year,
                args.to_year,
                args.prefecture,
                zoom=args.zoom,
                skip_empty_tiles=not args.no_skip_empty_tiles,
                reference_year=args.reference_year,
            )
            estimate["estimated_seconds"] = int(
                estimate["total_requests"] * args.sleep
            )
            estimate["estimated_hours"] = round(
                estimate["total_requests"] * args.sleep / 3600,
                1,
            )
            print(estimate)
            return

        api_key = getattr(args, "api_key", None)
        if args.command in (
            "sync-municipalities",
            "sync-transactions",
            "sync-land-prices",
            "sync-stations",
        ) and not api_key:
            raise SystemExit("REINFOLIB_API_KEY を .env に設定してください")

        if args.command == "sync-municipalities":
            client = ReinfolibClient(api_key=api_key)
            stats = sync_municipalities(db, client)
            print(stats)

        elif args.command == "sync-transactions":
            codes = _resolve_municipality_codes(db, args.prefecture, args.city)
            if not codes:
                raise SystemExit(
                    "対象市区町村がありません。先に sync-municipalities を実行してください。"
                )
            client = ReinfolibClient(api_key=api_key, sleep_seconds=args.sleep)
            stats = sync_transactions(
                db,
                client,
                municipality_codes=codes,
                from_year=args.from_year,
                to_year=args.to_year,
                prefecture_code=args.prefecture,
                skip_done=not args.force,
            )
            print(stats)

        elif args.command == "sync-land-prices":
            client = ReinfolibClient(api_key=api_key, sleep_seconds=args.sleep)
            stats = sync_land_prices(
                db,
                client,
                from_year=args.from_year,
                to_year=args.to_year,
                prefecture_code=args.prefecture,
                zoom=args.zoom,
                skip_done=not args.force,
                skip_empty_tiles=not args.no_skip_empty_tiles,
                reference_year=args.reference_year,
            )
            print(stats)

        elif args.command == "sync-stations":
            client = ReinfolibClient(api_key=api_key, sleep_seconds=args.sleep)
            stats = sync_station_passengers(
                db,
                client,
                prefecture_code=args.prefecture,
                zoom=args.zoom,
                skip_done=not args.force,
                workers=max(1, args.workers),
                api_key=api_key,
                sleep_seconds=args.sleep,
            )
            print(stats)

        elif args.command == "rebuild-stats":
            stat_result = rebuild_trade_stats(db, args.city)
            meta_result = rebuild_page_meta(db, args.city)
            print({**stat_result, **meta_result})

        elif args.command == "import-listings":
            result = import_listings_csv(db, args.csv)
            if not args.no_rebuild:
                result.update(rebuild_listing_stats(db))
            print(result)

        elif args.command == "rebuild-listing-stats":
            print(rebuild_listing_stats(db, args.city))

        elif args.command == "retry-failed":
            failed_rows = db.scalars(
                select(SyncCheckpoint).where(
                    SyncCheckpoint.status == "failed",
                    SyncCheckpoint.sync_type == args.sync_type,
                )
            ).all()
            print(f"failed checkpoints ({args.sync_type}): {len(failed_rows)}")
            if args.dry_run or not failed_rows:
                return
            if not args.api_key:
                raise SystemExit("REINFOLIB_API_KEY を .env に設定してください")
            client = ReinfolibClient(api_key=args.api_key, sleep_seconds=args.sleep)
            if args.sync_type == "transactions":
                codes = sorted({r.municipality_code for r in failed_rows if r.municipality_code})
                years = sorted({r.trade_year for r in failed_rows if r.trade_year})
                from_year = min(years) if years else 2005
                to_year = max(years) if years else 2025
                stats = sync_transactions(
                    db,
                    client,
                    municipality_codes=codes,
                    from_year=from_year,
                    to_year=to_year,
                    skip_done=False,
                )
                print(stats)
            else:
                years = sorted({r.trade_year for r in failed_rows if r.trade_year})
                stats = sync_land_prices(
                    db,
                    client,
                    from_year=min(years) if years else 1995,
                    to_year=max(years) if years else 2025,
                    skip_done=False,
                )
                print(stats)

    finally:
        db.close()


if __name__ == "__main__":
    main()
