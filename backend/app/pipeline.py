"""照片处理流水线：上传后分析（一次）+ 按规格/底色渲染（可多次，带缓存）。

磁盘上每张照片一个目录 data/photos/<photo_id>/：
  work.jpg   摆正后的工作图（不保留用户原图）
  alpha.png  抠图结果
  r_<hash>.*  某规格+底色的渲染结果：final.jpg（无水印，解锁后才可下载）、preview.jpg（水印）、meta.json
到期（默认 24 小时）后整个目录删除。
"""
from __future__ import annotations

import hashlib
import io
import json
import logging
import shutil
import threading
from collections import OrderedDict
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from datetime import timedelta
from pathlib import Path
from typing import Any

import cv2
import numpy as np
from PIL import Image

from .config import settings
from .db import Photo, session_scope, utcnow
from .imaging import get_engines
from .imaging.analysis import analyze
from .imaging.io import ImageLoadError, load_rgb
from .imaging.precheck import build_report, rejection_report
from .imaging.render import (
    clothing_rgb,
    encode_jpeg,
    plan_crop,
    print_layout,
    render,
    validate_output,
    watermark_preview,
)
from .specs import Spec, bg_name, bg_rgb, library

log = logging.getLogger("yiciguo.pipeline")

PHOTOS_DIR = settings.data_dir / "photos"
executor = ThreadPoolExecutor(max_workers=max(1, settings.workers), thread_name_prefix="photo")

_photo_locks: dict[str, threading.Lock] = {}
_photo_locks_guard = threading.Lock()


def photo_lock(photo_id: str) -> threading.Lock:
    with _photo_locks_guard:
        lock = _photo_locks.get(photo_id)
        if lock is None:
            if len(_photo_locks) > 2000:
                _photo_locks.clear()
            lock = _photo_locks[photo_id] = threading.Lock()
        return lock


def photo_dir(photo_id: str) -> Path:
    if not photo_id.isalnum():
        raise ValueError("bad photo id")
    return PHOTOS_DIR / photo_id


def delete_photo_files(photo_id: str) -> None:
    shutil.rmtree(photo_dir(photo_id), ignore_errors=True)
    _cache.pop(photo_id, None)


# ---------------------------------------------------------------- 工作图缓存（切换规格时免去重复解码）
class _LRU(OrderedDict):
    def __init__(self, cap: int):
        super().__init__()
        self.cap = cap
        self.guard = threading.Lock()

    def get_or_load(self, key: str, loader):
        with self.guard:
            if key in self:
                self.move_to_end(key)
                return self[key]
        value = loader()
        with self.guard:
            self[key] = value
            while len(self) > self.cap:
                self.popitem(last=False)
        return value

    def pop(self, key, default=None):
        with self.guard:
            return super().pop(key, default)


# 只缓存最近 2 张：解码一次只要几十毫秒，缓存太多反而长期占内存（2400px 一张约 17MB）
_cache = _LRU(2)


def _load_work(photo_id: str) -> tuple[np.ndarray, np.ndarray]:
    """返回工作图（uint8 RGB）和 alpha（float32 0–1）。缓存里的 alpha 存 uint8，用时再转换。"""
    def loader():
        d = photo_dir(photo_id)
        work = np.asarray(Image.open(d / "work.jpg").convert("RGB"))
        alpha_u8 = cv2.imread(str(d / "alpha.png"), cv2.IMREAD_GRAYSCALE)
        return work, alpha_u8

    work, alpha_u8 = _cache.get_or_load(photo_id, loader)
    return work, alpha_u8.astype(np.float32) * np.float32(1 / 255)


# ---------------------------------------------------------------- 上传后的分析
STAGES = {
    "queued": "排队中",
    "loading": "读取照片",
    "detect": "检测人脸与姿态",
    "matting": "AI 抠图",
    "render": "按规格生成与校验",
    "done": "完成",
}


def _set(photo_id: str, **fields: Any) -> None:
    with session_scope() as db:
        photo = db.get(Photo, photo_id)
        if photo is None:
            return
        for k, v in fields.items():
            setattr(photo, k, v)


def submit(photo_id: str, data: bytes) -> None:
    executor.submit(_process_safe, photo_id, data)


def _process_safe(photo_id: str, data: bytes) -> None:
    from . import hooks

    try:
        process(photo_id, data)
    except ImageLoadError as exc:
        _set(photo_id, status="failed", stage="done", error=str(exc))
        hooks.photo_rejected(photo_id)
    except Exception:  # noqa: BLE001
        log.exception("处理照片失败 %s", photo_id)
        _set(photo_id, status="failed", stage="done", error="处理失败，请稍后重试或换一张照片")
        hooks.photo_rejected(photo_id)


