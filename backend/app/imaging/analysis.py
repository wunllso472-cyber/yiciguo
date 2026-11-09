"""上传后的一次性分析：人脸 → 摆正 → 抠图 → 头顶定位 → 预审指标。

结果（摆正后的图、alpha、几何信息、指标）缓存下来，之后切换任何规格/底色都只需要快速渲染。
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any

import cv2
import numpy as np

from . import face as F
from .face import FaceAnalyzer, FaceResult
from .matting import Matter, matte_person


@dataclass
class Analysis:
    ok: bool
    reason: str = ""  # ok=False 时的拒绝原因代码：no_face / multi_face / crown_cut
    work: np.ndarray | None = None  # 摆正后的 RGB
    alpha: np.ndarray | None = None  # float32 0..1
    geometry: dict[str, float] = field(default_factory=dict)
    metrics: dict[str, Any] = field(default_factory=dict)


def _poly_mask(shape: tuple[int, int], pts: np.ndarray) -> np.ndarray:
    mask = np.zeros(shape, dtype=np.uint8)
    cv2.fillPoly(mask, [np.round(pts).astype(np.int32)], 1)
    return mask.astype(bool)


def _circle_mask(shape: tuple[int, int], center: np.ndarray, radius: float) -> np.ndarray:
    mask = np.zeros(shape, dtype=np.uint8)
    cv2.circle(mask, (int(center[0]), int(center[1])), max(2, int(radius)), 1, -1)
    return mask.astype(bool)


def _rect_mask(shape: tuple[int, int], x0: float, y0: float, x1: float, y1: float) -> np.ndarray:
    h, w = shape
    mask = np.zeros(shape, dtype=bool)
    xa, xb = int(np.clip(min(x0, x1), 0, w)), int(np.clip(max(x0, x1), 0, w))
    ya, yb = int(np.clip(min(y0, y1), 0, h)), int(np.clip(max(y0, y1), 0, h))
    mask[ya:yb, xa:xb] = True
    return mask


class SkinModel:
    """以本人两颊颜色为基准的自适应肤色判定（YCrCb）。"""

    def __init__(self, ycc: np.ndarray, sample_mask: np.ndarray):
        pix = ycc[sample_mask].astype(np.float32)
        if len(pix) < 20:
            pix = ycc.reshape(-1, 3).astype(np.float32)
        self.mean = pix.mean(axis=0)
        self.std = pix.std(axis=0)

    def ratio(self, ycc: np.ndarray, mask: np.ndarray) -> float | None:
        pix = ycc[mask].astype(np.float32)
        if len(pix) < 20:
            return None
        tol_cr = max(7.0, 2.5 * self.std[1])
        tol_cb = max(7.0, 2.5 * self.std[2])
        skin = (
            (np.abs(pix[:, 1] - self.mean[1]) < tol_cr)
            & (np.abs(pix[:, 2] - self.mean[2]) < tol_cb)
            & (pix[:, 0] > self.mean[0] * 0.45)
        )
        return float(skin.mean())


def _find_crown(alpha: np.ndarray, fc: FaceResult) -> tuple[float, str, bool]:
    """在人脸宽度范围内自上而下找第一行“足够多前景”的位置作为头顶。"""
    x0, y0, x1, y1 = fc.face_box
    fw, fh = x1 - x0, y1 - y0
    band = alpha[:, int(max(0, x0 + 0.12 * fw)): int(min(alpha.shape[1], x1 - 0.12 * fw))]
    forehead_y = fc.pt(F.FOREHEAD_TOP)[1]
    if band.shape[1] < 4:
        return forehead_y - 0.3 * fh, "estimate", False
    need = max(3, int(0.05 * band.shape[1]))
    counts = (band > 0.5).sum(axis=1)
    rows = np.nonzero(counts[: int(forehead_y)] >= need)[0]
    if len(rows) == 0:
        return forehead_y - 0.3 * fh, "estimate", False
    crown = float(rows[0])
    gap = forehead_y - crown
    if gap < 0.04 * fh or gap > 1.1 * fh:
        # 抠图结果不合理（帽子/背景物体粘连），退回经验估计
        return forehead_y - 0.3 * fh, "estimate", crown <= 1
    return crown, "matte", crown <= 1


def _sharpness(gray: np.ndarray, box: tuple[float, float, float, float]) -> float:
    x0, y0, x1, y1 = (int(v) for v in box)
    h, w = gray.shape
    roi = gray[max(0, y0): min(h, y1), max(0, x0): min(w, x1)]
    if roi.size < 100:
        return 0.0
    scale = 200.0 / roi.shape[1]
    roi = cv2.resize(roi, (200, max(10, int(roi.shape[0] * scale))), interpolation=cv2.INTER_AREA)
    return float(cv2.Laplacian(roi, cv2.CV_64F).var())


def analyze(rgb: np.ndarray, analyzer: FaceAnalyzer, matter: Matter) -> Analysis:
    h, w = rgb.shape[:2]
    fc = analyzer.detect(rgb)
    if fc is None:
        return Analysis(ok=False, reason="no_face", metrics={"face_count": 0, "image_w": w, "image_h": h})
    if fc.count > 1:
        return Analysis(ok=False, reason="multi_face", metrics={"face_count": fc.count, "image_w": w, "image_h": h})

    # 1) 摆正：按两眼连线旋转（±15° 以内自动处理）
    roll = fc.roll
    rotated = False
    work = rgb
    if 0.8 < abs(roll) <= 15:
        left, right = fc.eye_centers
        center = (float((left[0] + right[0]) / 2), float((left[1] + right[1]) / 2))
        mat = cv2.getRotationMatrix2D(center, roll, 1.0)
        work = cv2.warpAffine(rgb, mat, (w, h), flags=cv2.INTER_CUBIC, borderMode=cv2.BORDER_REPLICATE)
        fc = fc.transformed(mat)
        rotated = True

    # 2) 抠图
    alpha = matte_person(matter, work, fc)

    # 3) 几何
    x0, y0, x1, y1 = fc.face_box
    fw, fh = x1 - x0, y1 - y0
    crown_y, crown_src, crown_cut = _find_crown(alpha, fc)
    chin_y = float(fc.pt(F.CHIN)[1])
    left_eye, right_eye = fc.eye_centers
    eye_y = float((left_eye[1] + right_eye[1]) / 2)
    cx = float((left_eye[0] + right_eye[0]) / 2 * 0.5 + fc.pt(F.NOSE_TIP)[0] * 0.25 + fc.pt(F.CHIN)[0] * 0.25)
    geometry = {
        "image_w": float(w), "image_h": float(h),
        "cx": cx, "crown_y": float(crown_y), "chin_y": chin_y, "eye_y": eye_y,
        "face_x0": float(x0), "face_x1": float(x1), "face_y0": float(y0),
        "face_w": float(fw), "face_h": float(fh),
    }

    # 4) 预审指标
    gray = cv2.cvtColor(work, cv2.COLOR_RGB2GRAY)
    ycc = cv2.cvtColor(work, cv2.COLOR_RGB2YCrCb)
    hsv = cv2.cvtColor(work, cv2.COLOR_RGB2HSV)
    shape = gray.shape
    face_mask = _poly_mask(shape, fc.landmarks[F.FACE_OVAL])
    cheek_r = 0.09 * fw
    ca, cb = fc.pt(F.CHEEK_A), fc.pt(F.CHEEK_B)
    if ca[0] > cb[0]:
        ca, cb = cb, ca
    cheek_a_mask = _circle_mask(shape, ca, cheek_r)
    cheek_b_mask = _circle_mask(shape, cb, cheek_r)
    skin = SkinModel(ycc, cheek_a_mask | cheek_b_mask)

    face_luma = gray[face_mask].astype(np.float32)
    la = float(gray[cheek_a_mask].mean()) if cheek_a_mask.any() else 0.0
    lb = float(gray[cheek_b_mask].mean()) if cheek_b_mask.any() else 0.0

    # 眉毛/额头遮挡：眉毛上方一条带状区域的肤色比例
    brow_ratios = []
    for brow in (F.BROW_A, F.BROW_B):
        pts = fc.landmarks[brow]
        upper = pts.copy()
        upper[:, 1] -= 0.13 * fh
        poly = np.vstack([pts[np.argsort(pts[:, 0])], upper[np.argsort(-upper[:, 0])]])
        r = skin.ratio(ycc, _poly_mask(shape, poly))
        if r is not None:
            brow_ratios.append(r)
    brow_skin = float(min(brow_ratios)) if brow_ratios else None

    # 耳朵：脸部两侧、眼睛到鼻尖高度范围内的肤色比例
    nose_y = float(fc.pt(F.NOSE_TIP)[1])
    sa, sb = fc.pt(F.SIDE_A), fc.pt(F.SIDE_B)
    if sa[0] > sb[0]:
        sa, sb = sb, sa
    ear_a = skin.ratio(ycc, _rect_mask(shape, sa[0] - 0.16 * fw, eye_y, sa[0] - 0.01 * fw, nose_y + 0.04 * fh))
    ear_b = skin.ratio(ycc, _rect_mask(shape, sb[0] + 0.01 * fw, eye_y, sb[0] + 0.16 * fw, nose_y + 0.04 * fh))

    # 镜片反光：眼周（含镜片范围）高亮低饱和像素比例
    glare = 0.0
    for eye in (F.EYE_A, F.EYE_B):
        pts = fc.landmarks[eye]
        ex0, ey0 = pts.min(axis=0)
        ex1, ey1 = pts.max(axis=0)
        ew, eh = ex1 - ex0, max(ey1 - ey0, 1.0)
        m = _rect_mask(shape, ex0 - 0.35 * ew, ey0 - 1.2 * eh, ex1 + 0.35 * ew, ey1 + 1.4 * eh)
        region = hsv[m]
        if len(region):
            bright = (region[:, 2] >= 240) & (region[:, 1] <= 45)
            glare = max(glare, float(bright.mean()))

    # 背景复杂度（只影响抠图边缘质量）
    region_mask = _rect_mask(shape, x0 - 1.2 * fw, crown_y - 0.3 * fh, x1 + 1.2 * fw, chin_y + 1.2 * fh)
    bg_mask = (alpha < 0.03) & region_mask
    bg_mask = cv2.erode(bg_mask.astype(np.uint8), np.ones((9, 9), np.uint8)).astype(bool)
    edges = cv2.Canny(gray, 60, 160) > 0
    bg_edge = float(edges[bg_mask].mean()) if bg_mask.sum() > 500 else 0.0
    bg_std = float(work[bg_mask].std(axis=0).mean()) if bg_mask.sum() > 500 else 0.0

    blend = fc.blendshapes
    metrics: dict[str, Any] = {
        "face_count": fc.count,
        "image_w": w,
        "image_h": h,
        "yaw": round(fc.yaw, 1),
        "pitch": round(fc.pitch, 1),
        "roll": round(roll, 1),
        "roll_corrected": rotated,
        "sharpness": round(_sharpness(gray, fc.face_box), 1),
        "face_luma": round(float(face_luma.mean()), 1) if face_luma.size else 0.0,
        "face_clip": round(float((face_luma >= 250).mean()), 3) if face_luma.size else 0.0,
        "face_dark": round(float((face_luma <= 25).mean()), 3) if face_luma.size else 0.0,
        "light_diff": round(abs(la - lb) / max(la, lb, 1.0), 3),
        "blink": round(max(blend.get("eyeBlinkLeft", 0.0), blend.get("eyeBlinkRight", 0.0)), 3),
        "jaw_open": round(blend.get("jawOpen", 0.0), 3),
        "smile": round((blend.get("mouthSmileLeft", 0.0) + blend.get("mouthSmileRight", 0.0)) / 2, 3),
        "brow_skin": None if brow_skin is None else round(brow_skin, 3),
        "ear_skin": [None if v is None else round(v, 3) for v in (ear_a, ear_b)],
        "glare": round(glare, 4),
        "bg_edge": round(bg_edge, 4),
        "bg_std": round(bg_std, 1),
        "crown_source": crown_src,
        "crown_cut": crown_cut,
        "face_px": round(fh, 1),
    }
    if crown_cut:
        return Analysis(ok=False, reason="crown_cut", work=work, alpha=alpha, geometry=geometry, metrics=metrics)
    return Analysis(ok=True, work=work, alpha=alpha, geometry=geometry, metrics=metrics)


def head_height(geometry: dict[str, float]) -> float:
    return max(1.0, geometry["chin_y"] - geometry["crown_y"])


def angle_text(value: float) -> str:
    return f"{abs(value):.0f}°" if not math.isnan(value) else "-"
