"""轻量漏斗埋点：只记录事件名和少量非敏感属性，绝不记录图片内容。"""
from __future__ import annotations

import json
import logging
import threading
from typing import Any

from sqlalchemy.orm import Session

from .db import Event, session_scope

log = logging.getLogger("yiciguo.events")

CLIENT_EVENTS = {
    "visit", "spec_view", "consent", "pick_photo", "pay_click", "pay_qr_shown", "pay_return_view",
    "download_click", "layout_click", "showcase_click", "share_click", "redo_click", "custom_spec",
}


def log_event(db: Session | None, user_id: str | None, name: str, props: dict[str, Any] | None = None) -> None:
    payload = json.dumps(props, ensure_ascii=False)[:1000] if props else None
    try:
        if db is None:
            with session_scope() as s:
                s.add(Event(user_id=user_id, name=name, props=payload))
        else:
            db.add(Event(user_id=user_id, name=name, props=payload))
            db.commit()
    except Exception:  # noqa: BLE001 - 埋点失败不影响主流程
        log.exception("记录事件失败 %s", name)


class KeyedLocks:
    def __init__(self):
        self._guard = threading.Lock()
        self._locks: dict[str, threading.Lock] = {}

    def get(self, key: str) -> threading.Lock:
        with self._guard:
            lock = self._locks.get(key)
            if lock is None:
                if len(self._locks) > 5000:
                    self._locks = {k: v for k, v in self._locks.items() if v.locked()}
                lock = self._locks[key] = threading.Lock()
            return lock
