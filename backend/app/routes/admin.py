"""运营看板：漏斗、付费用户、热门规格、规格纠错。需要 YCG_ADMIN_TOKEN。"""
from __future__ import annotations

import hmac
import json
from collections import Counter
from datetime import timedelta

from fastapi import APIRouter, Depends, Header, HTTPException
from sqlalchemy import distinct, func
from sqlalchemy.orm import Session

from ..config import settings
from ..db import Consume, Event, Photo, Purchase, SpecFeedback, User, get_db, utcnow
from ..specs import library

router = APIRouter(prefix="/api/admin", tags=["admin"])

FUNNEL = ["visit", "spec_view", "upload", "ready", "pay_click", "purchase_create", "paid_detected", "unlock",
          "download"]


def require_admin(authorization: str = Header("")) -> None:
    token = authorization.removeprefix("Bearer ").strip()
    if not settings.admin_token or not hmac.compare_digest(token, settings.admin_token):
        raise HTTPException(401, "需要管理员令牌")


@router.get("/stats", dependencies=[Depends(require_admin)])
def stats(days: int = 14, db: Session = Depends(get_db)):
    since = utcnow() - timedelta(days=days)
    daily: dict[str, dict[str, int]] = {}
    rows = (
        db.query(func.date(Event.created_at), Event.name, func.count(distinct(Event.user_id)))
        .filter(Event.created_at >= since, Event.name.in_(FUNNEL))
        .group_by(func.date(Event.created_at), Event.name)
        .all()
    )
    for day, name, n in rows:
        daily.setdefault(str(day), {})[name] = n
    totals = dict(
        db.query(Event.name, func.count(distinct(Event.user_id)))
        .filter(Event.created_at >= since, Event.name.in_(FUNNEL))
        .group_by(Event.name)
        .all()
    )
    paid_users = (
        db.query(func.count(distinct(Consume.user_id))).filter(Consume.status == "succeeded").scalar() or 0
    )
    buyers = (
        db.query(func.count(distinct(Purchase.user_id))).filter(Purchase.status == "confirmed").scalar() or 0
    )
    unlock_types = dict(db.query(Photo.unlock_type, func.count()).filter(Photo.unlocked.is_(True))
                        .group_by(Photo.unlock_type).all())
    specs = Counter()
    for (props,) in db.query(Event.props).filter(Event.name == "upload", Event.created_at >= since).all():
        try:
            specs[json.loads(props or "{}").get("spec", "?")] += 1
        except json.JSONDecodeError:
            pass
    pending = db.query(Consume).filter(Consume.status.in_(["pending", "unknown"])).count()
    feedback = [
        {"spec_id": f.spec_id, "content": f.content, "url": f.url, "contact": f.contact,
         "created_at": f.created_at.isoformat()}
        for f in db.query(SpecFeedback).order_by(SpecFeedback.created_at.desc()).limit(50)
    ]
    return {
        "funnel": [{"name": n, "users": totals.get(n, 0)} for n in FUNNEL],
        "daily": daily,
        "paying_users_consumed": paid_users,
        "paying_users_purchased": buyers,
        "users_total": db.query(User).count(),
        "unlock_types": unlock_types,
        "top_specs": specs.most_common(15),
        "pending_consumes": pending,
        "feedback": feedback,
    }


@router.post("/specs/reload", dependencies=[Depends(require_admin)])
def reload_specs():
    library.reload()
    return {"ok": True, "count": len(library.all())}
