"""本地模拟的即刻收（仅开发/演示用，YCG_PAY_MODE=mock；生产环境启动时会拒绝该模式）。

行为尽量贴近真实接口：同一 out_request_no 幂等、参数不一致报冲突、核销原子扣减、
余额不足返回 NOW_PAY_QUOTA_INSUFFICIENT、refresh 查不到返回 CONSUME_REQUEST_NOT_FOUND。
托管购买页由本服务的 /mock/pay/<link_id> 模拟。
"""
from __future__ import annotations

import calendar
import threading
from datetime import datetime, timedelta, timezone
from typing import Any

from ..db import MockConsume, MockLink, MockQuota, session_scope, utcnow
from ..security import new_id
from .gateway import GatewayError
from .nowpay import CONSUME_CONFLICT, CONSUME_NOT_FOUND, ORDER_CONFLICT, QUOTA_INSUFFICIENT

MOCK_COUNT_PRODUCT = "np_mock_count"
MOCK_MONTHLY_PRODUCT = "np_mock_monthly"

MOCK_PRODUCTS: dict[str, dict[str, Any]] = {
    MOCK_COUNT_PRODUCT: {
        "product_name": "报名照导出（模拟）",
        "billing_mode": "QUANTITY",
        "quota_unit": "COUNT",
        "charging_options": [
            {"sku_id": "S_MOCK_1", "display_name": "1次", "price": "0.99", "quota_amount": 1},
            {"sku_id": "S_MOCK_3", "display_name": "3次", "price": "1.99", "quota_amount": 3},
            {"sku_id": "S_MOCK_10", "display_name": "10次", "price": "4.99", "quota_amount": 10},
        ],
    },
    MOCK_MONTHLY_PRODUCT: {
        "product_name": "备考季月卡（模拟）",
        "billing_mode": "ONE_TIME_DURATION",
        "charging_options": [
            {"sku_id": "S_MOCK_M", "display_name": "备考季月卡", "price": "9.90", "duration_period": "MONTH"},
        ],
    },
}

CN_TZ = timezone(timedelta(hours=8))
_lock = threading.Lock()


def _cn(dt: datetime) -> str:
    return (dt.replace(tzinfo=timezone.utc).astimezone(CN_TZ)).strftime("%Y-%m-%d %H:%M:%S")


def _add_month(dt: datetime) -> datetime:
    month = dt.month % 12 + 1
    year = dt.year + (1 if dt.month == 12 else 0)
    day = min(dt.day, calendar.monthrange(year, month)[1])
    return dt.replace(year=year, month=month, day=day)


def _ok(**fields: Any) -> dict[str, Any]:
    return {"code": "10000", "msg": "Success", **fields}


def _biz_error(sub_code: str, sub_msg: str) -> GatewayError:
    return GatewayError("40004", "Business Failed", sub_code, sub_msg)


