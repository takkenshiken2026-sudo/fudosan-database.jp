from __future__ import annotations

import json
import os
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import HTMLResponse, PlainTextResponse, RedirectResponse, Response
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.api import services
from app.config import settings
from app.db import get_db
from app.reinfolib.district_pages import get_district_detail, resolve_district
from app.news.regional import get_regional_news
from app.news.service import get_news_feed
from app.web.pdf import html_to_pdf
from app.web.formatters import (
    format_count,
    format_man_yen,
    format_news_datetime,
    format_passengers_daily,
    format_percent,
    format_yen_per_sqm,
    quarter_label,
)
from app.web.seo import (
    seo_compare,
    seo_district,
    seo_estimate,
    seo_for_agents,
    seo_home,
    seo_market,
    seo_municipality,
    seo_news,
    seo_not_found,
    seo_prefecture,
    seo_rankings,
    seo_regional_news,
    seo_report_new,
    seo_report_preview,
    seo_search,
    seo_station,
    site_base_url,
)
from app.web.sitemap import build_sitemap_entries

TEMPLATES_DIR = Path(__file__).resolve().parent / "templates"
templates = Jinja2Templates(directory=str(TEMPLATES_DIR))
templates.env.filters["tojson"] = lambda value: json.dumps(
    value, ensure_ascii=False, default=str
)


def publish_deep_pages() -> bool:
    """静的ビルドで地区・駅を未生成のとき、壊れたリンクを出さない。"""
    static = os.environ.get("STATIC_BUILD", "").strip().lower() in ("1", "true", "yes")
    if not static:
        return True
    return os.environ.get("STATIC_PUBLISH_DEEP_PAGES", "").strip().lower() in (
        "1",
        "true",
        "yes",
    )


templates.env.globals.update(
    {
        "format_man_yen": format_man_yen,
        "format_count": format_count,
        "format_yen_per_sqm": format_yen_per_sqm,
        "format_percent": format_percent,
        "format_news_datetime": format_news_datetime,
        "format_passengers_daily": format_passengers_daily,
        "quarter_label": quarter_label,
        "google_site_verification": settings.google_site_verification,
        "publish_deep_pages": publish_deep_pages,
    }
)

router = APIRouter(tags=["web"])


def _base(request: Request) -> str:
    return site_base_url(str(request.base_url))


def _render(request: Request, template: str, seo, **context) -> HTMLResponse:
    return templates.TemplateResponse(
        request,
        template,
        {"seo": seo, **context},
    )


@router.get("/robots.txt", response_class=PlainTextResponse)
def robots_txt(request: Request) -> str:
    base = _base(request)
    return f"""User-agent: *
Allow: /
Disallow: /api/
Disallow: /report/

Sitemap: {base}/sitemap.xml
"""


@router.get("/google{token}.html", response_class=PlainTextResponse)
def google_verification_file(token: str) -> str:
    filename = f"google{token}.html"
    if not settings.google_site_verification_file or filename != settings.google_site_verification_file:
        raise HTTPException(status_code=404, detail="Not found")
    return f"google-site-verification: {filename}"


@router.get("/sitemap.xml")
def sitemap_xml(request: Request, db: Session = Depends(get_db)) -> Response:
    from app.web.seo import render_sitemap_xml

    base = _base(request)
    entries = build_sitemap_entries(db, base)
    body = render_sitemap_xml(entries)
    return Response(content=body, media_type="application/xml; charset=utf-8")


@router.get("/", response_class=HTMLResponse)
def home(request: Request, db: Session = Depends(get_db)) -> HTMLResponse:
    highlights = services.get_home_highlights(db)
    prefectures = services.list_prefectures(db)
    chart_data = services.get_home_chart_data(db)
    prefecture_map_data = [
        {
            "code": p.code,
            "slug": p.slug,
            "name_ja": p.name_ja,
            "total_transactions": p.total_transactions,
            "avg_price": p.avg_price,
        }
        for p in prefectures
    ]
    return _render(
        request,
        "index.html",
        seo_home(_base(request)),
        highlights=highlights,
        prefectures=prefectures,
        prefecture_map_data=prefecture_map_data,
        chart_data=chart_data.model_dump(),
        popular_areas=services.POPULAR_AREAS,
        popular_compares=services.POPULAR_COMPARES,
    )


@router.get("/market", response_class=HTMLResponse)
def market_page(request: Request, db: Session = Depends(get_db)) -> HTMLResponse:
    chart_data = services.get_home_chart_data(db)
    return _render(
        request,
        "market.html",
        seo_market(_base(request)),
        chart_data=chart_data.model_dump(),
    )


