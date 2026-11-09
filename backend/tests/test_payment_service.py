"""支付状态机：成功、余额不足、超时/处理中恢复、查不到记录、购买入口幂等、查询失败不当 0。"""
from datetime import timedelta

import pytest

from app.db import Consume, Photo, Purchase, SessionLocal, User, init_db, utcnow
from app.payments.gateway import GatewayError
from app.payments.service import PaymentService
from app.security import new_id, new_pickup_code


class FakeClient:
    def __init__(self):
        self.remaining = 0
        self.verify_script: list = []  # 依次返回/抛出
        self.refresh_script: list = []
        self.create_script: list = []
        self.calls: list[tuple] = []
        self.consumed: dict[str, dict] = {}

    def _next(self, script, default):
        item = script.pop(0) if script else default
        if isinstance(item, Exception):
            raise item
        return item() if callable(item) else item

    def charge_query(self, pid):
        return {"code": "10000", "capability_status": "ENABLED", "billing_mode": "QUANTITY", "quota_unit": "COUNT",
                "charging_options": [{"sku_id": "S1", "display_name": "1次", "price": "0.99", "quota_amount": 1}]}

    def quota_query(self, pid, buyer):
        self.calls.append(("query", buyer))
        if self.remaining is None:
            raise GatewayError("20000", "Service Currently Unavailable", unknown=True)
        return {"code": "10000", "remaining": self.remaining, "total": 9, "used": 0}

    def purchase_consult(self, pid, buyer, callback_url=None):
        return {"code": "10000", "decision": "PURCHASE_REQUIRED"}

    def purchase_create(self, req, pid, buyer, sku, cb):
        self.calls.append(("create", req, sku, cb))
        return self._next(self.create_script, {"code": "10000", "purchase_url": "alipays://x", "purchase_qr_code": "https://qr",
                                               "expire_time": "2099-01-01 10:30:00"})

    def _succeed(self, req):
        self.remaining -= 1
        res = {"code": "10000", "consume_status": "SUCCEEDED", "consumed": 1, "remaining": self.remaining}
        self.consumed[req] = res
        return res

    def quota_verify(self, req, pid, buyer, amount, reason):
        self.calls.append(("verify", req, amount))
        assert amount == 1
        if req in self.consumed:
            return self.consumed[req]
        return self._next(self.verify_script, lambda: self._succeed(req))

    def quota_refresh(self, req, pid, buyer):
        self.calls.append(("refresh", req))
        return self._next(self.refresh_script, lambda: self.consumed.get(req) or (_ for _ in ()).throw(
            GatewayError("40004", "x", "CONSUME_REQUEST_NOT_FOUND")))


@pytest.fixture()
def env():
    init_db()
    db = SessionLocal()
    user = User(id=new_id("u", 10), pickup_code=new_pickup_code(), invite_code=new_pickup_code(6))
    photo = Photo(id=new_id("ph", 10), user_id=user.id, spec_key="cun1", bg="white", status="ready",
                  expires_at=utcnow() + timedelta(hours=24))
    db.add_all([user, photo])
    db.commit()
    client = FakeClient()
    svc = PaymentService(client, "np_count", "", "https://example.com", "nowpay")
    yield db, user, photo, client, svc
    db.close()


def test_unlock_success(env):
    db, user, photo, client, svc = env
    client.remaining = 1
    assert svc.unlock(db, user, photo)["state"] == "unlocked"
    db.refresh(photo)
    assert photo.unlocked and photo.unlock_type == "quota"
    c = db.query(Consume).filter_by(photo_id=photo.id).one()
    assert c.status == "succeeded" and c.remaining == 0
    # 再次解锁不会再核销
    assert svc.unlock(db, user, photo)["state"] == "unlocked"
    assert sum(1 for x in client.calls if x[0] == "verify") == 1


def test_need_purchase_when_no_quota(env):
    db, user, photo, client, svc = env
    client.remaining = 0
    assert svc.unlock(db, user, photo)["state"] == "need_purchase"
    assert not any(x[0] == "verify" for x in client.calls)


