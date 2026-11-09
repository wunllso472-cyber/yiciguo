"""测试环境：独立临时数据目录 + 模拟支付。必须在导入 app 之前设置环境变量。

fixtures/portrait*.jpg 来自 NASA 官方肖像（公有领域，Wikimedia Commons），仅用于测试。
"""
import os
import pathlib
import sys
import tempfile
import time

TMP = tempfile.mkdtemp(prefix="ycg_test_")
os.environ["YCG_DATA_DIR"] = TMP
os.environ["YCG_PAY_MODE"] = "mock"
os.environ["YCG_ADMIN_TOKEN"] = "test-admin"
os.environ["YCG_BASE_URL"] = "http://testserver"
os.environ["YCG_ENV"] = "dev"
os.environ.pop("YCG_DATABASE_URL", None)

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import pytest  # noqa: E402

FIXTURES = ROOT / "tests" / "fixtures"


@pytest.fixture(scope="session")
def app():
    from app.db import init_db
    from app.main import app as fastapi_app

    init_db()
    return fastapi_app


@pytest.fixture()
def client(app):
    from fastapi.testclient import TestClient

    with TestClient(app) as c:
        yield c


@pytest.fixture(scope="session")
def portrait_bytes() -> bytes:
    return (FIXTURES / "portrait.jpg").read_bytes()


def wait_ready(client, photo_id: str, timeout: float = 60) -> dict:
    deadline = time.time() + timeout
    while time.time() < deadline:
        r = client.get(f"/api/photos/{photo_id}")
        assert r.status_code == 200, r.text
        data = r.json()
        if data["status"] not in ("queued", "processing"):
            return data
        time.sleep(0.3)
    raise AssertionError("照片处理超时")
