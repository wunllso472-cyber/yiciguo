"""照片处理完成后的业务钩子：驳回重做自动解锁、邀请奖励发放。"""
from __future__ import annotations

from .config import settings
from .db import Photo, User, session_scope
from .events import log_event
from .payments.service import mark_unlocked


def photo_ready(photo_id: str) -> None:
    with session_scope() as db:
        photo = db.get(Photo, photo_id)
        if photo is None:
            return
        log_event(db, photo.user_id, "ready", {"photo": photo.id})
        if photo.redo_of:
            src = db.get(Photo, photo.redo_of)
            if src and src.user_id == photo.user_id and src.unlocked:
                mark_unlocked(db, photo, "redo")
        user = db.get(User, photo.user_id)
        if user and user.invited_by and not user.invite_rewarded:
            user.invite_rewarded = True
            user.free_credits += 1
            inviter = db.get(User, user.invited_by)
            if inviter and inviter.invite_reward_count < settings.invite_reward_cap:
                inviter.free_credits += 1
                inviter.invite_reward_count += 1
            db.commit()
            log_event(db, user.id, "invite_reward")


def photo_rejected(photo_id: str) -> None:
    with session_scope() as db:
        photo = db.get(Photo, photo_id)
        if photo is None:
            return
        log_event(db, photo.user_id, "rejected", {"photo": photo.id})
        # 重做名额：新照片没通过时退回名额，用户可以再拍一次
        if photo.redo_of:
            src = db.get(Photo, photo.redo_of)
            if src:
                src.redo_used = False
