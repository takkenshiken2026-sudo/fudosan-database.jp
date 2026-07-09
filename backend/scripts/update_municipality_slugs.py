#!/usr/bin/env python3
"""市区町村 slug をローマ字化（例: 渋谷区 → shibuya-ku）"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import select

from app.db import Municipality, SessionLocal, init_db
from app.utils.slugify import dedupe_slug, municipality_slug


def main() -> None:
    init_db()
    db = SessionLocal()
    try:
        municipalities = db.scalars(select(Municipality).order_by(Municipality.code)).all()
        used: dict[str, set[str]] = {}
        updated = 0

        for muni in municipalities:
            pref = muni.prefecture_code
            used.setdefault(pref, set())
            base_slug = municipality_slug(muni.name_ja, muni.code)
            slug = base_slug
            if slug in used[pref]:
                slug = dedupe_slug(f"{base_slug}-{muni.code}", muni.code)
            used[pref].add(slug)

            if muni.slug != slug:
                print(f"{muni.code} {muni.name_ja}: {muni.slug} → {slug}")
                muni.slug = slug
                updated += 1

        db.commit()
        print(f"完了: {updated} 件更新 / {len(municipalities)} 件")
    finally:
        db.close()


if __name__ == "__main__":
    main()