@router.get("/estimate", response_class=HTMLResponse)
def estimate_page(request: Request) -> HTMLResponse:
    return _render(request, "estimate.html", seo_estimate(_base(request)))


@router.get("/search", response_class=HTMLResponse)
def search_page(
    request: Request, q: str = "", db: Session = Depends(get_db)
) -> HTMLResponse:
    results = services.search_municipalities(db, q, limit=30) if q.strip() else []
    districts = services.search_districts(db, q, limit=15) if q.strip() else []
    stations = services.search_stations(db, q, limit=15) if q.strip() else []
    return _render(
        request,
        "search.html",
        seo_search(_base(request), q, len(results)),
        query=q,
        results=results,
        districts=districts,
        stations=stations,
    )


@router.get("/news", response_class=HTMLResponse)
def news_page(
    request: Request, category: str = "", db: Session = Depends(get_db)
) -> HTMLResponse:
    feed = get_news_feed(per_category=12)
    active = category if category else ""
    prefectures = services.list_prefectures(db)
    return _render(
        request,
        "news.html",
        seo_news(_base(request), active),
        feed=feed,
        active_category=active,
        prefectures=prefectures,
    )


@router.get("/news/area/{prefecture_slug}", response_class=HTMLResponse)
def regional_news_prefecture_page(
    request: Request, prefecture_slug: str, db: Session = Depends(get_db)
) -> HTMLResponse:
    prefecture = services.get_prefecture_by_slug(db, prefecture_slug)
    if not prefecture:
        raise HTTPException(status_code=404, detail="都道府県が見つかりません")
    feed = get_regional_news(prefecture.name_ja, prefecture.slug, limit=12)
    prefectures = services.list_prefectures(db)
    return _render(
        request,
        "news_area.html",
        seo_regional_news(
            _base(request),
            prefecture.name_ja,
            prefecture.slug,
            prefecture_name=prefecture.name_ja,
        ),
        feed=feed,
        prefecture=prefecture,
        municipality=None,
        prefectures=prefectures,
    )


@router.get(
    "/news/area/{prefecture_slug}/{municipality_slug}",
    response_class=HTMLResponse,
)
def regional_news_municipality_page(
    request: Request,
    prefecture_slug: str,
    municipality_slug: str,
    db: Session = Depends(get_db),
) -> HTMLResponse:
    prefecture, municipality = services.resolve_municipality(
        db, prefecture_slug, municipality_slug
    )
    if not prefecture or not municipality:
        raise HTTPException(status_code=404, detail="市区町村が見つかりません")
    area_label = f"{prefecture.name_ja}{municipality.name_ja}"
    feed = get_regional_news(
        prefecture.name_ja,
        prefecture.slug,
        municipality.name_ja,
        municipality.slug,
        limit=12,
    )
    prefectures = services.list_prefectures(db)
    return _render(
        request,
        "news_area.html",
        seo_regional_news(
            _base(request),
            area_label,
            prefecture.slug,
            prefecture_name=prefecture.name_ja,
            municipality_slug=municipality.slug,
            municipality_name=municipality.name_ja,
        ),
        feed=feed,
        prefecture=prefecture,
        municipality=municipality,
        prefectures=prefectures,
    )


@router.get("/rankings", response_class=HTMLResponse)
def rankings_page(
    request: Request, sort: str = "volume", db: Session = Depends(get_db)
) -> HTMLResponse:
    from app.api.value_insights import FEATURE_RANKING_META

    # 旧 ?sort= はパス形式へ（静的配信でも解決できるように）
    if sort in FEATURE_RANKING_META and sort != "volume":
        return RedirectResponse(url=f"/rankings/{sort}", status_code=301)
    return rankings_kind_page(request, kind="volume", db=db)


@router.get("/rankings/volume", response_class=HTMLResponse)
def rankings_volume_redirect() -> RedirectResponse:
    return RedirectResponse(url="/rankings", status_code=301)


@router.get("/rankings/{kind}", response_class=HTMLResponse)
def rankings_kind_page(
    request: Request, kind: str = "volume", db: Session = Depends(get_db)
) -> HTMLResponse:
    from app.api.value_insights import FEATURE_RANKING_META, get_feature_rankings, ranking_tabs

    if kind not in FEATURE_RANKING_META:
        kind = "volume"
    meta = FEATURE_RANKING_META[kind]
    items = get_feature_rankings(db, kind=kind, limit=50)
    return _render(
        request,
        "rankings.html",
        seo_rankings(_base(request), kind, items, title=meta["title"]),
        items=items,
        sort=kind,
        title=meta["title"],
        description=meta["description"],
        metric_label=meta["metric_label"],
        secondary_label="平均地価" if kind == "land-price-growth" else None,
        ranking_tabs=ranking_tabs(),
    )


