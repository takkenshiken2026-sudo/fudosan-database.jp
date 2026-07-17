#!/usr/bin/env python3
"""市区町村ページの埋め込み JSON から相場シミュレーター用データを生成する。

- estimate-data.json: 市区町村×種別の㎡単価・件数など
- estimate-tx/{prefecture}.json: 町名別の取引事例

集計は直近 SIMULATOR_RECENT_YEARS 年（既定5年）に限定する。
サイトのチャート・推移（yearly_stats / quarterly_chart）はページ側で全期間を表示。
"""
from __future__ import annotations

import argparse
import json
import re
import statistics
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_SITE_DIR = ROOT / "public_site"
DEFAULT_OUT_DIR = DEFAULT_SITE_DIR / "static"

SIMULATOR_RECENT_YEARS = 5

PROPERTY_TYPE_TO_SIM = {
    "中古マンション等": "mansion",
    "宅地(土地と建物)": "house",
    "宅地(土地)": "land",
}

BUILDING_YEAR_RE = re.compile(r"(19|20)\d{2}")


def extract_chart_data(html: str) -> dict:
    marker = "initMunicipalityCharts("
    start = html.index(marker) + len(marker)
    depth = 0
    for i, ch in enumerate(html[start:], start):
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                return json.loads(html[start : i + 1])
    raise ValueError("initMunicipalityCharts JSON not found")


def min_trade_year(data: dict, *, years: int = SIMULATOR_RECENT_YEARS) -> int:
    candidates = [data.get("latest_year") or 0]
    for row in data.get("property_stats") or []:
        if row.get("trade_year"):
            candidates.append(int(row["trade_year"]))
    for row in data.get("recent_transactions") or []:
        if row.get("trade_year"):
            candidates.append(int(row["trade_year"]))
    latest = max(candidates)
    return latest - (years - 1)


def parse_building_year(value: str | None) -> int | None:
    if not value:
        return None
    match = BUILDING_YEAR_RE.search(str(value))
    return int(match.group(0)) if match else None


