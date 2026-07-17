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
CNAME_DOMAIN = os.environ.get("GITHUB_PAGES_CNAME", "fudosan-database.jp").strip()

# コア（常に生成）。地区・駅は --full のみ（数万ページ）。
CORE_PATHS = {
    "/",
    "/market",
    "/rankings",
    "/rankings/price",
    "/rankings/price-growth",
    "/rankings/land-price",
    "/rankings/land-price-growth",
    "/rankings/avg-rent",
    "/rankings/population-growth",
    "/rankings/population-density",
    "/rankings/elderly",
    "/rankings/low-vacancy",
    "/rankings/owner-occupied",
    "/rankings/single-household",
    "/news",
    "/compare",
    "/compare/tokyo/shibuya-ku/vs/tokyo/minato-ku",
    "/compare/tokyo/shinjuku-ku/vs/tokyo/chiyoda-ku",
    "/compare/kanagawa/naka-ku/vs/kanagawa/nishi-ku",
    "/compare/osaka/kita-ku/vs/aichi/naka-ku",
    "/compare/fukuoka/chuuou-ku/vs/fukuoka/fukuoka-shi",
    "/for-agents",
    "/search",
    "/estimate",
}


def _configure_env(db_path: Path | None, *, full: bool) -> None:
    os.environ["SITE_URL"] = SITE_URL
    os.environ["PURCHASE_INSIGHTS_USE_CACHE"] = "1"
    os.environ["STATIC_BUILD"] = "1"
    # 地区・駅ページを静的生成するときだけ、テンプレから深いリンクを出す
    os.environ["STATIC_PUBLISH_DEEP_PAGES"] = "1" if full else "0"
    if db_path and db_path.exists():
        os.environ["DATABASE_URL"] = f"sqlite:///{db_path.resolve()}"
    else:
        os.environ.setdefault(
            "DATABASE_URL", f"sqlite:///{(ROOT / 'data' / 'reinfolib.db').resolve()}"
        )


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


def _is_district_path(path: str) -> bool:
    return path.startswith("/price/") and "/area/" in path


def _is_station_path(path: str) -> bool:
    return path.startswith("/station/")


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

        all_paths = [
            loc.replace(SITE_URL, "") or "/"
            for loc, *_ in build_sitemap_entries(db, SITE_URL, include_deep=full)
        ]
        if full:
            return sorted(set(all_paths) | CORE_PATHS)

        selected: set[str] = set(CORE_PATHS)
        for path in all_paths:
            if _is_district_path(path) or _is_station_path(path):
                continue
            if path.startswith("/price/"):
                # 都道府県・市区町村のみ（/area/ は除外済み）
                selected.add(path)
            elif path.startswith("/news/area/"):
                # 都道府県・市区町村ニュース（地区・駅以外は含める）
                selected.add(path)
        return sorted(selected)
    finally:
        db.close()


def _changefreq_priority(path: str) -> tuple[str, str]:
    if path == "/":
        return "daily", "1.0"
    if path.startswith("/rankings"):
        return "daily", "0.9"
    if path.startswith("/news"):
        return "hourly", "0.7"
    if _is_district_path(path):
        return "weekly", "0.6"
    if _is_station_path(path):
        return "monthly", "0.5"
    if path.startswith("/price/") and path.count("/") == 2:
        return "weekly", "0.9"
    if path.startswith("/price/"):
        return "weekly", "0.8"
    return "weekly", "0.7"


def _write_sitemap(built_paths: list[str]) -> int:
    """生成に成功したパスだけをサイトマップに載せる（未生成URLの soft 404 を防ぐ）。"""
    sys.path.insert(0, str(BACKEND))
    from app.web.seo import absolute_url, render_sitemap_xml

    unique = sorted({p if p.startswith("/") else f"/{p}" for p in built_paths if p})
    entries = [
        (absolute_url(SITE_URL, path), None, *_changefreq_priority(path))
        for path in unique
    ]

    chunk_size = 2000
    sitemap_dir = OUT / "sitemaps"
    if sitemap_dir.exists():
        shutil.rmtree(sitemap_dir)
    sitemap_dir.mkdir(parents=True, exist_ok=True)

    if len(entries) <= chunk_size:
        (OUT / "sitemap.xml").write_text(render_sitemap_xml(entries), encoding="utf-8")
        return len(entries)

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


def _write_cname() -> None:
    if CNAME_DOMAIN and "." in CNAME_DOMAIN:
        (OUT / "CNAME").write_text(f"{CNAME_DOMAIN}\n", encoding="utf-8")


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


