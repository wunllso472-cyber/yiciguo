"""匿名用户：隐私同意、取件码换设备找回、邀请奖励。"""
from __future__ import annotations

from datetime import timedelta

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel
from sqlalchemy.orm import Session

from ..config import settings
from ..db import User, get_db, utcnow
from ..events import CLIENT_EVENTS, log_event
from ..payments import payments
from ..security import normalize_code
from .deps import CONSENT_VERSION, client_ip, current_user, limiter, optional_user, set_user_cookie

router = APIRouter(prefix="/api", tags=["user"])


def me_view(user: User) -> dict:
    return {
        "id": user.id[:7],
        "pickup_code": user.pickup_code,
        "invite_code": user.invite_code,
        "consent": user.consent_version == CONSENT_VERSION,
        "consent_version": CONSENT_VERSION,
        "free_credits": user.free_credits,
        "pay_enabled": payments.enabled,
        "pay_mode": payments.mode,
        "showcase_url": settings.showcase_url,
        "ttl_hours": settings.photo_ttl_hours,
        "redo_days": settings.redo_days,
    }


@router.get("/me")
def me(user: User = Depends(current_user)):
    return me_view(user)


class ConsentBody(BaseModel):
    version: str


@router.post("/me/consent")
def consent(body: ConsentBody, user: User = Depends(current_user), db: Session = Depends(get_db)):
    if body.version != CONSENT_VERSION:
        raise HTTPException(400, "隐私规则已更新，请刷新页面后重新阅读")
    user.consent_version = CONSENT_VERSION
    user.consent_at = utcnow()
    db.commit()
    log_event(db, user.id, "consent", {"v": CONSENT_VERSION})
    return me_view(user)


@router.post("/me/consent/withdraw")
def withdraw(user: User = Depends(current_user), db: Session = Depends(get_db)):
    user.consent_version = None
    db.commit()
    return me_view(user)


class RestoreBody(BaseModel):
    code: str


@router.post("/me/restore")
def restore(body: RestoreBody, request: Request, response: Response, db: Session = Depends(get_db)):
    """用取件码在另一台设备上找回照片和次数。"""
    limiter.check(f"restore:{client_ip(request)}", 10, 600)
    code = normalize_code(body.code)
    user = db.query(User).filter_by(pickup_code=code).first() if len(code) == 8 else None
    if user is None:
        raise HTTPException(404, "取件码不正确")
    set_user_cookie(response, user.id)
    log_event(db, user.id, "restore")
    return me_view(user)


class InviteBody(BaseModel):
    code: str


@router.post("/me/invite")
def accept_invite(body: InviteBody, user: User = Depends(current_user), db: Session = Depends(get_db)):
    """新用户通过分享链接进入：首张照片处理完成后，双方各得 1 次免费导出（由本站发放，不走支付）。"""
    code = normalize_code(body.code)
    inviter = db.query(User).filter_by(invite_code=code).first()
    if inviter is None or inviter.id == user.id:
        return {"ok": False}
    if user.invited_by or utcnow() - user.created_at > timedelta(hours=2):
        return {"ok": False}
    user.invited_by = inviter.id
    db.commit()
    log_event(db, user.id, "invited", {"by": inviter.id[:7]})
    return {"ok": True}


class EventBody(BaseModel):
    name: str
    props: dict | None = None


@router.post("/events")
def client_event(body: EventBody, request: Request, user: User | None = Depends(optional_user),
                 db: Session = Depends(get_db)):
    if body.name not in CLIENT_EVENTS:
        return {"ok": False}
    limiter.check(f"ev:{client_ip(request)}", 300, 600)
    props = {k: str(v)[:80] for k, v in (body.props or {}).items()}
    log_event(db, user.id if user else None, body.name, props)
    return {"ok": True}