@router.get("/report/new", response_class=HTMLResponse)
def report_new(request: Request, area: str = "") -> HTMLResponse:
    return _render(
        request,
        "report_new.html",
        seo_report_new(_base(request)),
        default_area=area,
    )


@router.get("/report/preview", response_class=HTMLResponse)
def report_preview(
    request: Request,
    prefecture_slug: str,
    municipality_slug: str,
    report_type: str = "seller",
    period_years: int = 2,
    db: Session = Depends(get_db),
) -> HTMLResponse:
    prefecture, municipality = services.resolve_municipality(
        db, prefecture_slug, municipality_slug
    )
    if not prefecture or not municipality:
        raise HTTPException(status_code=404, detail="市区町村が見つかりません")
    if municipality.slug != municipality_slug and municipality_slug == municipality.code:
        return RedirectResponse(
            url=(
                f"/report/preview?prefecture_slug={prefecture.slug}"
                f"&municipality_slug={municipality.slug}"
                f"&report_type={report_type}&period_years={period_years}"
            ),
            status_code=301,
        )
    detail = services.get_municipality_detail(db, prefecture, municipality)
    report_ctx = services.build_report_context(report_type, period_years)
    return _render(
        request,
        "report_preview.html",
        seo_report_preview(_base(request)),
        detail=detail,
        report=report_ctx,
    )