def _write_404(client) -> None:
    """GitHub Pages 用。トップへの偽装ではなく本物の 404 ページを書く。"""
    response = client.get("/__static_build_missing_page__", follow_redirects=False)
    if response.status_code == 404 and response.text and "ページが見つかりません" in response.text:
        (OUT / "404.html").write_text(response.text, encoding="utf-8")
        return
    # フォールバック: テンプレートを直接描画
    sys.path.insert(0, str(BACKEND))
    from app.web.routes import templates
    from app.web.seo import seo_not_found
    from starlette.requests import Request

    scope = {
        "type": "http",
        "asgi": {"version": "3.0"},
        "http_version": "1.1",
        "method": "GET",
        "scheme": "https",
        "path": "/404",
        "raw_path": b"/404",
        "query_string": b"",
        "headers": [],
        "client": ("127.0.0.1", 0),
        "server": ("fudosan-database.jp", 443),
    }
    request = Request(scope)
    html = templates.get_template("404.html").render(
        request=request, seo=seo_not_found(SITE_URL)
    )
    (OUT / "404.html").write_text(html, encoding="utf-8")


def _render_paths_chunk(paths: list[str], env: dict[str, str]) -> list[tuple[str, str]]:
    for key, value in env.items():
        os.environ[key] = value
    sys.path.insert(0, str(BACKEND))
    from starlette.testclient import TestClient
    from app.main import app

    client = TestClient(app, base_url=env["SITE_URL"])
    out: list[tuple[str, str]] = []
    for path in paths:
        response = client.get(path, follow_redirects=True)
        if response.status_code == 200:
            out.append((path, response.text))
    return out


