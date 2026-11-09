"""支付：档位、余额、发起购买、返回确认（含支付宝内置浏览器打开的返回页）。"""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Response
from pydantic import BaseModel
from sqlalchemy.orm import Session

from ..db import Photo, Purchase, User, get_db, utcnow
from ..events import log_event
from ..payments import PayError, payments
from ..payments.service import cn_text
from ..security import verify
from .deps import current_user, limiter, set_user_cookie
from .photos import photo_view

router = APIRouter(prefix="/api/pay", tags=["pay"])


@router.get("/offers")
def offers():
    return payments.offers()


@router.get("/balance")
def balance(user: User = Depends(current_user), db: Session = Depends(get_db)):
    monthly = None
    if payments.monthly_product and db.query(Purchase).filter_by(user_id=user.id, product="monthly").first():
        monthly = payments.monthly_decision(user.id)
    return {"remaining": payments.balance(user.id), "free_credits": user.free_credits, "monthly": monthly}


class PurchaseBody(BaseModel):
    product: str = "count"  # count | monthly
    sku_id: str | None = None
    photo_id: str | None = None


def purchase_view(p: Purchase) -> dict[str, Any]:
    return {
        "out_request_no": p.out_request_no,
        "product": p.product,
        "sku_id": p.sku_id,
        "photo_id": p.photo_id,
        "status": p.status,
        "purchase_url": p.purchase_url,
        "qr_code": p.qr_code,
        "expire_time": cn_text(p.expire_time),
        "expired": bool(p.expire_time and p.expire_time < utcnow()),
    }


@router.post("/purchase")
def create_purchase(body: PurchaseBody, user: User = Depends(current_user), db: Session = Depends(get_db)):
    if body.product not in ("count", "monthly"):
        raise HTTPException(400, "未知商品")
    limiter.check(f"buy:{user.id}", 20, 600)
    if body.photo_id:
        photo = db.get(Photo, body.photo_id)
        if photo is None or photo.user_id != user.id:
            raise HTTPException(404, "照片不存在")
    try:
        p = payments.create_purchase(db, user.id, body.product, body.sku_id, body.photo_id)
    except PayError as exc:
        raise HTTPException(409, exc.message) from exc
    return purchase_view(p)


def _check(db: Session, p: Purchase, user: User) -> dict[str, Any]:
    """确认付款结果；如果这次购买是为某张照片发起的，到账后自动为它解锁（只核销 1 次）。"""
    result: dict[str, Any] = {"purchase": purchase_view(p)}
    check = payments.check_purchase(db, p)
    result["pay"] = check
    if check["state"] == "paid" and p.photo_id:
        photo = db.get(Photo, p.photo_id)
        if photo and not photo.deleted and photo.status == "ready" and photo.expires_at > utcnow():
            photo_view(photo)  # 确保无水印成品已生成
            result["unlock"] = payments.unlock(db, user, photo)
            db.refresh(photo)
            result["photo"] = photo_view(photo)
    return result


@router.get("/purchase/{req_no}")
def purchase_status(req_no: str, user: User = Depends(current_user), db: Session = Depends(get_db)):
    p = db.get(Purchase, req_no)
    if p is None or p.user_id != user.id:
        raise HTTPException(404, "订单不存在")
    limiter.check(f"chk:{user.id}", 120, 300)
    return _check(db, p, user)


@router.get("/return/{req_no}")
def purchase_return(req_no: str, t: str, response: Response, db: Session = Depends(get_db)):
    """支付宝托管页返回的页面（可能在支付宝 App 内打开，没有原浏览器的 Cookie），凭签名访问。"""
    if not verify(req_no, t, 16):
        raise HTTPException(403, "链接无效")
    p = db.get(Purchase, req_no)
    if p is None:
        raise HTTPException(404, "订单不存在")
    user = db.get(User, p.user_id)
    limiter.check(f"chk:{user.id}", 120, 300)
    set_user_cookie(response, user.id)
    log_event(db, user.id, "pay_return", {"req": req_no})
    out = _check(db, p, user)
    out["pickup_code"] = user.pickup_code
    return out
