#!/usr/bin/env python3
"""全市区町村の購入参考データを並列で事前計算しキャッシュする。"""
from __future__ import annotations

import argparse
import os
import sys
import time
from concurrent.futures import ProcessPoolExecutor, as_completed
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
DB_DEFAULT = ROOT / "data" / "reinfolib.db"


def _configure(db_path: Path) -> str:
    os.environ["DATABASE_URL"] = f"sqlite:///{db_path.resolve()}"
    return os.environ["DATABASE_URL"]


def _collect_jobs(db_path: str) -> list[tuple[str, int | None, float | None]]:
    sys.path.insert(0, str(BACKEND))
    from sqlalchemy import select

    from app.api.services import get_land_price_summary
    from app.db import Municipality, MunicipalityPageMeta, SessionLocal, init_db

    init_db()
    db = SessionLocal()
    try:
        rows = db.execute(
            select(
                Municipality.code,
                MunicipalityPageMeta.latest_year,
            )
            .outerjoin(
                MunicipalityPageMeta,
                MunicipalityPageMeta.municipality_code == Municipality.code,
            )
            .order_by(Municipality.code)
        ).all()
        jobs: list[tuple[str, int | None, float | None]] = []
        for code, latest_year in rows:
            land = get_land_price_summary(db, code)
            land_avg = (
                float(land.avg_unit_price)
                if land and land.avg_unit_price
                else None
            )
            jobs.append((code, latest_year, land_avg))
        return jobs
    finally:
        db.close()


def _compute_batch(batch: list[tuple[str, int | None, float | None]], db_path: str) -> dict:
    sys.path.insert(0, str(BACKEND))
    os.environ["DATABASE_URL"] = db_path
    os.environ.pop("PURCHASE_INSIGHTS_USE_CACHE", None)

    from app.db import SessionLocal, init_db
    from app.reinfolib.purchase_insights import get_purchase_insights

    init_db()
    db = SessionLocal()
    out: dict = {}
    try:
        for code, latest_year, land_avg in batch:
            insights = get_purchase_insights(
                db,
                code,
                latest_year=latest_year,
                land_price_avg=land_avg,
            )
            out[code] = insights.model_dump()
    finally:
        db.close()
    return out


def prewarm(*, db_path: Path, jobs: int, batch_size: int) -> int:
    db_url = _configure(db_path)
    jobs_list = _collect_jobs(db_url)
    total = len(jobs_list)
    print(f"Prewarming purchase insights for {total} municipalities (jobs={jobs})...")

    cache_path = ROOT / "data" / "purchase_insights_cache.json"

    batches = [
        jobs_list[i : i + batch_size]
        for i in range(0, total, batch_size)
    ]
    store: dict = {}
    t0 = time.time()
    done = 0

    with ProcessPoolExecutor(max_workers=jobs) as pool:
        futures = {
            pool.submit(_compute_batch, batch, db_url): len(batch)
            for batch in batches
        }
        for fut in as_completed(futures):
            store.update(fut.result())
            done += futures[fut]
            elapsed = time.time() - t0
            rate = done / elapsed if elapsed else 0
            print(f"  {done}/{total} ({rate:.1f} muni/s)")
            if done % 200 == 0 or done == total:
                cache_path.parent.mkdir(parents=True, exist_ok=True)
                import json

                cache_path.write_text(
                    json.dumps(store, ensure_ascii=False), encoding="utf-8"
                )

    import json

    cache_path.write_text(json.dumps(store, ensure_ascii=False), encoding="utf-8")
    print(f"Cache written: {cache_path} ({len(store)} entries)")
    return len(store)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--db", type=Path, default=DB_DEFAULT)
    parser.add_argument("--jobs", type=int, default=4)
    parser.add_argument("--batch-size", type=int, default=20)
    args = parser.parse_args()
    prewarm(db_path=args.db, jobs=args.jobs, batch_size=args.batch_size)


if __name__ == "__main__":
    main()