def build(*, full: bool = False, db_path: Path | None = None, jobs: int = 1, resume: bool = False) -> None:
    _configure_env(db_path, full=full)
    sys.path.insert(0, str(BACKEND))

    if resume and OUT.exists():
        OUT.mkdir(parents=True, exist_ok=True)
        (OUT / ".nojekyll").touch()
        if not (OUT / "static").exists():
            shutil.copytree(STATIC_SRC, OUT / "static")
    else:
        if OUT.exists():
            shutil.rmtree(OUT, ignore_errors=True)
            time.sleep(0.5)
            if OUT.exists():
                shutil.rmtree(OUT, ignore_errors=True)
        OUT.mkdir(parents=True, exist_ok=True)
        (OUT / ".nojekyll").touch()
        shutil.copytree(STATIC_SRC, OUT / "static")

    paths = _collect_paths(full=full)
    if resume:
        before = len(paths)
        paths = [p for p in paths if not _path_to_file(p).exists()]
        print(f"Resume: skip {before - len(paths)} existing, {len(paths)} remaining")
    total = len(paths)
    workers = max(1, jobs)
    print(f"Rendering {total} pages (full={full}, jobs={workers})...")

    env = {
        "SITE_URL": SITE_URL,
        "DATABASE_URL": os.environ["DATABASE_URL"],
        "PURCHASE_INSIGHTS_USE_CACHE": "1",
        "STATIC_BUILD": "1",
        "STATIC_PUBLISH_DEEP_PAGES": "1" if full else "0",
    }
    chunk_size = max(1, (total + workers * 32 - 1) // (workers * 32)) if total else 1
    chunks = [paths[i : i + chunk_size] for i in range(0, total, chunk_size)] if paths else []

    ok_paths: list[str] = []
    t0 = time.time()
    processed = 0

    # resume 時は既存 HTML もサイトマップに含める
    if resume and OUT.exists():
        for html_path in OUT.rglob("index.html"):
            rel = html_path.relative_to(OUT)
            if rel == Path("index.html"):
                ok_paths.append("/")
            else:
                ok_paths.append("/" + str(rel.parent).replace("\\", "/"))

    from starlette.testclient import TestClient
    from app.main import app

    client = TestClient(app, base_url=SITE_URL)

    if workers == 1 or total == 0:
        for i, path in enumerate(paths, 1):
            response = client.get(path, follow_redirects=True)
            if response.status_code != 200:
                print(f"  skip {path} ({response.status_code})")
                continue
            target = _path_to_file(path)
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(response.text, encoding="utf-8")
            ok_paths.append(path)
            if i % 100 == 0 or i == total:
                elapsed = time.time() - t0
                rate = i / elapsed if elapsed else 0
                print(f"  {i}/{total} ({len(ok_paths)} ok, {rate:.1f} pages/s)")
    else:
        from concurrent.futures import ProcessPoolExecutor, as_completed

        with ProcessPoolExecutor(max_workers=workers) as pool:
            futures = {
                pool.submit(_render_paths_chunk, chunk, env): len(chunk)
                for chunk in chunks
            }
            for fut in as_completed(futures):
                for path, html in fut.result():
                    target = _path_to_file(path)
                    target.parent.mkdir(parents=True, exist_ok=True)
                    target.write_text(html, encoding="utf-8")
                    ok_paths.append(path)
                processed += futures[fut]
                elapsed = time.time() - t0
                rate = processed / elapsed if elapsed else 0
                print(f"  {processed}/{total} ({len(ok_paths)} ok, {rate:.1f} pages/s)")

    _write_404(client)
    _write_volume_redirect()

    # 存在するコアページは必ずサイトマップへ（部分再生成でも欠落させない）
    for core in CORE_PATHS:
        if _path_to_file(core).exists():
            ok_paths.append(core)

    sitemap_count = _write_sitemap(ok_paths)
    _write_robots()
    _write_cname()
    _write_google_verification_html()
    _sync_seo_sitemap()

    try:
        sys.path.insert(0, str(ROOT / "tools"))
        from build_custom_overlays import build_overlays

        pref_n, muni_n = build_overlays(site_dir=OUT, out_dir=OUT / "static")
        print(f"Simulator overlays: {pref_n} prefectures, {muni_n} municipalities (last 5 years)")
    except Exception as exc:
        print(f"Warning: simulator overlay build skipped ({exc})")

    print(f"Done: {len(set(ok_paths))} HTML files, sitemap {sitemap_count} URLs → {OUT}")
    if not full:
        print(
            "Note: district/station pages are omitted (use --full). "
            "Sitemap lists only generated pages."
        )


def _write_volume_redirect() -> None:
    """静的配信でも /rankings/volume → /rankings を解決する。"""
    target = OUT / "rankings" / "volume" / "index.html"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(
        """<!DOCTYPE html>
<html lang="ja">
<head>
  <meta charset="utf-8">
  <title>取引件数ランキングへ移動</title>
  <link rel="canonical" href="/rankings/">
  <meta http-equiv="refresh" content="0;url=/rankings/">
</head>
<body>
  <p><a href="/rankings/">取引件数ランキングへ</a></p>
</body>
</html>
""",
        encoding="utf-8",
    )


def _sync_seo_sitemap() -> None:
    """リポジトリの seo/sitemap.xml をデプロイ成果物と同期（古い駅URL混入を防ぐ）。"""
    seo_dir = ROOT / "seo"
    seo_dir.mkdir(parents=True, exist_ok=True)
    src = OUT / "sitemap.xml"
    if not src.exists():
        return
    shutil.copy2(src, seo_dir / "sitemap.xml")
    # 分割サイトマップがあればコピー
    src_dir = OUT / "sitemaps"
    dst_dir = seo_dir / "sitemaps"
    if dst_dir.exists():
        shutil.rmtree(dst_dir)
    if src_dir.exists():
        shutil.copytree(src_dir, dst_dir)
    readme = seo_dir / "README.md"
    readme.write_text(
        """# SEO artifacts

`sitemap.xml`（および `sitemaps/`）は `tools/build_public_site.py` 実行時に
`public_site/` の生成結果から同期されます。

- 通常ビルド: 都道府県・市区町村・ニュース・ランキングなど（地区・駅は含まない）
- `--full` ビルド: 地区・駅ページも含む

Search Console には **デプロイ済みの** `https://fudosan-database.jp/sitemap.xml` を登録してください。
手編集しないでください。
""",
        encoding="utf-8",
    )


def main() -> None:
    parser = argparse.ArgumentParser(description="Build static site for GitHub Pages")
    parser.add_argument("--full", action="store_true", help="Render all sitemap URLs (incl. districts/stations)")
    parser.add_argument("--jobs", type=int, default=4, help="Parallel render workers")
    parser.add_argument("--resume", action="store_true", help="Skip existing HTML and keep public_site/")
    parser.add_argument("--db", type=Path, default=ROOT / "data" / "reinfolib.db")
    args = parser.parse_args()
    build(full=args.full, db_path=args.db, jobs=args.jobs, resume=args.resume)


if __name__ == "__main__":
    main()
