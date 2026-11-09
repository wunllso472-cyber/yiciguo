"""支付业务：购买入口、付款返回确认、交付核销与结果恢复。

关键约束（来自即刻收直连文档）：
- 没有异步通知：callback_url 只是页面返回地址，必须由服务端主动 quota.query / purchase.consult 确认；
- quota.query 失败不能当作 0 余额；remaining 以接口返回为准；
- quota.verify 只有 code=10000 且 consume_status=SUCCEEDED 才算扣减成功；
- 超时/PROCESSING/未知：保留原 out_request_no，用 quota.refresh 查或原参数重试，绝不换号重扣；
- 没有核销撤销接口：先生成好无水印成品再核销，生成失败不核销。
"""
from __future__ import annotations

import logging
import time
from datetime import datetime, timedelta
from typing import Any

from sqlalchemy.orm import Session

from ..config import settings
from ..db import Consume, Photo, Purchase, User, session_scope, utcnow
from ..events import KeyedLocks, log_event
from ..security import new_id, sign
from .gateway import GatewayError
from .nowpay import (
    CONSUME_CONFLICT,
    CONSUME_NOT_FOUND,
    LINK_CREATING,
    QUOTA_INSUFFICIENT,
    NowPayClient,
)

log = logging.getLogger("yiciguo.pay")

CONSUME_REASON = "导出报名照（无水印成品）"
_locks = KeyedLocks()


class PayError(Exception):
    def __init__(self, message: str, code: str = "PAY_ERROR"):
        super().__init__(message)
        self.message = message
        self.code = code


def parse_cn_time(value: str | None) -> datetime | None:
    """即刻收返回的时间是北京时间 yyyy-MM-dd HH:mm:ss，统一转成 UTC naive 存库。"""
    if not value:
        return None
    try:
        return datetime.strptime(value, "%Y-%m-%d %H:%M:%S") - timedelta(hours=8)
    except ValueError:
        return None


def cn_text(dt: datetime | None) -> str | None:
    return (dt + timedelta(hours=8)).strftime("%Y-%m-%d %H:%M") if dt else None


def mark_unlocked(db: Session, photo: Photo, unlock_type: str) -> None:
    if photo.unlocked:
        return
    now = utcnow()
    photo.unlocked = True
    photo.unlock_type = unlock_type
    photo.unlocked_at = now
    # 解锁后保证至少还有 24 小时可以下载
    photo.expires_at = max(photo.expires_at, now + timedelta(hours=settings.photo_ttl_hours))
    db.commit()
    log_event(db, photo.user_id, "unlock", {"photo": photo.id, "type": unlock_type})


