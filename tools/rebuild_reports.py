#!/usr/bin/env python3
"""レポートページ（/report/{pref}/{muni}）だけを既存 public_site に再生成する。

全ページの再ビルド（数十分）をせずに、レポート関連（テンプレート・生成JS・
埋め込みデータ）の変更だけを数分で反映するための軽量スクリプト。
既存の public_site/ を土台に、レポートHTMLと static/ のみ差し替える。
その後 scripts/deploy-reports.sh が gh-pages へ push する。

前提: 一度 scripts/deploy-gh-pages.sh --full でフルビルド済み（public_site が揃っている）。
"""
from __future__ import annotations

import argparse
import os
import shutil
import sys
import time
from concurrent.futures import ProcessPoolExecutor, as_completed
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
import build_public_site as B  # 既存のビルド機構を再利用


def _report_paths(db) -> list[str]:
    """市区町村相場ページ（/price/{pref}/{muni}）から /report/... を導出する。"""
    from app.web.sitemap import build_sitemap_entries

    all_paths = [
        loc.replace(B.SITE_URL, "") or "/"
        for loc, *_ in build_sitemap_entries(db, B.SITE_URL, include_deep=False)
    ]
    out = set()
    for p in all_paths:
        if p.startswith("/price/") and "/area/" not in p and p.count("/") == 3:
            out.add(p.replace("/price/", "/report/", 1))
    return sorted(out)


def _render_chunk(paths: list[str], env: dict[str, str]) -> list[tuple[str, str]]:
    for key, value in env.items():
        os.environ[key] = value
    sys.path.insert(0, str(B.BACKEND))
    from starlette.testclient import TestClient
    from app.main import app

    client = TestClient(app, base_url=env["SITE_URL"])
    out: list[tuple[str, str]] = []
    for path in paths:
        response = client.get(path, follow_redirects=True)
        if response.status_code == 200:
            out.append((path, response.text))
    return out


def main() -> None:
    parser = argparse.ArgumentParser(description="Rebuild only /report/ pages into existing public_site")
    parser.add_argument("--jobs", type=int, default=4)
    parser.add_argument("--db", type=Path, default=ROOT / "data" / "reinfolib.db")
    args = parser.parse_args()

    if not (B.OUT / "index.html").exists():
        sys.exit(
            "ABORT: public_site が空です。先に一度 scripts/deploy-gh-pages.sh --full を実行してください。"
        )

    B._configure_env(args.db, full=True)
    sys.path.insert(0, str(B.BACKEND))

    # static/ を最新化（report-export.js などを差し替え）
    dst = B.OUT / "static"
    if dst.exists():
        shutil.rmtree(dst)
    shutil.copytree(B.STATIC_SRC, dst)

    from app.db import SessionLocal, init_db

    init_db()
    db = SessionLocal()
    try:
        paths = _report_paths(db)
    finally:
        db.close()

    total = len(paths)
    print(f"Rebuilding {total} report pages (jobs={args.jobs})...")

    env = {
        "SITE_URL": B.SITE_URL,
        "DATABASE_URL": os.environ["DATABASE_URL"],
        "PURCHASE_INSIGHTS_USE_CACHE": "1",
        "STATIC_BUILD": "1",
        "STATIC_PUBLISH_DEEP_PAGES": "1",
    }
    workers = max(1, args.jobs)
    chunk_size = max(1, (total + workers * 4 - 1) // (workers * 4))
    chunks = [paths[i : i + chunk_size] for i in range(0, total, chunk_size)]

    ok = 0
    processed = 0
    t0 = time.time()
    with ProcessPoolExecutor(max_workers=workers) as pool:
        futures = {pool.submit(_render_chunk, chunk, env): len(chunk) for chunk in chunks}
        for fut in as_completed(futures):
            for path, html in fut.result():
                target = B._path_to_file(path)
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_text(html, encoding="utf-8")
                ok += 1
            processed += futures[fut]
            elapsed = time.time() - t0
            rate = ok / elapsed if elapsed else 0
            print(f"  {processed}/{total} ({ok} ok, {rate:.0f}/s)")

    print(f"Done: {ok} report pages updated → {B.OUT}")


if __name__ == "__main__":
    main()
