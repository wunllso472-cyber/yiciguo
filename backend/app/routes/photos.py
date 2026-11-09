"""照片：上传 → 处理进度 → 预审报告 + 水印预览 → 解锁 → 下载（单张/打印排版）→ 删除 / 驳回重做。"""
from __future__ import annotations

import json
from datetime import timedelta
from typing import Any
from urllib.parse import quote

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, Request, UploadFile
from fastapi.responses import FileResponse
from pydantic import BaseModel
from sqlalchemy.orm import Session

from ..config import settings
from ..db import Photo, User, get_db, utcnow
from ..events import log_event
from ..payments import payments
from ..pipeline import STAGES, delete_photo_files, get_layout, get_render, new_expiry, submit
from ..security import check_signed, new_id, signed_query
from ..specs import Spec, bg_name, library
from .deps import client_ip, current_user, limiter

router = APIRouter(prefix="/api/photos", tags=["photos"])

ALLOWED_TYPES = {"image/jpeg", "image/png", "image/heic", "image/heif", "image/webp", "application/octet-stream", ""}


def resolve_spec(key: str | None) -> Spec:
    spec = library.get(key or "") if key else None
    if spec is None:
        raise HTTPException(400, "未知的规格")
    return spec


def resolve_bg(spec: Spec, bg: str | None) -> str:
    if bg and spec.allows_bg(bg):
        return bg
    return spec.backgrounds[0]


def _file_url(photo_id: str, spec: Spec, bg: str, kind: str, ttl: int) -> str:
    key = f"{photo_id}|{spec.key}|{bg}|{kind}"
    return (f"/api/photos/{photo_id}/file?kind={kind}&spec={quote(spec.key, safe='')}&bg={quote(bg, safe='')}&"
            f"{signed_query(key, ttl)}")


def can_redo(photo: Photo) -> bool:
    return (photo.unlocked and photo.unlock_type != "redo" and not photo.redo_used and photo.unlocked_at is not None
            and utcnow() - photo.unlocked_at < timedelta(days=settings.redo_days))


def photo_view(photo: Photo, spec_key: str | None = None, bg: str | None = None) -> dict[str, Any]:
    spec = library.get(spec_key or photo.spec_key) or library.get("cun1")
    bg = resolve_bg(spec, bg or photo.bg)
    view: dict[str, Any] = {
        "id": photo.id,
        "status": photo.status,
        "stage": photo.stage,
        "stage_text": STAGES.get(photo.stage, ""),
        "error": photo.error,
        "created_at": photo.created_at.isoformat() + "Z",
        "expires_at": photo.expires_at.isoformat() + "Z",
        "unlocked": photo.unlocked,
        "unlock_type": photo.unlock_type,
        "redo_of": photo.redo_of,
        "can_redo": can_redo(photo),
        "spec": spec.to_public(brief=True),
        "bg": bg,
        "bg_name": bg_name(bg),
        "backgrounds": [{"key": b, "name": bg_name(b)} for b in spec.backgrounds],
    }
    analysis = json.loads(photo.analysis_json) if photo.analysis_json else None
    if photo.status == "rejected" and analysis:
        view["report"] = analysis.get("report")
    if photo.status == "ready" and analysis:
        result = get_render(photo.id, analysis, spec, bg)
        meta = result.meta
        view.update(
            report=meta["report"],
            validation=meta["validation"],
            output={"width": meta["width"], "height": meta["height"], "kb": meta["kb"], "quality": meta["quality"],
                    "head_ratio": meta["plan"]["head_ratio"], "top_margin": meta["plan"]["top_margin"]},
            preview_url=_file_url(photo.id, spec, bg, "preview", 3600),
        )
        if photo.unlocked:
            view["downloads"] = {
                "photo": _file_url(photo.id, spec, bg, "photo", 3600),
                "layout": _file_url(photo.id, spec, bg, "layout", 3600),
                "filename": download_name(spec, bg, meta),
            }
    return view


