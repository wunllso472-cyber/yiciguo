"""运行配置：全部来自环境变量（可放在 backend/.env），私钥等敏感信息不写进代码。"""
from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parent.parent
PROJECT_DIR = BACKEND_DIR.parent


def _load_dotenv(path: Path) -> None:
    """极简 .env 读取：KEY=VALUE，已存在的环境变量优先。"""
    if not path.exists():
        return
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key, value = key.strip(), value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
            value = value[1:-1]
        os.environ.setdefault(key, value)


_load_dotenv(BACKEND_DIR / ".env")


def _env(name: str, default: str = "") -> str:
    return os.environ.get(name, default).strip()


def _int(name: str, default: int) -> int:
    value = _env(name)
    return int(value) if value else default


def _bool(name: str, default: bool) -> bool:
    value = _env(name).lower()
    if not value:
        return default
    return value in {"1", "true", "yes", "on"}


def _read_key(name: str) -> str:
    """私钥/公钥：优先 *_FILE 指向的文件，其次环境变量本身。"""
    file_path = _env(f"{name}_FILE")
    if file_path:
        return Path(file_path).read_text(encoding="utf-8").strip()
    return _env(name)


@dataclass(frozen=True)
class Settings:
    env: str
    base_url: str
    secret_key: str
    data_dir: Path
    models_dir: Path
    frontend_dist: Path
    font_path: str
    photo_ttl_hours: int
    max_upload_mb: int
    workers: int
    matting_model: str
    pay_mode: str  # mock | nowpay | off
    alipay_app_id: str
    alipay_private_key: str
    alipay_public_key: str
    alipay_gateway: str
    alipay_app_auth_token: str
    nowpay_product_count: str
    nowpay_product_monthly: str
    admin_token: str
    showcase_url: str
    redo_days: int
    invite_reward_cap: int

    @property
    def is_prod(self) -> bool:
        return self.env == "prod"

    @property
    def https(self) -> bool:
        return self.base_url.startswith("https://")


def load_settings() -> Settings:
    env = _env("YCG_ENV", "dev")
    secret = _env("YCG_SECRET_KEY")
    if not secret:
        if env == "prod":
            raise RuntimeError("生产环境必须设置 YCG_SECRET_KEY")
        secret = "dev-only-secret-change-me"
    pay_mode = _env("YCG_PAY_MODE", "mock").lower()
    if env == "prod" and pay_mode == "mock":
        raise RuntimeError("生产环境禁止使用模拟支付（YCG_PAY_MODE=mock）")
    data_dir = Path(_env("YCG_DATA_DIR", str(BACKEND_DIR / "data")))
    return Settings(
        env=env,
        base_url=_env("YCG_BASE_URL", "http://127.0.0.1:8000").rstrip("/"),
        secret_key=secret,
        data_dir=data_dir,
        models_dir=Path(_env("YCG_MODELS_DIR", str(BACKEND_DIR / "models"))),
        frontend_dist=Path(_env("YCG_FRONTEND_DIST", str(PROJECT_DIR / "frontend" / "dist"))),
        font_path=_env("YCG_FONT_PATH"),
        photo_ttl_hours=_int("YCG_PHOTO_TTL_HOURS", 24),
        max_upload_mb=_int("YCG_MAX_UPLOAD_MB", 15),
        workers=_int("YCG_WORKERS", 2),
        matting_model=_env("YCG_MATTING_MODEL", "modnet_photographic_portrait_matting.onnx"),
        pay_mode=pay_mode,
        alipay_app_id=_env("ALIPAY_APP_ID"),
        alipay_private_key=_read_key("ALIPAY_PRIVATE_KEY"),
        alipay_public_key=_read_key("ALIPAY_PUBLIC_KEY"),
        alipay_gateway=_env("ALIPAY_GATEWAY", "https://openapi.alipay.com/gateway.do"),
        alipay_app_auth_token=_env("ALIPAY_APP_AUTH_TOKEN"),
        nowpay_product_count=_env("NOWPAY_PRODUCT_COUNT"),
        nowpay_product_monthly=_env("NOWPAY_PRODUCT_MONTHLY"),
        admin_token=_env("YCG_ADMIN_TOKEN"),
        showcase_url=_env("YCG_SHOWCASE_URL", "https://aipay.alipay.com/community/events/payathon-2026"),
        redo_days=_int("YCG_REDO_DAYS", 7),
        invite_reward_cap=_int("YCG_INVITE_REWARD_CAP", 5),
    )


settings = load_settings()
