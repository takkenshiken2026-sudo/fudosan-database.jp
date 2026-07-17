#!/usr/bin/env python3
"""ローカルの reinfolib.db から地価変動率ランキング（上昇/下落トップ10）を
JSON で出力する。依存なし（標準ライブラリの sqlite3 のみ）。

市区町村・都道府県の両方を出力する。

使い方（リポジトリのルートで、data/reinfolib.db がある状態で）:
    python3 tools/extract_land_price_rankings.py

DBの場所が違う場合:
    python3 tools/extract_land_price_rankings.py /path/to/reinfolib.db
"""
from __future__ import annotations

import json
import sqlite3
import sys
from pathlib import Path

MUNI_MIN_POINTS = 3
PREF_MIN_POINTS = 10
LIMIT = 10


def _pack_muni(entries: list[dict], latest_year: int) -> list[dict]:
    out = []
    for i, e in enumerate(entries):
        out.append(
            {
                "rank": i + 1,
                "name_ja": e["name_ja"],
                "slug": e["slug"],
                "prefecture_name": e["prefecture_name"],
                "prefecture_slug": e["prefecture_slug"],
                "survey_year": latest_year,
                "point_count": int(e["point_count"]),
                "avg_unit_price": round(e["avg_unit_price"])
                if e["avg_unit_price"] is not None
                else None,
                "yoy_change_avg": round(e["yoy_change_avg"], 2),
            }
        )
    return out


def _pack_pref(entries: list[dict], latest_year: int) -> list[dict]:
    out = []
    for i, e in enumerate(entries):
        out.append(
            {
                "rank": i + 1,
                "name_ja": e["name_ja"],
                "slug": e["slug"],
                "survey_year": latest_year,
                "point_count": int(e["point_count"]),
                "avg_unit_price": round(e["avg_unit_price"])
                if e["avg_unit_price"] is not None
                else None,
                "yoy_change_avg": round(e["yoy_change_avg"], 2),
            }
        )
    return out


def main() -> None:
    db_path = Path(sys.argv[1]) if len(sys.argv) > 1 else Path("data/reinfolib.db")
    if not db_path.exists():
        sys.exit(
            f"reinfolib.db が見つかりません: {db_path}\n"
            "リポジトリのルートで実行するか、DBのパスを引数で指定してください。"
        )

    con = sqlite3.connect(str(db_path))
    con.row_factory = sqlite3.Row

    latest_year = con.execute(
        "SELECT MAX(survey_year) FROM land_price_points"
    ).fetchone()[0]
    if latest_year is None:
        sys.exit("land_price_points にデータがありません。")

    muni_rows = con.execute(
        """
        SELECT m.code            AS code,
               m.name_ja         AS name_ja,
               m.slug            AS slug,
               p.name_ja         AS prefecture_name,
               p.slug            AS prefecture_slug,
               COUNT(lp.id)      AS point_count,
               AVG(lp.unit_price) AS avg_unit_price,
               AVG(lp.year_on_year_change_rate) AS yoy_change_avg
        FROM land_price_points lp
        JOIN municipalities m ON m.code = lp.municipality_code
        JOIN prefectures    p ON p.code = m.prefecture_code
        WHERE lp.survey_year = ?
          AND lp.year_on_year_change_rate IS NOT NULL
        GROUP BY m.code
        HAVING COUNT(lp.id) >= ?
        """,
        (latest_year, MUNI_MIN_POINTS),
    ).fetchall()

    pref_rows = con.execute(
        """
        SELECT p.code            AS code,
               p.name_ja         AS name_ja,
               p.slug            AS slug,
               COUNT(lp.id)      AS point_count,
               AVG(lp.unit_price) AS avg_unit_price,
               AVG(lp.year_on_year_change_rate) AS yoy_change_avg
        FROM land_price_points lp
        JOIN prefectures p ON p.code = lp.prefecture_code
        WHERE lp.survey_year = ?
          AND lp.year_on_year_change_rate IS NOT NULL
        GROUP BY p.code
        HAVING COUNT(lp.id) >= ?
        """,
        (latest_year, PREF_MIN_POINTS),
    ).fetchall()
    con.close()

    muni_ranked = [dict(r) for r in muni_rows if r["yoy_change_avg"] is not None]
    pref_ranked = [dict(r) for r in pref_rows if r["yoy_change_avg"] is not None]

    muni_gainers = _pack_muni(
        sorted(muni_ranked, key=lambda e: e["yoy_change_avg"], reverse=True)[:LIMIT],
        latest_year,
    )
    muni_losers = _pack_muni(
        sorted(muni_ranked, key=lambda e: e["yoy_change_avg"])[:LIMIT],
        latest_year,
    )
    pref_gainers = _pack_pref(
        sorted(pref_ranked, key=lambda e: e["yoy_change_avg"], reverse=True)[:LIMIT],
        latest_year,
    )
    pref_losers = _pack_pref(
        sorted(pref_ranked, key=lambda e: e["yoy_change_avg"])[:LIMIT],
        latest_year,
    )

    print(
        json.dumps(
            {
                "survey_year": latest_year,
                "municipalities": {"gainers": muni_gainers, "losers": muni_losers},
                "prefectures": {"gainers": pref_gainers, "losers": pref_losers},
            },
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