@router.get("/report/pdf")
def report_pdf(
    request: Request,
    prefecture_slug: str,
    municipality_slug: str,
    report_type: str = "seller",
    period_years: int = 2,
    db: Session = Depends(get_db),
) -> Response:
    prefecture, municipality = services.resolve_municipality(
        db, prefecture_slug, municipality_slug
    )
    if not prefecture or not municipality:
        raise HTTPException(status_code=404, detail="市区町村が見つかりません")
    detail = services.get_municipality_detail(db, prefecture, municipality)
    report_ctx = services.build_report_context(report_type, period_years)
    html = templates.get_template("report_pdf.html").render(
        detail=detail,
        report=report_ctx,
        format_man_yen=format_man_yen,
        format_count=format_count,
        format_yen_per_sqm=format_yen_per_sqm,
        format_percent=format_percent,
        quarter_label=quarter_label,
    )
    pdf_bytes = html_to_pdf(html)
    filename = f"report-{detail.slug}.pdf"
    return Response(
        content=pdf_bytes,
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


class BetaSignupBody(BaseModel):
    email: str


@router.post("/api/beta-signup")
def beta_signup(body: BetaSignupBody) -> dict[str, str]:
    data_dir = Path(__file__).resolve().parents[3] / "data"
    data_dir.mkdir(parents=True, exist_ok=True)
    path = data_dir / "beta_signups.txt"
    with path.open("a", encoding="utf-8") as f:
        f.write(f"{body.email}\n")
    return {"status": "ok", "message": "登録ありがとうございます。正式版でご連絡します。"}


@router.get("/price/{prefecture_slug}", response_class=HTMLResponse)
def prefecture_page(
    request: Request, prefecture_slug: str, db: Session = Depends(get_db)
) -> HTMLResponse:
    prefecture = services.get_prefecture_by_slug(db, prefecture_slug)
    if not prefecture:
        raise HTTPException(status_code=404, detail="都道府県が見つかりません")
    municipalities = services.list_municipalities_for_prefecture(db, prefecture)
    chart_data = services.get_prefecture_chart_data(db, prefecture, municipalities)
    regional_news = get_regional_news(prefecture.name_ja, prefecture.slug, limit=6)
    return _render(
        request,
        "prefecture.html",
        seo_prefecture(
            _base(request),
            prefecture.name_ja,
            prefecture.slug,
            len(municipalities),
        ),
        prefecture=prefecture,
        municipalities=municipalities,
        chart_data=chart_data.model_dump(),
        regional_news=regional_news,
    )


@router.get(
    "/price/{prefecture_slug}/{municipality_slug}",
    response_class=HTMLResponse,
)
def municipality_page(
    request: Request,
    prefecture_slug: str,
    municipality_slug: str,
    db: Session = Depends(get_db),
) -> HTMLResponse:
    prefecture, municipality = services.resolve_municipality(
        db, prefecture_slug, municipality_slug
    )
    if not prefecture or not municipality:
        raise HTTPException(status_code=404, detail="市区町村が見つかりません")
    if municipality.slug != municipality_slug and municipality_slug == municipality.code:
        return RedirectResponse(
            url=f"/price/{prefecture.slug}/{municipality.slug}",
            status_code=301,
        )
    detail = services.get_municipality_detail(db, prefecture, municipality)
    regional_news = get_regional_news(
        detail.prefecture_name,
        detail.prefecture_slug,
        detail.name_ja,
        detail.slug,
        limit=6,
    )
    return _render(
        request,
        "municipality.html",
        seo_municipality(
            _base(request),
            detail.prefecture_name,
            detail.prefecture_slug,
            detail.name_ja,
            detail.slug,
            total_transactions=detail.total_transactions,
            recent_avg_price=detail.recent_avg_price,
            latest_year=detail.latest_year,
            stats_updated_at=detail.stats_updated_at,
            population=detail.estat_insights.population
            if detail.estat_insights and detail.estat_insights.available
            else None,
        ),
        detail=detail,
        regional_news=regional_news,
        stations=services.list_stations_for_municipality(
            db, municipality.code, prefecture.code, limit=12
        ),
    )


@router.get(
    "/price/{prefecture_slug}/{municipality_slug}/area/{area_slug}",
    response_class=HTMLResponse,
)
def district_page(
    request: Request,
    prefecture_slug: str,
    municipality_slug: str,
    area_slug: str,
    db: Session = Depends(get_db),
) -> HTMLResponse:
    prefecture, municipality, district = resolve_district(
        db, prefecture_slug, municipality_slug, area_slug
    )
    if not prefecture or not municipality or not district:
        raise HTTPException(status_code=404, detail="地区が見つかりません")
    detail = get_district_detail(db, prefecture, municipality, district)
    if detail.slug != area_slug and area_slug == district.code:
        return RedirectResponse(
            url=f"/price/{prefecture.slug}/{municipality.slug}/area/{detail.slug}",
            status_code=301,
        )
    return _render(
        request,
        "district.html",
        seo_district(
            _base(request),
            detail.prefecture_name,
            detail.prefecture_slug,
            detail.municipality_name,
            detail.municipality_slug,
            detail.name,
            detail.slug,
            total_transactions=detail.total_transactions,
            recent_avg_price=detail.recent_avg_price,
        ),
        detail=detail,
    )


@router.get("/station/{station_id}", response_class=HTMLResponse)
def station_page(
    request: Request, station_id: int, db: Session = Depends(get_db)
) -> HTMLResponse:
    station = services.get_station_detail(db, station_id)
    if not station:
        raise HTTPException(status_code=404, detail="駅が見つかりません")
    return _render(
        request,
        "station.html",
        seo_station(_base(request), station),
        station=station,
    )


@router.get("/compare", response_class=HTMLResponse)
def compare_page(
    request: Request,
    a: str = "",
    b: str = "",
    db: Session = Depends(get_db),
) -> HTMLResponse:
    if a and b and "/" in a and "/" in b:
        a_parts = a.split("/", 1)
        b_parts = b.split("/", 1)
        return RedirectResponse(
            url=services.compare_path(a_parts[0], a_parts[1], b_parts[0], b_parts[1]),
            status_code=302,
        )
    return _render(
        request,
        "compare.html",
        seo_compare(_base(request), None, None),
        compare=None,
        param_a=a,
        param_b=b,
        popular_compares=services.POPULAR_COMPARES,
    )


@router.get(
    "/compare/{a_pref}/{a_muni}/vs/{b_pref}/{b_muni}",
    response_class=HTMLResponse,
)
def compare_pair_page(
    request: Request,
    a_pref: str,
    a_muni: str,
    b_pref: str,
    b_muni: str,
    db: Session = Depends(get_db),
) -> HTMLResponse:
    compare = services.get_compare_view(db, a_pref, a_muni, b_pref, b_muni)
    if not compare:
        raise HTTPException(status_code=404, detail="比較対象の市区町村が見つかりません")
    left_name = f"{compare.left.prefecture_name}{compare.left.name_ja}"
    right_name = f"{compare.right.prefecture_name}{compare.right.name_ja}"
    return _render(
        request,
        "compare.html",
        seo_compare(_base(request), left_name, right_name),
        compare=compare,
        param_a=f"{a_pref}/{a_muni}",
        param_b=f"{b_pref}/{b_muni}",
        popular_compares=services.POPULAR_COMPARES,
    )


@router.get("/for-agents", response_class=HTMLResponse)
def for_agents(request: Request) -> HTMLResponse:
    return _render(request, "for_agents.html", seo_for_agents(_base(request)))