class MockNowPayClient:
    def __init__(self, base_url: str):
        self.base_url = base_url.rstrip("/")

    # ---- 查询类
    def charge_query(self, product_id: str) -> dict[str, Any]:
        p = MOCK_PRODUCTS.get(product_id)
        if not p:
            return _ok(capability_status="NOT_CONFIGURED", charging_options=[])
        return _ok(capability_status="ENABLED", **p)

    def quota_query(self, product_id: str, buyer: str) -> dict[str, Any]:
        with session_scope() as db:
            q = db.get(MockQuota, (buyer, product_id))
            total, used = (q.total, q.used) if q else (0, 0)
        return _ok(quota_unit="COUNT", total=total, used=used, remaining=total - used, as_of_time=_cn(utcnow()))

    def purchase_consult(self, product_id: str, buyer: str, callback_url: str | None = None) -> dict[str, Any]:
        p = MOCK_PRODUCTS[product_id]
        with session_scope() as db:
            q = db.get(MockQuota, (buyer, product_id))
            if q and q.valid_until and q.valid_until > utcnow():
                start = q.valid_until
                return _ok(decision="ALLOW", capability_status="ENABLED", valid_from=_cn(utcnow()),
                           valid_until=_cn(start), charging_options=p["charging_options"])
        link = self._new_link(None, product_id, buyer, None, callback_url)
        return _ok(decision="PURCHASE_REQUIRED", capability_status="ENABLED", purchase_url=link,
                   purchase_qr_code=link, charging_options=p["charging_options"])

    # ---- 购买入口
    def _new_link(self, req_no: str | None, product_id: str, buyer: str, sku_id: str | None,
                  callback_url: str | None) -> str:
        with session_scope() as db:
            link = MockLink(id=new_id("ml", 8), out_request_no=req_no, buyer=buyer, product=product_id,
                            sku_id=sku_id, callback_url=callback_url)
            db.add(link)
        return f"{self.base_url}/mock/pay/{link.id}"

    def purchase_create(self, out_request_no: str, product_id: str, buyer: str, sku_id: str | None,
                        callback_url: str | None) -> dict[str, Any]:
        with _lock:
            with session_scope() as db:
                existing = db.query(MockLink).filter_by(out_request_no=out_request_no).first()
                if existing:
                    if (existing.buyer, existing.product, existing.sku_id, existing.callback_url) != (
                            buyer, product_id, sku_id, callback_url):
                        raise _biz_error(ORDER_CONFLICT, "同一幂等请求号对应的业务参数不一致")
                    url = f"{self.base_url}/mock/pay/{existing.id}"
                    expire = existing.created_at + timedelta(minutes=30)
                    return _ok(purchase_url=url, purchase_qr_code=url, expire_time=_cn(expire))
            url = self._new_link(out_request_no, product_id, buyer, sku_id, callback_url)
        return _ok(purchase_url=url, purchase_qr_code=url, expire_time=_cn(utcnow() + timedelta(minutes=30)))

    # ---- 模拟托管页的“支付成功”
    def complete_link(self, link_id: str, sku_id: str | None) -> MockLink | None:
        with _lock, session_scope() as db:
            link = db.get(MockLink, link_id)
            if link is None or link.status != "open":
                return link
            if link.created_at < utcnow() - timedelta(minutes=30):
                return link
            p = MOCK_PRODUCTS[link.product]
            sku = link.sku_id or sku_id or p["charging_options"][0]["sku_id"]
            option = next((o for o in p["charging_options"] if o["sku_id"] == sku), p["charging_options"][0])
            q = db.get(MockQuota, (link.buyer, link.product))
            if q is None:
                q = MockQuota(buyer=link.buyer, product=link.product, total=0, used=0)
                db.add(q)
            if p["billing_mode"] == "QUANTITY":
                q.total = (q.total or 0) + int(option["quota_amount"])
            else:
                now = utcnow()
                base = q.valid_until if q.valid_until and q.valid_until > now else now
                q.valid_until = _add_month(base)
            link.status = "paid"
            link.sku_id = sku
            return link

    def cancel_link(self, link_id: str) -> MockLink | None:
        with session_scope() as db:
            link = db.get(MockLink, link_id)
            if link and link.status == "open":
                link.status = "cancelled"
            return link

    def get_link(self, link_id: str) -> MockLink | None:
        with session_scope() as db:
            return db.get(MockLink, link_id)

    # ---- 核销
    def quota_verify(self, out_request_no: str, product_id: str, buyer: str, amount: int,
                     consume_reason: str) -> dict[str, Any]:
        if amount <= 0:
            raise _biz_error("INVALID_PARAMETER", "amount 必须为正整数")
        with _lock, session_scope() as db:
            existing = db.get(MockConsume, out_request_no)
            if existing:
                if (existing.buyer, existing.product, existing.amount) != (buyer, product_id, amount):
                    raise _biz_error(CONSUME_CONFLICT, "额度消费请求幂等冲突")
                return self._consume_result(existing)
            q = db.get(MockQuota, (buyer, product_id))
            remaining = (q.total - q.used) if q else 0
            if remaining < amount:
                raise _biz_error(QUOTA_INSUFFICIENT, "额度不足")
            q.used += amount
            rec = MockConsume(out_request_no=out_request_no, buyer=buyer, product=product_id, amount=amount,
                              consume_reason=consume_reason, status="SUCCEEDED", consumed=amount,
                              remaining=q.total - q.used, update_time=utcnow())
            db.add(rec)
            return self._consume_result(rec)

    def quota_refresh(self, out_request_no: str, product_id: str, buyer: str) -> dict[str, Any]:
        with session_scope() as db:
            rec = db.get(MockConsume, out_request_no)
            if rec is None or rec.buyer != buyer or rec.product != product_id:
                raise _biz_error(CONSUME_NOT_FOUND, "未找到匹配的幂等请求记录")
            return self._consume_result(rec)

    @staticmethod
    def _consume_result(rec: MockConsume) -> dict[str, Any]:
        out = _ok(consume_status=rec.status, consume_reason=rec.consume_reason, quota_unit="COUNT")
        if rec.status == "SUCCEEDED":
            out.update(consumed=rec.consumed, remaining=rec.remaining, update_time=_cn(rec.update_time))
        return out