def test_balance_failure_is_not_zero(env):
    db, user, photo, client, svc = env
    client.remaining = None
    r = svc.unlock(db, user, photo)
    assert r["state"] == "error"
    assert svc.balance(user.id) is None


def test_timeout_then_refresh_recovers(env):
    db, user, photo, client, svc = env
    client.remaining = 1

    def timeout_but_executed():
        client._succeed(client.calls[-1][1])  # 服务端其实扣成功了
        raise GatewayError("NETWORK", "timeout", unknown=True)

    client.verify_script = [timeout_but_executed]
    assert svc.unlock(db, user, photo)["state"] == "confirming"
    c = db.query(Consume).filter_by(photo_id=photo.id).one()
    assert c.status == "unknown"
    # 再点一次：用原请求号 refresh，不会换号重扣
    assert svc.unlock(db, user, photo)["state"] == "unlocked"
    reqs = {x[1] for x in client.calls if x[0] in ("verify", "refresh")}
    assert reqs == {c.out_request_no}
    assert client.remaining == 0


def test_processing_then_background_reconcile(env):
    db, user, photo, client, svc = env
    client.remaining = 1
    client.verify_script = [{"code": "10000", "consume_status": "PROCESSING"}]
    assert svc.unlock(db, user, photo)["state"] == "confirming"
    c = db.query(Consume).filter_by(photo_id=photo.id).one()
    # 服务端最终处理成功
    client._succeed(c.out_request_no)
    c.next_check_at = utcnow() - timedelta(seconds=1)
    db.commit()
    assert svc.reconcile() >= 1
    db.refresh(photo)
    assert photo.unlocked


def test_refresh_not_found_retries_same_request(env):
    db, user, photo, client, svc = env
    client.remaining = 1
    client.verify_script = [GatewayError("NETWORK", "timeout", unknown=True)]  # 请求根本没到达
    assert svc.unlock(db, user, photo)["state"] == "confirming"
    c = db.query(Consume).filter_by(photo_id=photo.id).one()
    assert svc.unlock(db, user, photo)["state"] == "unlocked"  # refresh 查不到 → 原参数重试 verify
    verifies = [x for x in client.calls if x[0] == "verify"]
    assert len(verifies) == 2 and all(v[1] == c.out_request_no for v in verifies)
    assert client.remaining == 0


def test_failed_then_new_attempt_after_purchase(env):
    db, user, photo, client, svc = env
    client.remaining = 1
    client.verify_script = [GatewayError("40004", "Business Failed", "NOW_PAY_QUOTA_INSUFFICIENT")]
    assert svc.unlock(db, user, photo)["state"] == "need_purchase"
    client.remaining = 1
    assert svc.unlock(db, user, photo)["state"] == "unlocked"
    rows = db.query(Consume).filter_by(photo_id=photo.id).order_by(Consume.attempt).all()
    assert [r.status for r in rows] == ["failed", "succeeded"]
    assert rows[0].out_request_no != rows[1].out_request_no


def test_purchase_reuse_and_retry_same_request_no(env):
    db, user, photo, client, svc = env
    client.create_script = [GatewayError("40004", "x", "NOW_PAY_PURCHASE_LINK_CREATING")]
    p1 = svc.create_purchase(db, user.id, "count", "S1", photo.id)
    creates = [x for x in client.calls if x[0] == "create"]
    assert len(creates) == 2 and creates[0][1] == creates[1][1] == p1.out_request_no
    assert p1.callback_url.startswith("https://example.com/r/")
    p2 = svc.create_purchase(db, user.id, "count", "S1", photo.id)
    assert p2.out_request_no == p1.out_request_no  # 重复点击复用有效入口


def test_check_purchase_detects_payment(env):
    db, user, photo, client, svc = env
    client.remaining = 0
    p = svc.create_purchase(db, user.id, "count", "S1", photo.id)
    assert svc.check_purchase(db, p)["state"] == "waiting"
    client.remaining = 1
    assert svc.check_purchase(db, p)["state"] == "paid"
    svc.unlock(db, user, photo)
    # 已确认的订单在额度用掉后仍显示已支付
    assert svc.check_purchase(db, db.get(Purchase, p.out_request_no))["state"] == "paid"
