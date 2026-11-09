"""请求级依赖：匿名用户（签名 Cookie）、简单限流。"""
from __future__ import annotations

import threading
import time
from collections import defaultdict, deque

from fastapi import Depends, HTTPException, Request, Response
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from ..config import settings
from ..db import User, get_db, utcnow
from ..security import new_id, new_pickup_code, sign, verify

COOKIE = "ycg_uid"
CONSENT_VERSION = "2026-11"


def cookie_value(uid: str) -> str:
    return f"{uid}.{sign(uid)}"


def set_user_cookie(response: Response, uid: str) -> None:
    response.set_cookie(COOKIE, cookie_value(uid), max_age=400 * 24 * 3600, httponly=True, samesite="lax",
                        secure=settings.https, path="/")


def _uid_from_cookie(request: Request) -> str | None:
    raw = request.cookies.get(COOKIE, "")
    if "." not in raw:
        return None
    uid, sig = raw.rsplit(".", 1)
    return uid if verify(uid, sig) else None


def create_user(db: Session) -> User:
    for _ in range(5):
        user = User(id=new_id("u", 10), pickup_code=new_pickup_code(), invite_code=new_pickup_code(6))
        db.add(user)
        try:
            db.commit()
            return user
        except IntegrityError:
            db.rollback()
    raise HTTPException(500, "创建用户失败")


def current_user(request: Request, response: Response, db: Session = Depends(get_db)) -> User:
    """匿名用户：首次访问自动创建；用户 ID 即即刻收的 external_buyer_id。"""
    uid = _uid_from_cookie(request)
    user = db.get(User, uid) if uid else None
    if user is None:
        user = create_user(db)
        set_user_cookie(response, user.id)
    elif (utcnow() - user.last_seen_at).total_seconds() > 600:
        user.last_seen_at = utcnow()
        db.commit()
    return user


def optional_user(request: Request, db: Session = Depends(get_db)) -> User | None:
    uid = _uid_from_cookie(request)
    return db.get(User, uid) if uid else None


class RateLimiter:
    def __init__(self):
        self._hits: dict[str, deque] = defaultdict(deque)
        self._lock = threading.Lock()

    def check(self, key: str, limit: int, window: int) -> None:
        now = time.time()
        with self._lock:
            q = self._hits[key]
            while q and q[0] < now - window:
                q.popleft()
            if len(q) >= limit:
                raise HTTPException(429, "操作太频繁，请稍后再试")
            q.append(now)
            if len(self._hits) > 20000:
                self._hits.clear()


limiter = RateLimiter()


def client_ip(request: Request) -> str:
    fwd = request.headers.get("x-forwarded-for", "")
    return fwd.split(",")[0].strip() if fwd else (request.client.host if request.client else "?")
