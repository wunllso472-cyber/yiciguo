"""数据库：SQLite（WAL），SQLAlchemy 2.0。生产可通过 YCG_DATABASE_URL 换成 Postgres。"""
from __future__ import annotations

import os
from contextlib import contextmanager
from datetime import datetime, timezone
from typing import Iterator

from sqlalchemy import (
    Boolean,
    DateTime,
    Integer,
    String,
    Text,
    create_engine,
    event,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, Session, mapped_column, sessionmaker

from .config import settings


def utcnow() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


class Base(DeclarativeBase):
    pass


class User(Base):
    __tablename__ = "users"
    id: Mapped[str] = mapped_column(String(40), primary_key=True)  # 即 external_buyer_id
    pickup_code: Mapped[str] = mapped_column(String(16), unique=True, index=True)
    invite_code: Mapped[str] = mapped_column(String(16), unique=True, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    last_seen_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    consent_version: Mapped[str | None] = mapped_column(String(16), nullable=True)
    consent_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    free_credits: Mapped[int] = mapped_column(Integer, default=0)
    invited_by: Mapped[str | None] = mapped_column(String(40), nullable=True)
    invite_rewarded: Mapped[bool] = mapped_column(Boolean, default=False)
    invite_reward_count: Mapped[int] = mapped_column(Integer, default=0)


class Photo(Base):
    __tablename__ = "photos"
    id: Mapped[str] = mapped_column(String(40), primary_key=True)
    user_id: Mapped[str] = mapped_column(String(40), index=True)
    # queued -> processing -> ready | rejected | failed ; deleted
    status: Mapped[str] = mapped_column(String(16), default="queued")
    stage: Mapped[str] = mapped_column(String(32), default="")
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    spec_key: Mapped[str] = mapped_column(String(128))
    bg: Mapped[str] = mapped_column(String(32), default="white")
    analysis_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    expires_at: Mapped[datetime] = mapped_column(DateTime, index=True)
    unlocked: Mapped[bool] = mapped_column(Boolean, default=False)
    unlock_type: Mapped[str | None] = mapped_column(String(16), nullable=True)  # quota|monthly|free|redo
    unlocked_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    redo_of: Mapped[str | None] = mapped_column(String(40), nullable=True)
    redo_used: Mapped[bool] = mapped_column(Boolean, default=False)
    deleted: Mapped[bool] = mapped_column(Boolean, default=False, index=True)


class Purchase(Base):
    """一次“获取购买入口”请求（purchase.create），不是支付宝交易。"""

    __tablename__ = "purchases"
    out_request_no: Mapped[str] = mapped_column(String(64), primary_key=True)
    user_id: Mapped[str] = mapped_column(String(40), index=True)
    photo_id: Mapped[str | None] = mapped_column(String(40), nullable=True)
    product: Mapped[str] = mapped_column(String(16))  # count | monthly
    out_product_id: Mapped[str] = mapped_column(String(128))
    sku_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    callback_url: Mapped[str | None] = mapped_column(String(512), nullable=True)
    purchase_url: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    qr_code: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    expire_time: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)  # 北京时间
    # creating -> created -> confirmed | error
    status: Mapped[str] = mapped_column(String(16), default="creating")
    remaining_before: Mapped[int | None] = mapped_column(Integer, nullable=True)
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, onupdate=utcnow)


class Consume(Base):
    """一次额度核销（quota.verify），out_request_no 一旦发出就绝不换号重扣。"""

    __tablename__ = "consumes"
    out_request_no: Mapped[str] = mapped_column(String(64), primary_key=True)
    user_id: Mapped[str] = mapped_column(String(40), index=True)
    photo_id: Mapped[str] = mapped_column(String(40), index=True)
    out_product_id: Mapped[str] = mapped_column(String(128))
    amount: Mapped[int] = mapped_column(Integer, default=1)
    consume_reason: Mapped[str] = mapped_column(String(256))
    attempt: Mapped[int] = mapped_column(Integer, default=1)
    # pending -> succeeded | failed | unknown(processing/超时，待确认)
    status: Mapped[str] = mapped_column(String(16), default="pending")
    consumed: Mapped[int | None] = mapped_column(Integer, nullable=True)
    remaining: Mapped[int | None] = mapped_column(Integer, nullable=True)
    tries: Mapped[int] = mapped_column(Integer, default=0)
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    next_check_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, onupdate=utcnow)


