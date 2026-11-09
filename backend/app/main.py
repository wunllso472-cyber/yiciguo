"""一次过 · 报名照片过审助手 —— FastAPI 入口。

本地开发：  uvicorn app.main:app --reload --port 8000
"""
from __future__ import annotations

import logging
import threading
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from .config import settings
from .db import Photo, init_db, session_scope, utcnow
from .payments import payments
from .pipeline import delete_photo_files
from .routes import admin, mock_pages, pay, photos, site, specs, users

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
log = logging.getLogger("yiciguo")

_stop = threading.Event()


def cleanup_expired() -> int:
    """删除到期照片（默认 24 小时）：文件整目录删除，数据库只保留不含图像信息的记录。"""
    n = 0
    with session_scope() as db:
        rows = db.query(Photo).filter(Photo.deleted.is_(False), Photo.expires_at < utcnow()).limit(500).all()
        for p in rows:
            delete_photo_files(p.id)
            p.deleted = True
            p.analysis_json = None
            n += 1
    return n


def _background_loop() -> None:
    tick = 0
    while not _stop.wait(15):
        tick += 1
        try:
            payments.reconcile()
        except Exception:  # noqa: BLE001
            log.exception("核销对账失败")
        if tick % 20 == 1:  # 约每 5 分钟
            try:
                n = cleanup_expired()
                if n:
                    log.info("已删除 %d 张到期照片", n)
            except Exception:  # noqa: BLE001
                log.exception("清理到期照片失败")


@asynccontextmanager
async def lifespan(_app: FastAPI):
    init_db()
    log.info("启动：env=%s pay_mode=%s base_url=%s", settings.env, payments.mode, settings.base_url)
    t = threading.Thread(target=_background_loop, name="bg", daemon=True)
    t.start()
    yield
    _stop.set()


app = FastAPI(title="一次过 · 报名照片过审助手", lifespan=lifespan, docs_url="/api/docs" if not settings.is_prod else None,
              redoc_url=None, openapi_url="/api/openapi.json" if not settings.is_prod else None)


@app.exception_handler(StarletteHTTPException)
async def http_error(_request: Request, exc: StarletteHTTPException):
    return JSONResponse({"detail": exc.detail}, status_code=exc.status_code)


@app.exception_handler(RequestValidationError)
async def validation_error(_request: Request, exc: RequestValidationError):
    return JSONResponse({"detail": "参数不正确", "errors": exc.errors()[:5]}, status_code=422)


@app.middleware("http")
async def security_headers(request: Request, call_next):
    response = await call_next(request)
    response.headers.setdefault("X-Content-Type-Options", "nosniff")
    response.headers.setdefault("Referrer-Policy", "strict-origin-when-cross-origin")
    if request.url.path.startswith("/api/"):
        response.headers.setdefault("Cache-Control", "no-store")
    return response


@app.get("/api/health")
def health():
    return {"ok": True, "pay_mode": payments.mode}


app.include_router(users.router)
app.include_router(specs.router)
app.include_router(photos.router)
app.include_router(pay.router)
app.include_router(admin.router)
if payments.mode == "mock":
    app.include_router(mock_pages.router)
app.include_router(site.router)  # 必须最后：兜底返回前端页面
