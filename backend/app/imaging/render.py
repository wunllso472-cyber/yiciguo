"""按规格渲染：裁剪构图 → 换底 → 缩放 → 压到目标 KB → 写 DPI、去 EXIF；以及水印预览、打印排版、规格校验。"""
from __future__ import annotations

import io
import math
from dataclasses import asdict, dataclass
from functools import lru_cache
from pathlib import Path

import cv2
import numpy as np
from PIL import Image, ImageDraw, ImageFont

from ..specs import Spec

# ---------------------------------------------------------------- 构图


@dataclass
class CropPlan:
    out_w: int
    out_h: int
    scale: float  # 输出像素 / 源像素
    x0: float
    y0: float
    crop_w: float
    crop_h: float
    head_ratio: float
    top_margin: float
    overflow_bottom: float  # 超出源图底部的比例（相对裁剪高度）
    overflow_top: float
    overflow_side: float
    needs_upscale: bool

    def to_dict(self) -> dict:
        return {k: (round(v, 4) if isinstance(v, float) else v) for k, v in asdict(self).items()}


def plan_crop(geometry: dict[str, float], spec: Spec) -> CropPlan:
    img_w, img_h = geometry["image_w"], geometry["image_h"]
    crown, chin, cx = geometry["crown_y"], geometry["chin_y"], geometry["cx"]
    head_h = max(1.0, chin - crown)
    r_lo, r_mid, r_hi = spec.head_ratio
    t_lo, t_mid, t_hi = spec.top_margin
    out_w, out_h = spec.width, spec.height

    ratio, top = r_mid, t_mid
    crop_h = head_h / ratio
    # 底部不够（照片只拍到脖子）：在允许范围内放大头部比例
    if crown + (1 - top) * crop_h > img_h:
        need_ratio = head_h * (1 - top) / max(1.0, img_h - crown)
        ratio = min(r_hi, max(ratio, need_ratio))
        crop_h = head_h / ratio
    # 头顶空间不够：在允许范围内减小头顶留白
    if crown - top * crop_h < 0:
        top = max(t_lo, crown / crop_h)
    crop_w = crop_h * out_w / out_h
    y0 = crown - top * crop_h
    x0 = cx - crop_w / 2
    scale = out_h / crop_h

    # “最小像素”类规格：源图不够时退到最小尺寸，绝不放大
    if scale > 1.0 and spec.size_mode == "min" and spec.min_height:
        target_h = max(spec.min_height, int(math.floor(crop_h)))
        target_w = max(spec.min_width or 1, int(round(target_h * out_w / out_h)))
        out_w, out_h = target_w, target_h
        scale = out_h / crop_h

    overflow_bottom = max(0.0, (y0 + crop_h) - img_h) / crop_h
    overflow_top = max(0.0, -y0) / crop_h
    overflow_side = max(0.0, -x0, (x0 + crop_w) - img_w) / crop_w
    return CropPlan(
        out_w=out_w, out_h=out_h, scale=scale, x0=x0, y0=y0, crop_w=crop_w, crop_h=crop_h,
        head_ratio=ratio, top_margin=top, overflow_bottom=overflow_bottom, overflow_top=overflow_top,
        overflow_side=overflow_side, needs_upscale=scale > 1.04,
    )


def _crop_with_pad(img: np.ndarray, x0: float, y0: float, w: float, h: float) -> np.ndarray:
    ih, iw = img.shape[:2]
    xa, ya = int(math.floor(x0)), int(math.floor(y0))
    xb, yb = int(math.ceil(x0 + w)), int(math.ceil(y0 + h))
    pad_l, pad_t = max(0, -xa), max(0, -ya)
    pad_r, pad_b = max(0, xb - iw), max(0, yb - ih)
    region = img[max(0, ya): min(ih, yb), max(0, xa): min(iw, xb)]
    if pad_l or pad_t or pad_r or pad_b:
        region = cv2.copyMakeBorder(region, pad_t, pad_b, pad_l, pad_r, cv2.BORDER_REPLICATE)
    return region


def _blur_fusion(image: np.ndarray, fg: np.ndarray, bg: np.ndarray, alpha: np.ndarray, r: int):
    """Forte & Pitié 2021 “Approximate Fast Foreground Colour Estimation”：去除换底后的原背景色边。"""
    # 尽量原地计算，减少整幅三通道浮点临时数组（小内存实例上这里是峰值所在）
    eps = np.float32(1e-5)
    a = alpha[..., None]
    inv_a = 1 - a
    blurred_a = cv2.blur(alpha, (r, r))[..., None]
    blurred_f = cv2.blur(fg * a, (r, r))
    blurred_f /= blurred_a + eps
    blurred_b = cv2.blur(bg * inv_a, (r, r))
    blurred_b /= (1 - blurred_a) + eps
    # fg = blurred_f + a * (image - a * blurred_f - (1 - a) * blurred_b)
    out = image - a * blurred_f
    out -= inv_a * blurred_b
    out *= a
    out += blurred_f
    np.clip(out, 0, 1, out=out)
    return out, blurred_b


