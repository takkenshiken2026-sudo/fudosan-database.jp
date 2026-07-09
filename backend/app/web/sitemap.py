from __future__ import annotations

from typing import Optional

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import Municipality, MunicipalityPageMeta, Prefecture
from app.web.seo import absolute_url, format_lastmod, render_sitemap_xml


def build_sitemap_entries(db: Session, base: str) -> list[tuple[str, Optional[str], str, str]]:
    entries: list[tuple[str, Optional[str], str, str]] = [
        (absolute_url(base, "/"), None, "daily", "1.0"),
        (absolute_url(base, "/rankings"), None, "daily", "0.9"),
        (absolute_url(base, "/news"), None, "hourly", "0.8"),
        (absolute_url(base, "/compare"), None, "weekly", "0.8"),
        (absolute_url(base, "/for-agents"), None, "monthly", "0.8"),
        (absolute_url(base, "/search"), None, "weekly", "0.6"),
    ]

    prefectures = db.scalars(select(Prefecture).order_by(Prefecture.code)).all()
    for pref in prefectures:
        entries.append(
            (absolute_url(base, f"/price/{pref.slug}"), None, "weekly", "0.9")
        )

    rows = db.execute(
        select(
            Municipality.slug,
            Prefecture.slug,
            MunicipalityPageMeta.stats_updated_at,
        )
        .join(Prefecture, Prefecture.code == Municipality.prefecture_code)
        .outerjoin(
            MunicipalityPageMeta,
            MunicipalityPageMeta.municipality_code == Municipality.code,
        )
        .order_by(Municipality.code)
    ).all()

    for muni_slug, pref_slug, updated_at in rows:
        entries.append(
            (
                absolute_url(base, f"/price/{pref_slug}/{muni_slug}"),
                format_lastmod(updated_at),
                "weekly",
                "0.8",
            )
        )

    return entries