def process(photo_id: str, data: bytes) -> None:
    _set(photo_id, status="processing", stage="loading")
    rgb = load_rgb(data)
    del data
    face, matter = get_engines(settings.models_dir, settings.matting_model)
    _set(photo_id, stage="detect")
    # analyze 内部先检测再抠图；为了进度展示把阶段拆成两步上报
    result = analyze(rgb, face, matter)
    _set(photo_id, stage="matting")
    d = photo_dir(photo_id)
    d.mkdir(parents=True, exist_ok=True)
    if not result.ok:
        payload = {"reason": result.reason, "metrics": result.metrics,
                   "report": rejection_report(result.reason, result.metrics)}
        _set(photo_id, status="rejected", stage="done", analysis_json=json.dumps(payload, ensure_ascii=False))
        from . import hooks

        hooks.photo_rejected(photo_id)
        return
    Image.fromarray(result.work).save(d / "work.jpg", "JPEG", quality=95, subsampling=0)
    cv2.imwrite(str(d / "alpha.png"), np.clip(result.alpha * 255 + 0.5, 0, 255).astype(np.uint8))
    _cache.pop(photo_id)
    payload = {"geometry": result.geometry, "metrics": result.metrics}
    _set(photo_id, stage="render", analysis_json=json.dumps(payload, ensure_ascii=False))

    with session_scope() as db:
        photo = db.get(Photo, photo_id)
        spec_key, bg = photo.spec_key, photo.bg
    spec = library.get(spec_key) or library.get("cun1")
    get_render(photo_id, payload, spec, bg)
    _set(photo_id, status="ready", stage="done")
    from . import hooks

    hooks.photo_ready(photo_id)


# ---------------------------------------------------------------- 渲染
@dataclass
class RenderResult:
    key: str
    meta: dict[str, Any]
    dir: Path

    @property
    def final_path(self) -> Path:
        return self.dir / f"r_{self.key}_final.jpg"

    @property
    def preview_path(self) -> Path:
        return self.dir / f"r_{self.key}_preview.jpg"

    @property
    def layout_path(self) -> Path:
        return self.dir / f"r_{self.key}_layout.jpg"


def render_key(spec: Spec, bg: str) -> str:
    return hashlib.sha1(f"{spec.key}|{bg}|v2".encode()).hexdigest()[:12]


def get_render(photo_id: str, analysis: dict[str, Any], spec: Spec, bg: str) -> RenderResult:
    d = photo_dir(photo_id)
    key = render_key(spec, bg)
    meta_path = d / f"r_{key}.json"
    with photo_lock(photo_id):
        if meta_path.exists():
            return RenderResult(key, json.loads(meta_path.read_text(encoding="utf-8")), d)
        work, alpha = _load_work(photo_id)
        geometry, metrics = analysis["geometry"], analysis["metrics"]
        color = bg_rgb(bg)
        plan = plan_crop(geometry, spec)
        out = render(work, alpha, plan, color)
        # 输出尺寸可能因“最小像素”规格回退而变化，用实际尺寸校验
        eff = spec if (plan.out_w, plan.out_h) == (spec.width, spec.height) else _with_size(spec, plan.out_w, plan.out_h)
        encoded = encode_jpeg(out, eff)
        validation = validate_output(encoded.data, eff, color, plan)
        report = build_report(metrics, spec, bg, plan, encoded, clothing_rgb(work, alpha, geometry), color)
        (d / f"r_{key}_final.jpg").write_bytes(encoded.data)
        (d / f"r_{key}_preview.jpg").write_bytes(watermark_preview(out, settings.font_path))
        meta = {
            "spec_key": spec.key,
            "bg": bg,
            "bg_name": bg_name(bg),
            "width": plan.out_w,
            "height": plan.out_h,
            "kb": round(encoded.kb, 1),
            "quality": encoded.quality,
            "encode_ok": encoded.ok,
            "plan": plan.to_dict(),
            "validation": validation,
            "report": report,
        }
        meta_path.write_text(json.dumps(meta, ensure_ascii=False), encoding="utf-8")
        return RenderResult(key, meta, d)


def get_layout(photo_id: str, result: RenderResult, spec: Spec) -> Path:
    path = result.layout_path
    with photo_lock(photo_id):
        if not path.exists():
            rgb = np.asarray(Image.open(io.BytesIO(result.final_path.read_bytes())).convert("RGB"))
            path.write_bytes(print_layout(rgb, spec, settings.font_path))
    return path


def _with_size(spec: Spec, w: int, h: int) -> Spec:
    from dataclasses import replace

    return replace(spec, width=w, height=h)


def new_expiry():
    return utcnow() + timedelta(hours=settings.photo_ttl_hours)
