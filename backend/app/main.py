from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.api.routes import router as api_router
from app.db import init_db
from app.web.routes import router as web_router, templates
from app.web.seo import seo_not_found
from app.web.routes import _base

app = FastAPI(
    title="reinfolib-report",
    description="不動産情報ライブラリデータのSEO・レポート基盤",
    version="0.1.0",
)

static_dir = Path(__file__).resolve().parent / "web" / "static"
app.mount("/static", StaticFiles(directory=str(static_dir)), name="static")
app.include_router(api_router)
app.include_router(web_router)


@app.on_event("startup")
def on_startup() -> None:
    init_db()


@app.exception_handler(StarletteHTTPException)
async def http_exception_handler(request: Request, exc: StarletteHTTPException) -> HTMLResponse:
    if exc.status_code == 404 and not request.url.path.startswith("/api"):
        base = _base(request)
        return templates.TemplateResponse(
            request,
            "404.html",
            {"seo": seo_not_found(base)},
            status_code=404,
        )
    from fastapi.responses import JSONResponse

    return JSONResponse(status_code=exc.status_code, content={"detail": exc.detail})