class Event(Base):
    __tablename__ = "events"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[str | None] = mapped_column(String(40), index=True, nullable=True)
    name: Mapped[str] = mapped_column(String(40), index=True)
    props: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, index=True)


class SpecFeedback(Base):
    __tablename__ = "spec_feedback"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[str | None] = mapped_column(String(40), nullable=True)
    spec_id: Mapped[str] = mapped_column(String(64))
    content: Mapped[str] = mapped_column(Text)
    url: Mapped[str | None] = mapped_column(String(512), nullable=True)
    contact: Mapped[str | None] = mapped_column(String(128), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


# ---- 以下三张表只在 YCG_PAY_MODE=mock（本地开发/演示）时使用 ----
class MockQuota(Base):
    __tablename__ = "mock_quota"
    buyer: Mapped[str] = mapped_column(String(128), primary_key=True)
    product: Mapped[str] = mapped_column(String(128), primary_key=True)
    total: Mapped[int] = mapped_column(Integer, default=0)
    used: Mapped[int] = mapped_column(Integer, default=0)
    valid_until: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)


class MockLink(Base):
    __tablename__ = "mock_links"
    id: Mapped[str] = mapped_column(String(40), primary_key=True)
    out_request_no: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    buyer: Mapped[str] = mapped_column(String(128))
    product: Mapped[str] = mapped_column(String(128))
    sku_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    callback_url: Mapped[str | None] = mapped_column(String(512), nullable=True)
    status: Mapped[str] = mapped_column(String(16), default="open")  # open|paid|cancelled
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class MockConsume(Base):
    __tablename__ = "mock_consumes"
    out_request_no: Mapped[str] = mapped_column(String(64), primary_key=True)
    buyer: Mapped[str] = mapped_column(String(128))
    product: Mapped[str] = mapped_column(String(128))
    amount: Mapped[int] = mapped_column(Integer)
    consume_reason: Mapped[str] = mapped_column(String(256))
    status: Mapped[str] = mapped_column(String(16))
    consumed: Mapped[int | None] = mapped_column(Integer, nullable=True)
    remaining: Mapped[int | None] = mapped_column(Integer, nullable=True)
    update_time: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


def _database_url() -> str:
    url = os.environ.get("YCG_DATABASE_URL", "").strip()
    if url:
        return url
    settings.data_dir.mkdir(parents=True, exist_ok=True)
    return f"sqlite:///{(settings.data_dir / 'yiciguo.db').as_posix()}"


DATABASE_URL = _database_url()
engine = create_engine(
    DATABASE_URL,
    connect_args={"check_same_thread": False, "timeout": 30} if DATABASE_URL.startswith("sqlite") else {},
    pool_pre_ping=True,
)

if DATABASE_URL.startswith("sqlite"):

    @event.listens_for(engine, "connect")
    def _sqlite_pragmas(dbapi_conn, _record):  # pragma: no cover - 连接级设置
        cur = dbapi_conn.cursor()
        cur.execute("PRAGMA journal_mode=WAL")
        cur.execute("PRAGMA synchronous=NORMAL")
        cur.execute("PRAGMA busy_timeout=30000")
        cur.close()


SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


def init_db() -> None:
    Base.metadata.create_all(engine)


def get_db() -> Iterator[Session]:
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


@contextmanager
def session_scope() -> Iterator[Session]:
    db = SessionLocal()
    try:
        yield db
        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()
