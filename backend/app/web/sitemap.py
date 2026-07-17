from __future__ import annotations

import os
from typing import Optional

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import Municipality, MunicipalityPageMeta, Prefecture, StationPassenger
from app.api.services import POPULAR_COMPARES
from app.reinfolib.district_pages import list_publishable_district_rows
from app.web.seo import absolute_url, format_lastmod


def _should_include_deep(include_deep: Optional[bool]) -> bool:
    """地区・駅は静的ビルド未生成時にサイトマップへ載せない。"""
    if include_deep is not None:
        return include_deep
    static = os.environ.get("STATIC_BUILD", "").strip().lower() in ("1", "true", "yes")
    if not static:
        return True
    return os.environ.get("STATIC_PUBLISH_DEEP_PAGES", "").strip().lower() in (
        "1",
        "true",
        "yes",
    )


def build_sitemap_entries(
    db: Session,
    base: str,
    *,
    include_deep: Optional[bool] = None,
) -> list[tuple[str, Optional[str], str, str]]:
    deep = _should_include_deep(include_deep)
    entries: list[tuple[str, Optional[str], str, str]] = [
        (absolute_url(base, "/"), None, "daily", "1.0"),
        (absolute_url(base, "/market"), None, "weekly", "0.9"),
        (absolute_url(base, "/rankings"), None, "daily", "0.9"),
        (absolute_url(base, "/rankings/price"), None, "daily", "0.8"),
        (absolute_url(base, "/rankings/price-growth"), None, "weekly", "0.8"),
        (absolute_url(base, "/rankings/land-price"), None, "weekly", "0.8"),
        (absolute_url(base, "/rankings/land-price-growth"), None, "weekly", "0.8"),
        (absolute_url(base, "/rankings/avg-rent"), None, "weekly", "0.7"),
        (absolute_url(base, "/rankings/population-growth"), None, "weekly", "0.7"),
        (absolute_url(base, "/rankings/population-density"), None, "weekly", "0.7"),
        (absolute_url(base, "/rankings/elderly"), None, "weekly", "0.7"),
        (absolute_url(base, "/rankings/low-vacancy"), None, "weekly", "0.7"),
        (absolute_url(base, "/rankings/owner-occupied"), None, "weekly", "0.7"),
        (absolute_url(base, "/rankings/single-household"), None, "weekly", "0.7"),
        (absolute_url(base, "/news"), None, "hourly", "0.8"),
        (absolute_url(base, "/compare"), None, "weekly", "0.8"),
        *[
            (
                absolute_url(
                    base,
                    f"/compare/{a_pref}/{a_muni}/vs/{b_pref}/{b_muni}",
                ),
                None,
                "weekly",
                "0.7",
            )
            for a_pref, a_muni, b_pref, b_muni, _a, _b in POPULAR_COMPARES
        ],
        (absolute_url(base, "/for-agents"), None, "monthly", "0.8"),
        (absolute_url(base, "/search"), None, "weekly", "0.6"),
    ]

    prefectures = db.scalars(select(Prefecture).order_by(Prefecture.code)).all()
    for pref in prefectures:
        entries.append(
            (absolute_url(base, f"/price/{pref.slug}"), None, "weekly", "0.9")
        )
        entries.append(
            (absolute_url(base, f"/news/area/{pref.slug}"), None, "hourly", "0.7")
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
        entries.append(
            (
                absolute_url(base, f"/news/area/{pref_slug}/{muni_slug}"),
                format_lastmod(updated_at),
                "hourly",
                "0.6",
            )
        )

    if deep:
        for pref_slug, muni_slug, area_slug, *_ in list_publishable_district_rows(db):
            entries.append(
                (
                    absolute_url(base, f"/price/{pref_slug}/{muni_slug}/area/{area_slug}"),
                    None,
                    "weekly",
                    "0.6",
                )
            )

        station_ids = db.scalars(
            select(StationPassenger.id)
            .where(StationPassenger.latest_passengers.isnot(None))
            .where(StationPassenger.latest_passengers > 0)
            .order_by(StationPassenger.id)
        ).all()
        for station_id in station_ids:
            entries.append(
                (absolute_url(base, f"/station/{station_id}"), None, "monthly", "0.5")
            )

    return entries
