"""人像抠图：MODNet（Apache-2.0）ONNX，本地 CPU 推理，不调用任何第三方 API。"""
from __future__ import annotations

from pathlib import Path

import cv2
import numpy as np

from .face import FaceResult


class Matter:
    def __init__(self, model_path: Path):
        import onnxruntime as ort

        opts = ort.SessionOptions()
        opts.intra_op_num_threads = 2
        # 关掉内存池和内存规划：推理完立即归还中间结果占用的内存（约 150MB），小内存实例不会被撑爆；
        # 代价是每次推理多几毫秒的分配开销
        opts.enable_cpu_mem_arena = False
        opts.enable_mem_pattern = False
        self.session = ort.InferenceSession(str(model_path), sess_options=opts, providers=["CPUExecutionProvider"])
        inp = self.session.get_inputs()[0]
        self.input_name = inp.name
        shape = inp.shape
        self.fixed = (shape[2], shape[3]) if isinstance(shape[2], int) and isinstance(shape[3], int) else None

    def _target_size(self, h: int, w: int) -> tuple[int, int]:
        if self.fixed:
            return int(self.fixed[0]), int(self.fixed[1])
        ref = 512
        if w >= h:
            rh, rw = ref, int(w / h * ref)
        else:
            rw, rh = ref, int(h / w * ref)
        scale = min(1.0, 1024 / max(rh, rw))
        rh, rw = int(rh * scale), int(rw * scale)
        return max(32, rh - rh % 32), max(32, rw - rw % 32)

    def predict(self, rgb: np.ndarray) -> np.ndarray:
        h, w = rgb.shape[:2]
        th, tw = self._target_size(h, w)
        x = cv2.resize(rgb, (tw, th), interpolation=cv2.INTER_AREA).astype(np.float32) / 255.0
        x = (x - 0.5) / 0.5
        x = x.transpose(2, 0, 1)[None]
        out = self.session.run(None, {self.input_name: x})[0][0, 0]
        alpha = cv2.resize(out, (w, h), interpolation=cv2.INTER_LINEAR)
        return np.clip(alpha, 0.0, 1.0).astype(np.float32)


def person_region(face: FaceResult, img_w: int, img_h: int) -> tuple[int, int, int, int]:
    """以人脸为中心估计人像区域（头顶留白 + 双肩），只对这块抠图，分辨率更高、干扰更少。"""
    x0, y0, x1, y1 = face.face_box
    fw, fh = x1 - x0, y1 - y0
    cx = (x0 + x1) / 2
    left = int(max(0, cx - fw * 2.3))
    right = int(min(img_w, cx + fw * 2.3))
    top = int(max(0, y0 - fh * 1.0))
    bottom = int(min(img_h, y1 + fh * 2.6))
    return left, top, right, bottom


def keep_main_component(alpha: np.ndarray, seed: tuple[int, int]) -> np.ndarray:
    """只保留与人脸相连的前景连通域，去掉旗帜、家具等误抠的孤立块。"""
    mask = (alpha > 0.5).astype(np.uint8)
    n, labels = cv2.connectedComponents(mask, connectivity=8)
    if n <= 2:
        return alpha
    sx, sy = seed
    sy = int(np.clip(sy, 0, alpha.shape[0] - 1))
    sx = int(np.clip(sx, 0, alpha.shape[1] - 1))
    label = labels[sy, sx]
    if label == 0:
        return alpha
    keep = (labels == label).astype(np.uint8)
    keep = cv2.dilate(keep, cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (9, 9)))
    keep = cv2.GaussianBlur(keep.astype(np.float32), (7, 7), 0)
    return alpha * np.clip(keep, 0, 1)


def matte_person(matter: Matter, rgb: np.ndarray, face: FaceResult) -> np.ndarray:
    h, w = rgb.shape[:2]
    left, top, right, bottom = person_region(face, w, h)
    crop = rgb[top:bottom, left:right]
    alpha_crop = matter.predict(crop)
    alpha = np.zeros((h, w), dtype=np.float32)
    alpha[top:bottom, left:right] = alpha_crop
    nose = face.pt(1)
    alpha = keep_main_component(alpha, (int(nose[0]), int(nose[1])))
    # 去掉背景里极淡的残影（原地计算，避免整幅图的临时副本）
    alpha -= np.float32(0.03)
    alpha *= np.float32(1 / 0.94)
    np.clip(alpha, 0.0, 1.0, out=alpha)
    return alpha