def download_name(spec: Spec, bg: str, meta: dict[str, Any]) -> str:
    """纯 ASCII 文件名：部分老旧报名系统对中文文件名处理有问题。"""
    base = "custom" if spec.custom else spec.id
    color = bg if bg.isalpha() else bg.lstrip("#").upper()
    return f"{base}_{color}_{meta['width']}x{meta['height']}_{meta['kb']:.1f}KB.jpg"


def owned_photo(db: Session, user: User, photo_id: str) -> Photo:
    photo = db.get(Photo, photo_id)
    if photo is None or photo.user_id != user.id:
        raise HTTPException(404, "照片不存在")
    if photo.deleted or photo.expires_at < utcnow():
        raise HTTPException(410, "照片已过期或已删除（为保护隐私，照片最多保留 24 小时）")
    return photo


@router.post("")
async def upload(
    request: Request,
    file: UploadFile = File(...),
    spec_key: str = Form(...),
    bg: str = Form(""),
    redo_of: str = Form(""),
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
):
    if not user.consent_version:
        raise HTTPException(403, "请先阅读并同意《人脸信息处理规则》")
    limiter.check(f"up:{user.id}", 40, 3600)
    limiter.check(f"upip:{client_ip(request)}", 80, 3600)
    spec = resolve_spec(spec_key)
    if (file.content_type or "") not in ALLOWED_TYPES and not (file.content_type or "").startswith("image/"):
        raise HTTPException(400, "请上传图片文件")
    busy = db.query(Photo).filter(Photo.user_id == user.id, Photo.status.in_(["queued", "processing"])).count()
    if busy >= 3:
        raise HTTPException(429, "还有照片正在处理，请稍候")
    data = await file.read(settings.max_upload_mb * 1024 * 1024 + 1)
    if len(data) > settings.max_upload_mb * 1024 * 1024:
        raise HTTPException(413, f"图片不能超过 {settings.max_upload_mb}MB")
    if len(data) < 1024:
        raise HTTPException(400, "图片内容为空")

    source = None
    if redo_of:
        source = owned_photo(db, user, redo_of)
        if not can_redo(source):
            raise HTTPException(400, "该照片不能免费重做（每张已付费照片可免费重做 1 次，7 天内有效）")
        source.redo_used = True
    photo = Photo(id=new_id("ph", 10), user_id=user.id, spec_key=spec.key, bg=resolve_bg(spec, bg),
                  status="queued", stage="queued", expires_at=new_expiry(), redo_of=source.id if source else None)
    db.add(photo)
    db.commit()
    log_event(db, user.id, "redo" if source else "upload", {"spec": spec.key, "photo": photo.id})
    submit(photo.id, data)
    return {"id": photo.id}


@router.get("")
def list_photos(user: User = Depends(current_user), db: Session = Depends(get_db)):
    rows = (
        db.query(Photo)
        .filter(Photo.user_id == user.id, Photo.deleted.is_(False), Photo.expires_at > utcnow())
        .order_by(Photo.created_at.desc())
        .limit(30)
        .all()
    )
    items = []
    for p in rows:
        spec = library.get(p.spec_key) or library.get("cun1")
        item = {
            "id": p.id, "status": p.status, "unlocked": p.unlocked, "unlock_type": p.unlock_type,
            "spec": {"key": spec.key, "short": spec.short, "name": spec.name}, "bg": p.bg, "bg_name": bg_name(p.bg),
            "created_at": p.created_at.isoformat() + "Z", "expires_at": p.expires_at.isoformat() + "Z",
        }
        if p.status == "ready":
            item["thumb_url"] = _file_url(p.id, spec, resolve_bg(spec, p.bg), "preview", 3600)
        items.append(item)
    return {"items": items}


