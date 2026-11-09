"""人脸检测与 478 点关键点（MediaPipe Face Landmarker，Apache-2.0，本地 CPU 推理）。"""
from __future__ import annotations

import math
import threading
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np

# 关键点索引（MediaPipe Face Mesh）
FACE_OVAL = [10, 338, 297, 332, 284, 251, 389, 356, 454, 323, 361, 288, 397, 365, 379, 378, 400, 377,
             152, 148, 176, 149, 150, 136, 172, 58, 132, 93, 234, 127, 162, 21, 54, 103, 67, 109]
EYE_A = [33, 7, 163, 144, 145, 153, 154, 155, 133, 173, 157, 158, 159, 160, 161, 246]
EYE_B = [362, 382, 381, 380, 374, 373, 390, 249, 263, 466, 388, 387, 386, 385, 384, 398]
BROW_A = [70, 63, 105, 66, 107, 55, 65, 52, 53, 46]
BROW_B = [336, 296, 334, 293, 300, 276, 283, 282, 295, 285]
CHEEK_A = 205
CHEEK_B = 425
FOREHEAD_TOP = 10
CHIN = 152
NOSE_TIP = 1
NOSE_BRIDGE = 168
SIDE_A = 234
SIDE_B = 454


@dataclass
class FaceResult:
    count: int
    landmarks: np.ndarray  # (478, 2) 像素坐标，主脸
    blendshapes: dict[str, float] = field(default_factory=dict)
    yaw: float = 0.0
    pitch: float = 0.0
    roll_3d: float = 0.0
    boxes: list[tuple[float, float, float, float]] = field(default_factory=list)

    def pt(self, idx: int) -> np.ndarray:
        return self.landmarks[idx]

    def mean(self, idxs: list[int]) -> np.ndarray:
        return self.landmarks[idxs].mean(axis=0)

    @property
    def eye_centers(self) -> tuple[np.ndarray, np.ndarray]:
        a, b = self.mean(EYE_A), self.mean(EYE_B)
        return (a, b) if a[0] <= b[0] else (b, a)

    @property
    def roll(self) -> float:
        """两眼连线相对水平线的角度（度），用于摆正。"""
        left, right = self.eye_centers
        return math.degrees(math.atan2(right[1] - left[1], right[0] - left[0]))

    @property
    def face_box(self) -> tuple[float, float, float, float]:
        pts = self.landmarks[FACE_OVAL]
        return float(pts[:, 0].min()), float(pts[:, 1].min()), float(pts[:, 0].max()), float(pts[:, 1].max())

    def transformed(self, matrix: np.ndarray) -> "FaceResult":
        pts = np.hstack([self.landmarks, np.ones((len(self.landmarks), 1))]) @ matrix.T
        return FaceResult(self.count, pts[:, :2], self.blendshapes, self.yaw, self.pitch, self.roll_3d, self.boxes)


def _euler_from_matrix(mat: np.ndarray) -> tuple[float, float, float]:
    r = mat[:3, :3]
    yaw = math.degrees(math.asin(max(-1.0, min(1.0, -r[2, 0]))))
    pitch = math.degrees(math.atan2(r[2, 1], r[2, 2]))
    roll = math.degrees(math.atan2(r[1, 0], r[0, 0]))
    return yaw, pitch, roll


class FaceAnalyzer:
    def __init__(self, model_path: Path):
        self.model_path = model_path
        self._lock = threading.Lock()
        self._landmarker = None

    def _ensure(self):
        if self._landmarker is None:
            from mediapipe.tasks import python as mpt
            from mediapipe.tasks.python import vision

            opts = vision.FaceLandmarkerOptions(
                base_options=mpt.BaseOptions(model_asset_path=str(self.model_path)),
                running_mode=vision.RunningMode.IMAGE,
                num_faces=4,
                output_face_blendshapes=True,
                output_facial_transformation_matrixes=True,
                min_face_detection_confidence=0.5,
                min_face_presence_confidence=0.5,
            )
            self._landmarker = vision.FaceLandmarker.create_from_options(opts)
        return self._landmarker

    def detect(self, rgb: np.ndarray) -> FaceResult | None:
        import mediapipe as mp

        h, w = rgb.shape[:2]
        with self._lock:
            landmarker = self._ensure()
            res = landmarker.detect(mp.Image(image_format=mp.ImageFormat.SRGB, data=np.ascontiguousarray(rgb)))
        if not res.face_landmarks:
            return None
        faces = []
        for i, lms in enumerate(res.face_landmarks):
            pts = np.array([[p.x * w, p.y * h] for p in lms], dtype=np.float64)
            oval = pts[FACE_OVAL]
            box = (oval[:, 0].min(), oval[:, 1].min(), oval[:, 0].max(), oval[:, 1].max())
            area = (box[2] - box[0]) * (box[3] - box[1])
            faces.append((area, i, pts, box))
        faces.sort(key=lambda f: -f[0])
        # 忽略面积不足主脸 6% 的背景小脸（例如墙上海报），但计入数量提示
        main_area = faces[0][0]
        significant = [f for f in faces if f[0] >= main_area * 0.06]
        _, idx, pts, _ = faces[0]
        blend = {}
        if res.face_blendshapes:
            blend = {c.category_name: float(c.score) for c in res.face_blendshapes[idx]}
        yaw = pitch = roll3 = 0.0
        if res.facial_transformation_matrixes:
            yaw, pitch, roll3 = _euler_from_matrix(np.array(res.facial_transformation_matrixes[idx]))
        return FaceResult(
            count=len(significant),
            landmarks=pts,
            blendshapes=blend,
            yaw=yaw,
            pitch=pitch,
            roll_3d=roll3,
            boxes=[tuple(map(float, f[3])) for f in faces],
        )
