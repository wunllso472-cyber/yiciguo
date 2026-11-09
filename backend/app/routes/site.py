"""托管前端单页应用；为每条规格页注入标题/描述/正文摘要，方便搜索引擎收录（SEO 落地页）。"""
from __future__ import annotations

import html
from functools import lru_cache

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse, HTMLResponse, PlainTextResponse, Response

from ..config import settings
from ..specs import library

router = APIRouter(tags=["site"])

DEFAULT_TITLE = "一次过 · 报名照片过审助手"
DEFAULT_DESC = "按考试官方规格生成报名照：免费 AI 预审 12 项，自动换底、裁剪、压到指定 KB，¥0.99 下载无水印合规照片，被驳回免费重做。"


@lru_cache(maxsize=2)
def _read_index(mtime: float) -> str:
    return (settings.frontend_dist / "index.html").read_text(encoding="utf-8")


def _index_template() -> str:
    """按修改时间缓存：前端重新构建后无需重启后端。"""
    path = settings.frontend_dist / "index.html"
    if not path.exists():
        return ""
    return _read_index(path.stat().st_mtime)


def render_shell(title: str, desc: str, body_html: str = "") -> HTMLResponse:
    tpl = _index_template()
    if not tpl:
        return HTMLResponse("<h1>前端尚未构建</h1><p>请在 frontend 目录运行 npm run build。</p>", status_code=503)
    head = (f"<title>{html.escape(title)}</title>\n"
            f'<meta name="description" content="{html.escape(desc)}">\n'
            f'<meta property="og:title" content="{html.escape(title)}">\n'
            f'<meta property="og:description" content="{html.escape(desc)}">')
    out = tpl.replace(f"<title>{DEFAULT_TITLE}</title>", head, 1)
    if body_html:
        out = out.replace('<div id="root"></div>', f'<div id="root"><noscript>{body_html}</noscript></div>', 1)
    return HTMLResponse(out, headers={"Cache-Control": "no-cache"})


@router.get("/spec/{key}", response_class=HTMLResponse)
def spec_page(key: str):
    spec = library.get(key)
    if spec is None or spec.custom:
        return render_shell(DEFAULT_TITLE, DEFAULT_DESC)
    bgs = "、".join(s for s in spec.to_public()["bg_names"])
    title = f"{spec.name}照片要求与在线制作 · 一次过"
    desc = (f"{spec.name}报名照片规格：{spec.to_public()['size_text']}，文件大小{spec.to_public()['kb_text']}，"
            f"底色{bgs}。上传自拍免费预审，一键生成合规照片。")
    rules = "".join(f"<li>{html.escape(r)}</li>" for r in spec.rules)
    body = (f"<h1>{html.escape(spec.name)}照片要求</h1><p>{html.escape(desc)}</p><ul>{rules}</ul>"
            f"<p>{html.escape(spec.notes)}</p>")
    return render_shell(title, desc, body)


@router.get("/sitemap.xml")
def sitemap():
    urls = [settings.base_url + "/"] + [f"{settings.base_url}/spec/{s.id}" for s in library.all()]
    body = "".join(f"<url><loc>{html.escape(u)}</loc></url>" for u in urls)
    xml = f'<?xml version="1.0" encoding="UTF-8"?><urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">{body}</urlset>'
    return Response(xml, media_type="application/xml")


@router.get("/robots.txt", response_class=PlainTextResponse)
def robots():
    return f"User-agent: *\nDisallow: /api/\nDisallow: /photo/\nDisallow: /r/\nSitemap: {settings.base_url}/sitemap.xml\n"


@router.get("/{path:path}", include_in_schema=False)
def spa(path: str):
    if path.startswith("api/"):
        raise HTTPException(404)
    dist = settings.frontend_dist
    candidate = (dist / path).resolve() if path else None
    if candidate and candidate.is_file() and dist.resolve() in candidate.parents:
        headers = {"Cache-Control": "public, max-age=31536000, immutable"} if path.startswith("assets/") else {}
        return FileResponse(candidate, headers=headers)
    return render_shell(DEFAULT_TITLE, DEFAULT_DESC)