@router.get("/{photo_id}")
def detail(photo_id: str, spec: str | None = None, bg: str | None = None, user: User = Depends(current_user),
           db: Session = Depends(get_db)):
    photo = owned_photo(db, user, photo_id)
    view = photo_view(photo, spec, bg)
    if photo.status == "ready" and not photo.unlocked:
        view["free_credits"] = user.free_credits
    return view


class SelectBody(BaseModel):
    spec_key: str
    bg: str | None = None


@router.post("/{photo_id}/select")
def select(photo_id: str, body: SelectBody, user: User = Depends(current_user), db: Session = Depends(get_db)):
    photo = owned_photo(db, user, photo_id)
    spec = resolve_spec(body.spec_key)
    bg = resolve_bg(spec, body.bg)
    photo.spec_key, photo.bg = spec.key, bg
    db.commit()
    return photo_view(photo)


class UnlockBody(BaseModel):
    method: str = "auto"  # auto | free


@router.post("/{photo_id}/unlock")
def unlock(photo_id: str, body: UnlockBody, user: User = Depends(current_user), db: Session = Depends(get_db)):
    photo = owned_photo(db, user, photo_id)
    if photo.status != "ready":
        raise HTTPException(400, "照片还没处理好")
    # 先在服务端生成并校验无水印成品；生成失败不核销
    view = photo_view(photo)
    if any(v["status"] == "fail" for v in view.get("validation", [])):
        raise HTTPException(400, "成品未通过规格校验，本次不扣次数，请换一张照片或调整规格")
    result = payments.unlock(db, user, photo, body.method)
    db.refresh(photo)
    out = {"result": result, "photo": photo_view(photo)}
    if result["state"] == "need_purchase":
        out["offers"] = payments.offers()
    return out


@router.delete("/{photo_id}")
def delete(photo_id: str, user: User = Depends(current_user), db: Session = Depends(get_db)):
    photo = db.get(Photo, photo_id)
    if photo is None or photo.user_id != user.id:
        raise HTTPException(404, "照片不存在")
    delete_photo_files(photo.id)
    photo.deleted = True
    photo.analysis_json = None
    db.commit()
    log_event(db, user.id, "delete", {"photo": photo.id})
    return {"ok": True}


@router.get("/{photo_id}/file")
def file(photo_id: str, kind: str, spec: str, bg: str, exp: int, sig: str, dl: int = Query(0),
         db: Session = Depends(get_db)):
    """签名链接（有效期 1 小时），不依赖 Cookie，方便在支付宝内置浏览器里直接下载。"""
    if not check_signed(f"{photo_id}|{spec}|{bg}|{kind}", exp, sig):
        raise HTTPException(403, "链接已失效，请回到页面刷新")
    photo = db.get(Photo, photo_id)
    if photo is None or photo.deleted or photo.expires_at < utcnow() or photo.status != "ready":
        raise HTTPException(410, "照片已过期或已删除")
    spec_obj = resolve_spec(spec)
    bg = resolve_bg(spec_obj, bg)
    analysis = json.loads(photo.analysis_json)
    result = get_render(photo.id, analysis, spec_obj, bg)
    headers = {"Cache-Control": "private, max-age=600"}
    if kind == "preview":
        return FileResponse(result.preview_path, media_type="image/jpeg", headers=headers)
    if not photo.unlocked:
        raise HTTPException(402, "解锁后才能下载无水印照片")
    name = download_name(spec_obj, bg, result.meta)
    if kind == "photo":
        path = result.final_path
        log_event(db, photo.user_id, "download", {"photo": photo.id, "spec": spec_obj.key})
    elif kind == "layout":
        path = get_layout(photo.id, result, spec_obj)
        name = name.replace(".jpg", "_print6inch.jpg")
    else:
        raise HTTPException(400, "未知文件类型")
    disposition = "attachment" if dl else "inline"
    headers["Content-Disposition"] = f"{disposition}; filename=\"photo.jpg\"; filename*=UTF-8''{quote(name)}"
    return FileResponse(path, media_type="image/jpeg", headers=headers)
