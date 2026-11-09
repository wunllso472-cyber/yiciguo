"""端到端：同意 → 上传 → 预审 → 需购买 → 模拟支付 → 返回确认自动解锁 → 下载全部规格 → 重做 → 删除 → 取件码找回。"""
import io
import re
from urllib.parse import urlparse

import numpy as np
from PIL import Image

from conftest import wait_ready


def _consent(client):
    me = client.get("/api/me").json()
    r = client.post("/api/me/consent", json={"version": me["consent_version"]})
    assert r.status_code == 200 and r.json()["consent"]
    return r.json()


def _upload(client, data: bytes, spec="js-sk-2027", bg="white", **extra):
    files = {"file": ("me.jpg", data, "image/jpeg")}
    return client.post("/api/photos", files=files, data={"spec_key": spec, "bg": bg, **extra})


def test_specs_and_seo(client):
    r = client.get("/api/specs", params={"q": "国考"})
    assert r.status_code == 200 and r.json()["items"][0]["id"] == "gk-2027"
    assert client.get("/api/specs/gk-2027").json()["official_tool"]["required"]
    assert client.get("/api/specs/nope").status_code == 404
    assert client.post("/api/specs/custom", json={"width": 358, "height": 441, "kb_min": 14, "kb_max": 40}).json()["custom"]
    assert "spec/js-sk-2027" in client.get("/sitemap.xml").text


def test_full_paid_flow(client, portrait_bytes):
    assert _upload(client, portrait_bytes).status_code == 403  # 未同意隐私规则
    me = _consent(client)
    r = _upload(client, portrait_bytes)
    assert r.status_code == 200
    pid = r.json()["id"]
    photo = wait_ready(client, pid)
    assert photo["status"] == "ready", photo
    assert photo["report"]["overall"] in ("pass", "warn")
    assert all(v["status"] == "pass" for v in photo["validation"])
    assert photo["output"]["kb"] <= 20
    assert "downloads" not in photo

    prev = client.get(photo["preview_url"])
    assert prev.status_code == 200 and prev.headers["content-type"] == "image/jpeg"
    # 未解锁不能下载无水印图（篡改 kind 会让签名失效）
    assert client.get(photo["preview_url"].replace("kind=preview", "kind=photo")).status_code == 403

    r = client.post(f"/api/photos/{pid}/unlock", json={})
    assert r.json()["result"]["state"] == "need_purchase"
    assert r.json()["offers"]["count"]["purchasable"]

    buy = client.post("/api/pay/purchase", json={"product": "count", "sku_id": "S_MOCK_1", "photo_id": pid}).json()
    again = client.post("/api/pay/purchase", json={"product": "count", "sku_id": "S_MOCK_1", "photo_id": pid}).json()
    assert again["out_request_no"] == buy["out_request_no"]  # 重复点击复用
    assert client.get(f"/api/pay/purchase/{buy['out_request_no']}").json()["pay"]["state"] == "waiting"

    link_path = urlparse(buy["purchase_url"]).path
    assert client.get(link_path).status_code == 200
    r = client.post(f"{link_path}/confirm", data={"sku_id": "S_MOCK_1"}, follow_redirects=False)
    assert r.status_code == 303 and "/r/" in r.headers["location"]

    st = client.get(f"/api/pay/purchase/{buy['out_request_no']}").json()
    assert st["pay"]["state"] == "paid" and st["unlock"]["state"] == "unlocked"
    photo = st["photo"]
    assert photo["unlocked"] and photo["unlock_type"] == "quota"

    f = client.get(photo["downloads"]["photo"] + "&dl=1")
    assert f.status_code == 200 and "attachment" in f.headers["content-disposition"]
    assert len(f.content) <= 20 * 1000
    im = Image.open(io.BytesIO(f.content))
    assert im.size == (413, 531) and len(im.getexif()) == 0

    # 同一张照片切换到其他规格，不再扣次数
    sel = client.post(f"/api/photos/{pid}/select", json={"spec_key": "visa-us", "bg": "white"}).json()
    assert sel["unlocked"] and Image.open(io.BytesIO(client.get(sel["downloads"]["photo"]).content)).size == (600, 600)
    layout = client.get(sel["downloads"]["layout"])
    assert layout.status_code == 200 and Image.open(io.BytesIO(layout.content)).size[0] in (1200, 1800)
    bal = client.get("/api/pay/balance").json()
    assert bal["remaining"] == 0

    # 支付返回页：凭签名访问（模拟在支付宝 App 里打开，没有原 Cookie）
    loc = urlparse(r.headers["location"])
    token = re.search(r"t=([^&]+)", loc.query).group(1)
    from fastapi.testclient import TestClient

    other = TestClient(client.app)
    ret = other.get(f"/api/pay/return/{buy['out_request_no']}", params={"t": token}).json()
    assert ret["pay"]["state"] == "paid" and ret["photo"]["unlocked"]
    assert other.get(f"/api/pay/return/{buy['out_request_no']}", params={"t": "bad"}).status_code == 403

    # 驳回免费重做：1 次
    r = _upload(client, portrait_bytes, spec="js-sk-2027", redo_of=pid)
    assert r.status_code == 200
    redo = wait_ready(client, r.json()["id"])
    assert redo["unlocked"] and redo["unlock_type"] == "redo"
    assert _upload(client, portrait_bytes, redo_of=pid).status_code == 400

    # 取件码换设备找回
    fresh = TestClient(client.app)
    restored = fresh.post("/api/me/restore", json={"code": me["pickup_code"].lower()})
    assert restored.status_code == 200
    ids = [p["id"] for p in fresh.get("/api/photos").json()["items"]]
    assert pid in ids

    # 立即删除
    assert client.delete(f"/api/photos/{pid}").status_code == 200
    assert client.get(f"/api/photos/{pid}").status_code == 410

    stats = client.get("/api/admin/stats", headers={"Authorization": "Bearer test-admin"}).json()
    assert stats["paying_users_consumed"] >= 1
    assert client.get("/api/admin/stats").status_code == 401


def test_no_face_photo_is_rejected(client):
    _consent(client)
    rgb = np.tile(np.linspace(40, 220, 900, dtype=np.uint8)[None, :, None], (1100, 1, 3))
    buf = io.BytesIO()
    Image.fromarray(rgb).save(buf, "JPEG")
    pid = _upload(client, buf.getvalue()).json()["id"]
    photo = wait_ready(client, pid)
    assert photo["status"] == "rejected"
    assert photo["report"]["items"][0]["id"] == "no_face"
    assert client.post(f"/api/photos/{pid}/unlock", json={}).status_code == 400


def test_invite_reward(client, portrait_bytes):
    from fastapi.testclient import TestClient

    inviter = _consent(client)
    friend = TestClient(client.app)
    _consent(friend)
    assert friend.post("/api/me/invite", json={"code": inviter["invite_code"]}).json()["ok"]
    pid = _upload(friend, portrait_bytes, spec="cun1", bg="blue").json()["id"]
    assert wait_ready(friend, pid)["status"] == "ready"
    assert friend.get("/api/me").json()["free_credits"] == 1
    assert client.get("/api/me").json()["free_credits"] >= 1
    r = friend.post(f"/api/photos/{pid}/unlock", json={"method": "free"}).json()
    assert r["result"]["state"] == "unlocked" and r["photo"]["unlock_type"] == "free"