def pctile(values: list[float], q: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    idx = q * (len(ordered) - 1)
    lo = int(idx)
    frac = idx - lo
    if lo + 1 >= len(ordered):
        return ordered[lo]
    return ordered[lo] * (1 - frac) + ordered[lo + 1] * frac


def weighted_avg(pairs: list[tuple[float | None, int]]) -> float | None:
    usable = [(v, w) for v, w in pairs if v is not None and w > 0]
    if not usable:
        return None
    total_w = sum(w for _, w in usable)
    return sum(v * w for v, w in usable) / total_w


def filter_recent_rows(rows: list[dict], min_year: int) -> list[dict]:
    return [r for r in rows if int(r.get("trade_year") or 0) >= min_year]


def aggregate_type_stats(
    property_stats: list[dict],
    transactions: list[dict],
    *,
    min_year: int,
    now_year: int,
) -> dict[str, dict]:
    stats_rows = filter_recent_rows(property_stats, min_year)
    tx_rows = filter_recent_rows(transactions, min_year)

    by_sim: dict[str, dict] = {}
    grouped: dict[str, list[dict]] = defaultdict(list)
    for row in stats_rows:
        sim_type = PROPERTY_TYPE_TO_SIM.get(row.get("property_type") or "")
        if sim_type:
            grouped[sim_type].append(row)

    for sim_type, rows in grouped.items():
        count = sum(int(r.get("transaction_count") or 0) for r in rows)
        if count <= 0:
            continue
        unit_avg = weighted_avg(
            [(r.get("unit_price_avg"), int(r.get("transaction_count") or 0)) for r in rows]
        )
        price_avg = weighted_avg(
            [(r.get("trade_price_avg"), int(r.get("transaction_count") or 0)) for r in rows]
        )
        area_avg = weighted_avg(
            [(r.get("area_avg"), int(r.get("transaction_count") or 0)) for r in rows]
        )
        if unit_avg is None and price_avg and area_avg and area_avg > 0:
            unit_avg = price_avg / area_avg

        type_txs = [
            tx
            for tx in tx_rows
            if PROPERTY_TYPE_TO_SIM.get(tx.get("property_type") or "") == sim_type
        ]
        unit_prices = [
            tx["unit_price"]
            for tx in type_txs
            if tx.get("unit_price") and tx["unit_price"] > 0
        ]
        if not unit_prices:
            unit_prices = [
                tx["trade_price"] / tx["area"]
                for tx in type_txs
                if tx.get("trade_price") and tx.get("area") and tx["area"] > 0
            ]
        if unit_avg is None and unit_prices:
            unit_avg = statistics.median(unit_prices)

        entry: dict = {
            "u": round(unit_avg) if unit_avg is not None else None,
            "n": count,
            "avg": round(price_avg) if price_avg is not None else None,
        }
        if area_avg is not None:
            entry["a"] = round(area_avg, 1)
        if len(unit_prices) >= 3:
            lo = pctile(unit_prices, 0.25)
            hi = pctile(unit_prices, 0.75)
            if lo is not None and hi is not None:
                entry["lo"] = round(lo)
                entry["hi"] = round(hi)

        ages = []
        for tx in type_txs:
            built = parse_building_year(tx.get("building_year"))
            if built and built <= now_year:
                ages.append(now_year - built)
        if ages:
            entry["g"] = round(statistics.median(ages))

        if entry.get("u") is not None:
            by_sim[sim_type] = {k: v for k, v in entry.items() if v is not None}

    return by_sim


def build_deals(transactions: list[dict], *, min_year: int) -> list[dict]:
    deals: list[dict] = []
    for tx in filter_recent_rows(transactions, min_year):
        sim_type = PROPERTY_TYPE_TO_SIM.get(tx.get("property_type") or "")
        if not sim_type:
            continue
        district = (tx.get("district_name") or "").strip()
        price = tx.get("trade_price")
        area = tx.get("area")
        if not district or not price:
            continue
        deal: dict = {"t": sim_type, "d": district, "p": int(price)}
        if area and area > 0:
            deal["a"] = round(float(area), 1)
        built = parse_building_year(tx.get("building_year"))
        if built:
            deal["y"] = built
        deals.append(deal)
    return deals


def collect_municipality_pages(site_dir: Path) -> list[Path]:
    price_root = site_dir / "price"
    if not price_root.exists():
        return []
    pages: list[Path] = []
    for pref_dir in sorted(price_root.iterdir()):
        if not pref_dir.is_dir():
            continue
        for muni_dir in sorted(pref_dir.iterdir()):
            if not muni_dir.is_dir() or muni_dir.name == "area":
                continue
            page = muni_dir / "index.html"
            if page.exists():
                pages.append(page)
    return pages


def build_overlays(
    *,
    site_dir: Path = DEFAULT_SITE_DIR,
    out_dir: Path = DEFAULT_OUT_DIR,
    recent_years: int = SIMULATOR_RECENT_YEARS,
) -> tuple[int, int]:
    pages = collect_municipality_pages(site_dir)
    if not pages:
        raise SystemExit(f"No municipality pages under {site_dir / 'price'}")

    prefectures: dict[str, dict] = {}
    tx_by_pref: dict[str, dict[str, list[dict]]] = defaultdict(lambda: defaultdict(list))
    now_year = 0

    for page in pages:
        pref_slug = page.parent.parent.name
        muni_slug = page.parent.name
        try:
            data = extract_chart_data(page.read_text(encoding="utf-8"))
        except (ValueError, json.JSONDecodeError, OSError) as exc:
            print(f"  skip {page.relative_to(site_dir)} ({exc})")
            continue

        latest = data.get("latest_year") or 0
        now_year = max(now_year, int(latest))
        min_year = min_trade_year(data, years=recent_years)

        type_stats = aggregate_type_stats(
            data.get("property_stats") or [],
            data.get("recent_transactions") or [],
            min_year=min_year,
            now_year=now_year or min_year + recent_years - 1,
        )
        if not type_stats:
            continue

        pref = prefectures.setdefault(
            pref_slug,
            {
                "slug": pref_slug,
                "name": data.get("prefecture_name") or pref_slug,
                "m": [],
            },
        )
        pref["m"].append(
            {
                "slug": muni_slug,
                "name": data.get("name_ja") or muni_slug,
                "t": type_stats,
            }
        )

        deals = build_deals(data.get("recent_transactions") or [], min_year=min_year)
        if deals:
            tx_by_pref[pref_slug][muni_slug].extend(deals)

    if not prefectures:
        raise SystemExit("No municipality overlay data produced")

    out_dir.mkdir(parents=True, exist_ok=True)
    estimate_data = {
        "now": now_year,
        "prefectures": sorted(prefectures.values(), key=lambda p: p["slug"]),
    }
    for pref in estimate_data["prefectures"]:
        pref["m"].sort(key=lambda m: m["slug"])

    (out_dir / "estimate-data.json").write_text(
        json.dumps(estimate_data, ensure_ascii=False, separators=(",", ":")),
        encoding="utf-8",
    )

    tx_dir = out_dir / "estimate-tx"
    tx_dir.mkdir(parents=True, exist_ok=True)
    for pref_slug, munis in sorted(tx_by_pref.items()):
        compact = {slug: deals for slug, deals in sorted(munis.items()) if deals}
        if compact:
            (tx_dir / f"{pref_slug}.json").write_text(
                json.dumps(compact, ensure_ascii=False, separators=(",", ":")),
                encoding="utf-8",
            )

    return len(estimate_data["prefectures"]), sum(len(m["m"]) for m in estimate_data["prefectures"])


def main() -> None:
    parser = argparse.ArgumentParser(description="Build estimate simulator overlay JSON")
    parser.add_argument(
        "--site-dir",
        type=Path,
        default=DEFAULT_SITE_DIR,
        help="Static site root (default: public_site/)",
    )
    parser.add_argument(
        "--out-dir",
        type=Path,
        default=None,
        help="Output directory (default: <site-dir>/static/)",
    )
    parser.add_argument(
        "--years",
        type=int,
        default=SIMULATOR_RECENT_YEARS,
        help=f"Recent years window for simulator (default: {SIMULATOR_RECENT_YEARS})",
    )
    args = parser.parse_args()
    out_dir = args.out_dir or (args.site_dir / "static")
    pref_n, muni_n = build_overlays(
        site_dir=args.site_dir,
        out_dir=out_dir,
        recent_years=args.years,
    )
    print(
        f"Done: estimate-data.json + estimate-tx/ "
        f"({pref_n} prefectures, {muni_n} municipalities, last {args.years} years) → {out_dir}"
    )


if __name__ == "__main__":
    main()
