"""图像处理：全部在本机 CPU 上完成，不调用任何第三方图像/大模型 API。"""
from __future__ import annotations

import threading
from pathlib import Path

from .face import FaceAnalyzer
from .matting import Matter

_lock = threading.Lock()
_face: FaceAnalyzer | None = None
_matter: Matter | None = None


class ModelMissingError(RuntimeError):
    pass


def _require(path: Path) -> Path:
    if not path.exists():
        raise ModelMissingError(f"缺少模型文件 {path}，请先运行 python scripts/download_models.py")
    return path


def get_engines(models_dir: Path, matting_model: str) -> tuple[FaceAnalyzer, Matter]:
    global _face, _matter
    with _lock:
        if _face is None:
            _face = FaceAnalyzer(_require(models_dir / "face_landmarker.task"))
        if _matter is None:
            _matter = Matter(_require(models_dir / matting_model))
    return _face, _matter