def estimate_foreground(image: np.ndarray, alpha: np.ndarray) -> np.ndarray:
    h = image.shape[0]
    r1 = int(np.clip(h / 16, 15, 90))
    r2 = max(3, r1 // 15)
    fg, blur_b = _blur_fusion(image, image, image, alpha, r1)
    fg, _ = _blur_fusion(image, fg, blur_b, alpha, r2)
    return fg


def render(work: np.ndarray, alpha: np.ndarray, plan: CropPlan, bg_rgb: tuple[int, int, int]) -> np.ndarray:
    src = _crop_with_pad(work, plan.x0, plan.y0, plan.crop_w, plan.crop_h)
    a = _crop_with_pad(alpha, plan.x0, plan.y0, plan.crop_w, plan.crop_h).astype(np.float32)
    # 在高于输出的分辨率上合成，再整体缩小，边缘更干净；
    # 合成分辨率取输出长边的 1.5 倍（800–1600），够用即可，避免大图在前景估计时占用几百 MB 内存
    max_side = int(min(1600, max(800, 1.5 * max(plan.out_w, plan.out_h))))
    k = min(1.0, max_side / max(src.shape[:2]))
    if k < 1.0:
        size = (max(1, int(src.shape[1] * k)), max(1, int(src.shape[0] * k)))
        src = cv2.resize(src, size, interpolation=cv2.INTER_AREA)  # 先在 uint8 上缩小，再转浮点，少占内存
        a = cv2.resize(a, size, interpolation=cv2.INTER_AREA)
    src = src.astype(np.float32)
    src *= np.float32(1 / 255)
    fg = estimate_foreground(src, a)
    bg = np.array(bg_rgb, dtype=np.float32) / 255.0
    a3 = a[..., None]
    comp = fg
    comp *= a3
    comp += bg[None, None, :] * (1 - a3)
    interp = cv2.INTER_AREA if comp.shape[0] >= plan.out_h else cv2.INTER_CUBIC
    out = cv2.resize(comp, (plan.out_w, plan.out_h), interpolation=interp)
    return np.clip(out * 255.0 + 0.5, 0, 255).astype(np.uint8)


def clothing_rgb(work: np.ndarray, alpha: np.ndarray, geometry: dict[str, float]) -> tuple[int, int, int] | None:
    """下巴以下、肩部区域的平均颜色（用于判断衣服与底色是否太接近）。"""
    fw = geometry["face_w"]
    cx, chin = geometry["cx"], geometry["chin_y"]
    fh = geometry["face_h"]
    y0, y1 = int(chin + 0.35 * fh), int(chin + 0.9 * fh)
    x0, x1 = int(cx - 1.3 * fw), int(cx + 1.3 * fw)
    h, w = alpha.shape
    y0, y1 = max(0, y0), min(h, y1)
    x0, x1 = max(0, x0), min(w, x1)
    if y1 - y0 < 4 or x1 - x0 < 4:
        return None
    a = alpha[y0:y1, x0:x1]
    region = work[y0:y1, x0:x1][a > 0.9]
    if len(region) < 200:
        return None
    med = np.median(region, axis=0)
    return int(med[0]), int(med[1]), int(med[2])


def color_distance(c1: tuple[int, int, int], c2: tuple[int, int, int]) -> float:
    """CIE76 ΔE（Lab）。"""
    lab = cv2.cvtColor(np.array([[c1, c2]], dtype=np.uint8), cv2.COLOR_RGB2LAB).astype(np.float32)[0]
    lab[:, 0] *= 100 / 255
    lab[:, 1:] -= 128
    return float(np.linalg.norm(lab[0] - lab[1]))


# ---------------------------------------------------------------- 编码


@dataclass
class EncodeResult:
    data: bytes
    quality: int
    subsampling: str
    kb: float
    ok: bool
    problem: str = ""


def _jpeg(img: Image.Image, quality: int, subsampling: int, dpi: int) -> bytes:
    buf = io.BytesIO()
    img.save(buf, "JPEG", quality=quality, subsampling=subsampling, optimize=True, progressive=False, dpi=(dpi, dpi))
    return buf.getvalue()


def encode_jpeg(rgb: np.ndarray, spec: Spec) -> EncodeResult:
    """二分搜索 JPEG 质量，使文件大小落在规格的 KB 区间内。

    上限按 1KB=1000 字节、下限按 1KB=1024 字节计算，两种口径下都满足要求。
    """
    img = Image.fromarray(rgb, "RGB")
    max_bytes = spec.kb_max * 1000 if spec.kb_max else None
    min_bytes = spec.kb_min * 1024 if spec.kb_min else None
    sub_names = {0: "4:4:4", 2: "4:2:0"}

    if max_bytes is None:
        data = _jpeg(img, 92, 0, spec.dpi)
        q, sub = 92, 0
    else:
        sub = 2
        best: tuple[int, bytes] | None = None
        lo, hi = 8, 95
        while lo <= hi:
            mid = (lo + hi) // 2
            d = _jpeg(img, mid, sub, spec.dpi)
            if len(d) <= max_bytes:
                best = (mid, d)
                lo = mid + 1
            else:
                hi = mid - 1
        if best is None:
            d = _jpeg(img, 8, sub, spec.dpi)
            return EncodeResult(d, 8, sub_names[sub], len(d) / 1024, False, "kb_too_small")
        q, data = best
        if q >= 92:  # 空间充裕时用 4:4:4，色彩更准
            d = _jpeg(img, 92, 0, spec.dpi)
            if len(d) <= max_bytes:
                q, sub, data = 92, 0, d

    if min_bytes and len(data) < min_bytes:
        for q2 in (95, 98, 100):
            d = _jpeg(img, q2, 0, spec.dpi)
            if len(d) >= min_bytes and (max_bytes is None or len(d) <= max_bytes):
                q, sub, data = q2, 0, d
                break
        else:
            return EncodeResult(data, q, sub_names[sub], len(data) / 1024, False, "kb_below_min")
    return EncodeResult(data, q, sub_names[sub], len(data) / 1024, True)


# ---------------------------------------------------------------- 规格校验


def validate_output(data: bytes, spec: Spec, bg_rgb: tuple[int, int, int], plan: CropPlan) -> list[dict]:
    im = Image.open(io.BytesIO(data))
    checks: list[dict] = []

    def add(cid: str, label: str, ok: bool, detail: str, warn: bool = False):
        checks.append({"id": cid, "label": label, "status": "pass" if ok else ("warn" if warn else "fail"), "detail": detail})

    w, h = im.size
    if spec.size_mode == "min" and spec.min_width:
        add("size", "像素尺寸", w >= spec.min_width and h >= (spec.min_height or 0),
            f"{w}×{h}（要求 ≥{spec.min_width}×{spec.min_height}）")
    else:
        add("size", "像素尺寸", (w, h) == (spec.width, spec.height), f"{w}×{h}（要求 {spec.width}×{spec.height}）")
    kb = len(data) / 1024
    kb_ok = (not spec.kb_max or len(data) <= spec.kb_max * 1000) and (not spec.kb_min or len(data) >= spec.kb_min * 1024)
    if spec.kb_min and spec.kb_max:
        req = f"要求 {spec.kb_min}–{spec.kb_max}KB"
    elif spec.kb_max:
        req = f"要求 ≤{spec.kb_max}KB"
    elif spec.kb_min:
        req = f"要求 ≥{spec.kb_min}KB"
    else:
        req = "无限制"
    add("kb", "文件大小", kb_ok, f"{kb:.1f}KB（{req}）")
    fmt_ok = im.format == "JPEG" and im.mode == "RGB" and not im.info.get("progressive") and not im.info.get("progression")
    add("format", "文件格式", fmt_ok, "JPG（基线、RGB 彩色）")
    dpi = im.info.get("dpi", (0, 0))
    add("dpi", "分辨率", round(dpi[0]) == spec.dpi, f"{round(dpi[0])} DPI")
    exif = im.getexif()
    add("exif", "隐私信息", len(exif) == 0 and "icc_profile" not in im.info, "已清除 EXIF（拍摄时间、地点、设备等）")
    arr = np.asarray(im.convert("RGB"), dtype=np.float32)
    k = max(2, min(w, h) // 25)
    corners = np.concatenate([arr[:k, :k].reshape(-1, 3), arr[:k, -k:].reshape(-1, 3)])
    corner_rgb = tuple(int(v) for v in corners.mean(axis=0))
    de = color_distance(corner_rgb, bg_rgb)
    add("bg", "背景颜色", de < 6, f"实测 RGB{corner_rgb}，偏差 ΔE {de:.1f}")
    r_lo, _, r_hi = spec.head_ratio
    add("head", "头部比例", r_lo - 0.005 <= plan.head_ratio <= r_hi + 0.005,
        f"头部占高度 {plan.head_ratio * 100:.0f}%（建议 {r_lo * 100:.0f}–{r_hi * 100:.0f}%）", warn=True)
    return checks


# ---------------------------------------------------------------- 字体、水印、打印排版

_FONT_CANDIDATES = [
    "C:/Windows/Fonts/msyh.ttc",
    "C:/Windows/Fonts/simhei.ttf",
    "/usr/share/fonts/truetype/wqy/wqy-microhei.ttc",
    "/usr/share/fonts/wqy-microhei/wqy-microhei.ttc",
    "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
    "/usr/share/fonts/noto-cjk/NotoSansCJK-Regular.ttc",
    "/System/Library/Fonts/PingFang.ttc",
]


@lru_cache(maxsize=1)
def _font_path(configured: str = "") -> str | None:
    for p in ([configured] if configured else []) + _FONT_CANDIDATES:
        if p and Path(p).exists():
            return p
    return None


def get_font(size: int, configured: str = "") -> tuple[ImageFont.ImageFont, bool]:
    path = _font_path(configured)
    if path:
        return ImageFont.truetype(path, size), True
    return ImageFont.load_default(size=size), False


def watermark_preview(rgb: np.ndarray, font_path: str = "", min_h: int = 480) -> bytes:
    img = Image.fromarray(rgb, "RGB")
    w, h = img.size
    if h < min_h:  # 小尺寸规格放大展示，便于看清
        k = min_h / h
        img = img.resize((round(w * k), round(h * k)), Image.LANCZOS)
        w, h = img.size
    font, cjk = get_font(max(12, int(w / 11)), font_path)
    text = "一次过 · 预览" if cjk else "YICIGUO PREVIEW"
    diag = int(math.hypot(w, h)) + 20
    layer = Image.new("RGBA", (diag, diag), (0, 0, 0, 0))
    draw = ImageDraw.Draw(layer)
    bbox = draw.textbbox((0, 0), text, font=font)
    tw, th = bbox[2] - bbox[0], bbox[3] - bbox[1]
    step_y = int(th * 3.2)
    for row, y in enumerate(range(0, diag, step_y)):
        offset = (row % 2) * tw // 2
        for x in range(-tw, diag, int(tw * 1.5)):
            # 深色字 + 白色描边：白底、蓝底、人脸上都看得见
            draw.text((x + offset, y), text, font=font, fill=(40, 40, 40, 105), stroke_width=max(1, font.size // 14),
                      stroke_fill=(255, 255, 255, 120))
    layer = layer.rotate(30, resample=Image.BICUBIC)
    left, top = (diag - w) // 2, (diag - h) // 2
    layer = layer.crop((left, top, left + w, top + h))
    out = Image.alpha_composite(img.convert("RGBA"), layer).convert("RGB")
    buf = io.BytesIO()
    out.save(buf, "JPEG", quality=82)
    return buf.getvalue()


def print_layout(rgb: np.ndarray, spec: Spec, font_path: str = "") -> bytes:
    """6 寸相纸（4R，152×102mm，300dpi）排版，带裁切参考线。"""
    dpi = 300
    page_w, page_h = 1800, 1200
    mm_w, mm_h = spec.physical_mm
    pw, ph = round(mm_w / 25.4 * dpi), round(mm_h / 25.4 * dpi)
    page = Image.new("RGB", (page_w, page_h), (255, 255, 255))
    if pw > page_w - 40 or ph > page_h - 80:
        page_w, page_h = page_h, page_w
        page = Image.new("RGB", (page_w, page_h), (255, 255, 255))
    gap, margin, footer = 20, 20, 44
    cols = max(1, (page_w - 2 * margin + gap) // (pw + gap))
    rows = max(1, (page_h - 2 * margin - footer + gap) // (ph + gap))
    photo = Image.fromarray(rgb, "RGB").resize((pw, ph), Image.LANCZOS)
    grid_w = cols * pw + (cols - 1) * gap
    grid_h = rows * ph + (rows - 1) * gap
    ox = (page_w - grid_w) // 2
    oy = (page_h - footer - grid_h) // 2
    draw = ImageDraw.Draw(page)
    for r in range(rows):
        for c in range(cols):
            x, y = ox + c * (pw + gap), oy + r * (ph + gap)
            page.paste(photo, (x, y))
            draw.rectangle((x - 1, y - 1, x + pw, y + ph), outline=(200, 200, 200), width=1)
    font, cjk = get_font(26, font_path)
    label = (f"{spec.short} · {mm_w:g}×{mm_h:g}mm × {rows * cols} 张 · 6寸相纸（4R）按 300dpi 原尺寸打印，勿缩放"
             if cjk else f"{mm_w:g}x{mm_h:g}mm x {rows * cols} · 4R 300dpi, print at 100%")
    draw.text((margin, page_h - footer + 8), label, font=font, fill=(130, 130, 130))
    buf = io.BytesIO()
    page.save(buf, "JPEG", quality=95, dpi=(dpi, dpi), subsampling=0)
    return buf.getvalue()