class PaymentService:
    def __init__(self, client: NowPayClient | None, count_product: str, monthly_product: str, base_url: str,
                 mode: str):
        self.client = client
        self.count_product = count_product
        self.monthly_product = monthly_product
        self.base_url = base_url.rstrip("/")
        self.mode = mode
        self._offer_cache: dict[str, tuple[float, dict[str, Any]]] = {}
        self._monthly_cache: dict[str, tuple[float, dict[str, Any]]] = {}

    # ------------------------------------------------------------ 基础
    @property
    def enabled(self) -> bool:
        return self.client is not None and bool(self.count_product)

    def callback_url(self, out_request_no: str) -> str | None:
        """支付完成后返回的页面。带签名，换浏览器（如支付宝内打开）也能查看结果。"""
        if not (self.base_url.startswith("https://") or self.mode == "mock"):
            return None  # 即刻收要求 HTTPS；本地 http 环境不传
        return f"{self.base_url}/r/{out_request_no}?t={sign(out_request_no, 16)}"

    def _product_offer(self, product_id: str, force: bool = False) -> dict[str, Any]:
        cached = self._offer_cache.get(product_id)
        if cached and not force and time.time() - cached[0] < (60 if cached[1].get("status") != "ERROR" else 10):
            return cached[1]
        try:
            node = self.client.charge_query(product_id)  # type: ignore[union-attr]
            options = []
            for o in node.get("charging_options") or []:
                options.append({
                    "sku_id": o.get("sku_id"),
                    "name": o.get("display_name"),
                    "price": o.get("price"),
                    "quota": o.get("quota_amount"),
                    "period": o.get("duration_period"),
                })
            status = node.get("capability_status")
            data = {
                "status": status,
                "billing_mode": node.get("billing_mode"),
                "product_name": node.get("product_name"),
                "options": options,
                # 档位非空不代表可买：必须 ENABLED
                "purchasable": status == "ENABLED" and bool(options),
            }
        except GatewayError as exc:
            log.warning("charge.query 失败 %s: %s", product_id, exc)
            data = {"status": "ERROR", "options": [], "purchasable": False}
        self._offer_cache[product_id] = (time.time(), data)
        return data

    def offers(self, force: bool = False) -> dict[str, Any]:
        if not self.enabled:
            return {"enabled": False, "mode": self.mode, "count": None, "monthly": None}
        return {
            "enabled": True,
            "mode": self.mode,
            "count": self._product_offer(self.count_product, force),
            "monthly": self._product_offer(self.monthly_product, force) if self.monthly_product else None,
        }

    def balance(self, user_id: str) -> int | None:
        """剩余次数；查询失败返回 None（不能当作 0）。"""
        if not self.enabled:
            return None
        try:
            node = self.client.quota_query(self.count_product, user_id)  # type: ignore[union-attr]
            return int(node.get("remaining", 0))
        except (GatewayError, TypeError, ValueError) as exc:
            log.warning("quota.query 失败: %s", exc)
            return None

    def monthly_decision(self, user_id: str, force: bool = False) -> dict[str, Any] | None:
        if not (self.client and self.monthly_product):
            return None
        cached = self._monthly_cache.get(user_id)
        if cached and not force and time.time() - cached[0] < 60:
            return cached[1]
        try:
            node = self.client.purchase_consult(self.monthly_product, user_id)
            data = {
                "decision": node.get("decision"),
                "reason_code": node.get("reason_code"),
                "valid_until": node.get("valid_until"),
            }
        except GatewayError as exc:
            log.warning("purchase.consult 失败: %s", exc)
            return {"decision": "UNKNOWN"}
        if data["decision"] == "ALLOW":
            self._monthly_cache[user_id] = (time.time(), data)
        else:
            self._monthly_cache.pop(user_id, None)
        return data

    # ------------------------------------------------------------ 购买
    def create_purchase(self, db: Session, user_id: str, product: str, sku_id: str | None,
                        photo_id: str | None) -> Purchase:
        if not self.enabled:
            raise PayError("支付暂未开通", "PAY_DISABLED")
        pid = self.count_product if product == "count" else self.monthly_product
        if not pid:
            raise PayError("该商品暂未开通", "NOT_CONFIGURED")
        offer = self._product_offer(pid)
        if not offer["purchasable"]:
            offer = self._product_offer(pid, force=True)
            if not offer["purchasable"]:
                raise PayError("商品暂不可购买，请稍后再试", "NOT_PURCHASABLE")
        if sku_id and sku_id not in {o["sku_id"] for o in offer["options"]}:
            raise PayError("所选档位已下架，请刷新后重选", "SKU_INVALID")

        # 防重复点击：复用仍有效的同一购买入口
        now = utcnow()
        existing = (
            db.query(Purchase)
            .filter_by(user_id=user_id, product=product, sku_id=sku_id, photo_id=photo_id, status="created")
            .order_by(Purchase.created_at.desc())
            .first()
        )
        if existing and existing.expire_time and existing.expire_time > now + timedelta(minutes=3):
            return existing

        remaining_before = self.balance(user_id) if product == "count" else None
        req_no = new_id("pc", 10)
        p = Purchase(out_request_no=req_no, user_id=user_id, photo_id=photo_id, product=product, out_product_id=pid,
                     sku_id=sku_id, callback_url=self.callback_url(req_no), status="creating",
                     remaining_before=remaining_before)
        db.add(p)
        db.commit()  # 先持久化请求号和参数，再调用接口

        last_error = ""
        for attempt in range(3):
            try:
                node = self.client.purchase_create(req_no, pid, user_id, sku_id, p.callback_url)  # type: ignore[union-attr]
            except GatewayError as exc:
                last_error = str(exc)
                if exc.unknown or exc.sub_code == LINK_CREATING:
                    time.sleep(0.5 * (attempt + 1))  # 原请求号 + 原参数重试
                    continue
                p.status, p.last_error = "error", last_error
                db.commit()
                raise PayError("创建支付失败，请稍后重试", exc.sub_code or exc.code) from exc
            p.purchase_url = node.get("purchase_url")
            p.qr_code = node.get("purchase_qr_code")
            p.expire_time = parse_cn_time(node.get("expire_time")) or now + timedelta(minutes=30)
            p.status = "created"
            db.commit()
            log_event(db, user_id, "purchase_create", {"product": product, "sku": sku_id, "photo": photo_id})
            return p
        p.status, p.last_error = "error", last_error
        db.commit()
        raise PayError("支付服务繁忙，请稍后重试", "PAY_TIMEOUT")

    def check_purchase(self, db: Session, purchase: Purchase) -> dict[str, Any]:
        """付款页返回后由服务端查询确认。查不到就返回 waiting，绝不自动再次发起支付。"""
        if purchase.status == "confirmed":
            return {"state": "paid", "remaining": self.balance(purchase.user_id) if purchase.product == "count" else None}
        if purchase.product == "count":
            remaining = self.balance(purchase.user_id)
            if remaining is None:
                return {"state": "unknown", "remaining": None}
            if remaining > (purchase.remaining_before or 0):
                purchase.status = "confirmed"
                db.commit()
                log_event(db, purchase.user_id, "paid_detected", {"product": "count", "sku": purchase.sku_id})
                return {"state": "paid", "remaining": remaining}
            return {"state": "waiting", "remaining": remaining}
        decision = self.monthly_decision(purchase.user_id, force=True) or {}
        if decision.get("decision") == "ALLOW":
            purchase.status = "confirmed"
            db.commit()
            log_event(db, purchase.user_id, "paid_detected", {"product": "monthly"})
            return {"state": "paid", "valid_until": decision.get("valid_until")}
        if decision.get("decision") == "UNKNOWN":
            return {"state": "unknown"}
        return {"state": "waiting"}

    # ------------------------------------------------------------ 交付核销
    def unlock(self, db: Session, user: User, photo: Photo, method: str = "auto") -> dict[str, Any]:
        """调用前，调用方必须已经在服务端生成好无水印成品。"""
        with _locks.get(photo.id):
            db.refresh(photo)
            if photo.unlocked:
                return {"state": "unlocked"}
            last = (db.query(Consume).filter_by(photo_id=photo.id).order_by(Consume.attempt.desc()).first())
            if last and last.status == "succeeded":
                mark_unlocked(db, photo, "quota")
                return {"state": "unlocked"}
            if last and last.status in ("pending", "unknown"):
                state = self._resolve(db, last)
                if state == "succeeded":
                    mark_unlocked(db, photo, "quota")
                    return {"state": "unlocked"}
                if state not in ("failed", "insufficient"):
                    return {"state": "confirming"}

            if method == "free":
                if user.free_credits <= 0:
                    return {"state": "error", "message": "没有可用的免费次数"}
                user.free_credits -= 1
                db.commit()
                mark_unlocked(db, photo, "free")
                return {"state": "unlocked"}

            if self.monthly_product and db.query(Purchase).filter_by(user_id=user.id, product="monthly").first():
                decision = self.monthly_decision(user.id) or {}
                if decision.get("decision") == "ALLOW":
                    mark_unlocked(db, photo, "monthly")
                    return {"state": "unlocked"}

            if not self.enabled:
                return {"state": "error", "message": "支付暂未开通"}
            remaining = self.balance(user.id)
            if remaining is None:
                return {"state": "error", "message": "余额查询失败，请稍后重试"}
            if remaining < 1:
                return {"state": "need_purchase", "remaining": remaining}

            attempt = (last.attempt + 1) if last else 1
            consume = Consume(
                out_request_no=f"cs{photo.id[2:]}{attempt:02d}",  # 每张照片每次尝试唯一，绝不复用
                user_id=user.id, photo_id=photo.id, out_product_id=self.count_product, amount=1,
                consume_reason=CONSUME_REASON, attempt=attempt, status="pending",
            )
            db.add(consume)
            db.commit()  # 先落库再核销
            state = self._verify(db, consume)
            if state == "succeeded":
                mark_unlocked(db, photo, "quota")
                return {"state": "unlocked", "remaining": consume.remaining}
            if state == "insufficient":
                return {"state": "need_purchase", "remaining": 0}
            if state == "failed":
                return {"state": "error", "message": "核销未成功，次数未扣减，请稍后重试"}
            return {"state": "confirming"}

    def _verify(self, db: Session, c: Consume) -> str:
        c.tries += 1
        try:
            node = self.client.quota_verify(c.out_request_no, c.out_product_id, c.user_id, c.amount,  # type: ignore[union-attr]
                                            c.consume_reason)
        except GatewayError as exc:
            c.last_error = str(exc)[:500]
            if exc.sub_code == QUOTA_INSUFFICIENT:
                c.status = "failed"
                db.commit()
                return "insufficient"
            if exc.unknown or exc.sub_code == CONSUME_CONFLICT:
                self._defer(db, c)
                return "unknown"
            c.status = "failed"
            db.commit()
            log.error("quota.verify 业务失败 %s: %s", c.out_request_no, exc)
            return "failed"
        return self._apply(db, c, node)

    def _apply(self, db: Session, c: Consume, node: dict[str, Any]) -> str:
        status = node.get("consume_status")
        if status == "SUCCEEDED":
            c.status = "succeeded"
            c.consumed = node.get("consumed")
            c.remaining = node.get("remaining")
            c.next_check_at = None
            db.commit()
            return "succeeded"
        if status == "FAILED":
            c.status = "failed"
            db.commit()
            return "failed"
        # PROCESSING 或缺失：待确认，不补零、不推断
        self._defer(db, c)
        return "unknown"

    @staticmethod
    def _defer(db: Session, c: Consume) -> None:
        c.status = "unknown"
        c.next_check_at = utcnow() + timedelta(seconds=min(600, 3 * 2 ** min(c.tries, 8)))
        db.commit()

    def _resolve(self, db: Session, c: Consume) -> str:
        """恢复一笔待确认的核销：pending 用原参数重发 verify；unknown 先 refresh。"""
        if c.status == "pending":
            return self._verify(db, c)
        try:
            node = self.client.quota_refresh(c.out_request_no, c.out_product_id, c.user_id)  # type: ignore[union-attr]
        except GatewayError as exc:
            c.last_error = str(exc)[:500]
            if exc.sub_code == CONSUME_NOT_FOUND and c.tries < 8:
                # 未找到不代表没执行：用完全相同的原参数重试 verify（幂等）
                return self._verify(db, c)
            c.tries += 1
            self._defer(db, c)
            return "unknown"
        return self._apply(db, c, node)

    def reconcile(self) -> int:
        """后台定时恢复待确认的核销，成功后给照片解锁。返回处理条数。"""
        if not self.enabled:
            return 0
        done = 0
        with session_scope() as db:
            now = utcnow()
            rows = (
                db.query(Consume)
                .filter(Consume.status.in_(["pending", "unknown"]))
                .filter((Consume.next_check_at.is_(None)) | (Consume.next_check_at <= now))
                .filter(Consume.created_at >= now - timedelta(days=7))
                .limit(50)
                .all()
            )
            for c in rows:
                if c.status == "pending" and c.created_at > now - timedelta(seconds=20):
                    continue  # 可能正在被请求线程处理
                with _locks.get(c.photo_id):
                    db.refresh(c)
                    if c.status not in ("pending", "unknown"):
                        continue
                    state = self._resolve(db, c)
                    if state == "succeeded":
                        photo = db.get(Photo, c.photo_id)
                        if photo and not photo.deleted:
                            mark_unlocked(db, photo, "quota")
                    done += 1
        return done


def new_purchase_token(out_request_no: str) -> str:
    return sign(out_request_no, 16)
