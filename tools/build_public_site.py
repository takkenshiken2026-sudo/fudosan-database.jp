#!/usr/bin/env python3
"""GitHub Pages 用に FastAPI SSR ページを public_site/ に静的出力する。"""
from __future__ import annotations

import argparse
import os
import shutil
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "public_site"
BACKEND = ROOT / "backend"
STATIC_SRC = BACKEND / "app" / "web" / "static"
SITE_URL = os.environ.get("SITE_URL", "https://fudosan-database.jp").rstrip("/")


def _configure_env(db_path: Path | None) -> None:
    os.environ["SITE_URL"] = SITE_URL
    if db_path and db_path.exists():
        os.environ["DATABASE_URL"] = f"sqlite:///{db_path.resolve()}"
    else:
        os.environ.setdefault("DATABASE_URL", f"sqlite:///{(ROOT / 'data' / 'reinfolib.db').resolve()}")


def _path_to_file(path: str) -> Path:
    if path in ("", "/"):
        return OUT / "index.html"
    clean = path.strip("/")
    return OUT / clean / "index.html"


def _write_google_verification_html() -> None:
    filename = os.environ.get("GOOGLE_SITE_VERIFICATION_FILE", "").strip()
    if not filename:
        filename = os.environ.get("GOOGLE_SITE_VERIFICATION_HTML", "").strip()
    if not filename or ".." in filename or "/" in filename:
        return
    token = filename.removesuffix(".html")
    (OUT / filename).write_text(f"google-site-verification: {token}.html\n", encoding="utf-8")


def _collect_paths(full: bool) -> list[str]:
    sys.path.insert(0, str(BACKEND))
    from app.db import SessionLocal, init_db
    from app.reinfolib.sync import seed_prefectures
    from app.web.sitemap import build_sitemap_entries

    init_db()
    db = SessionLocal()
    try:
        from sqlalchemy import func, select
        from app.db import Prefecture

        if not db.scalar(select(func.count(Prefecture.code))):
            seed_prefectures(db)
            db.commit()

        paths = [loc.replace(SITE_URL, "") or "/" for loc, *_ in build_sitemap_entries(db, SITE_URL)]
        if full:
            return paths

        core = {
            "/",
            "/market",
            "/rankings",
            "/news",
            "/compare",
            "/for-agents",
            "/search",
        }
        for path in paths:
            if path.startswith("/price/"):
                core.add(path)
            elif path.startswith("/news/area/") and path.count("/") == 3:
                core.add(path)
        return sorted(core)
    finally:
        db.close()


def _write_sitemap() -> int:
    sys.path.insert(0, str(BACKEND))
    from app.db import SessionLocal
    from app.web.seo import render_sitemap_xml
    from app.web.sitemap import build_sitemap_entries

    committed = ROOT / "seo" / "sitemap.xml"
    db = SessionLocal()
    try:
        entries = build_sitemap_entries(db, SITE_URL)
        if len(entries) < 200 and committed.exists():
            xml = committed.read_text(encoding="utf-8")
            (OUT / "sitemap.xml").write_text(xml, encoding="utf-8")
            return xml.count("<url>")

        chunk_size = 2000
        sitemap_dir = OUT / "sitemaps"
        sitemap_dir.mkdir(parents=True, exist_ok=True)
        sitemap_urls: list[str] = []
        for i in range(0, len(entries), chunk_size):
            chunk = entries[i : i + chunk_size]
            name = f"sitemap-{i // chunk_size + 1}.xml"
            (sitemap_dir / name).write_text(render_sitemap_xml(chunk), encoding="utf-8")
            sitemap_urls.append(f"{SITE_URL}/sitemaps/{name}")

        index_lines = [
            '<?xml version="1.0" encoding="UTF-8"?>',
            '<sitemapindex xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">',
        ]
        for url in sitemap_urls:
            index_lines.append("  <sitemap>")
            index_lines.append(f"    <loc>{url}</loc>")
            index_lines.append("  </sitemap>")
        index_lines.append("</sitemapindex>")
        (OUT / "sitemap.xml").write_text("\n".join(index_lines), encoding="utf-8")
        return len(entries)
    finally:
        db.close()


def _write_robots() -> None:
    (OUT / "robots.txt").write_text(
        f"""User-agent: *
Allow: /
Disallow: /api/
Disallow: /report/

Sitemap: {SITE_URL}/sitemap.xml
""",
        encoding="utf-8",
    )


def build(*, full: bool = False, db_path: Path | None = None) -> None:
    _configure_env(db_path)
    sys.path.insert(0, str(BACKEND))

    if OUT.exists():
        shutil.rmtree(OUT, ignore_errors=True)
        time.sleep(0.5)
        if OUT.exists():
            shutil.rmtree(OUT, ignore_errors=True)
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / ".nojekyll").touch()
    shutil.copytree(STATIC_SRC, OUT / "static")

    from starlette.testclient import TestClient
    from app.main import app

    client = TestClient(app, base_url=SITE_URL)
    paths = _collect_paths(full=full)
    total = len(paths)
    print(f"Rendering {total} pages (full={full})...")

    ok = 0
    t0 = time.time()
    for i, path in enumerate(paths, 1):
        response = client.get(path, follow_redirects=True)
        if response.status_code != 200:
            print(f"  skip {path} ({response.status_code})")
            continue
        target = _path_to_file(path)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(response.text, encoding="utf-8")
        ok += 1
        if i % 100 == 0 or i == total:
            elapsed = time.time() - t0
            rate = i / elapsed if elapsed else 0
            print(f"  {i}/{total} ({ok} ok, {rate:.1f} pages/s)")

    sitemap_count = _write_sitemap()
    _write_robots()
    _write_google_verification_html()

    # GitHub Pages: 存在しないパスはトップへ（段階的ビルド時のフォールバック）
    if not full:
        (OUT / "404.html").write_text((OUT / "index.html").read_text(encoding="utf-8"), encoding="utf-8")

    print(f"Done: {ok} HTML files, sitemap {sitemap_count} URLs → {OUT}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Build static site for GitHub Pages")
    parser.add_argument("--full", action="store_true", help="Render all sitemap URLs")
    parser.add_argument("--db", type=Path, default=ROOT / "data" / "reinfolib.db")
    args = parser.parse_args()
    build(full=args.full, db_path=args.db)


if __name__ == "__main__":
    main()
