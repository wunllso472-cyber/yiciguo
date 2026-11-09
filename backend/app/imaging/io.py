"""图片读取：HEIC/JPG/PNG/WebP，按 EXIF 方向摆正，转 sRGB，限制最大边长。"""
from __future__ import annotations

import io

import numpy as np
from PIL import Image, ImageCms, ImageOps

try:  # HEIC（iPhone 原图）
    import pillow_heif

    pillow_heif.register_heif_opener()
except Exception:  # pragma: no cover - 可选依赖
    pillow_heif = None

Image.MAX_IMAGE_PIXELS = 80_000_000
MAX_SIDE = 2400

_SRGB = ImageCms.createProfile("sRGB")


class ImageLoadError(ValueError):
    pass


def load_rgb(data: bytes, max_side: int = MAX_SIDE) -> np.ndarray:
    try:
        im = Image.open(io.BytesIO(data))
        im.load()
    except Exception as exc:  # noqa: BLE001
        raise ImageLoadError("无法识别的图片格式，请上传 JPG / PNG / HEIC 照片") from exc

    im = ImageOps.exif_transpose(im)

    icc = im.info.get("icc_profile")
    if icc and im.mode in ("RGB", "RGBA", "CMYK"):
        try:
            src = ImageCms.ImageCmsProfile(io.BytesIO(icc))
            out_mode = "RGBA" if im.mode == "RGBA" else "RGB"
            im = ImageCms.profileToProfile(im, src, _SRGB, outputMode=out_mode)
        except Exception:  # noqa: BLE001 - 色彩配置文件损坏时按原样处理
            pass

    if im.mode in ("RGBA", "LA") or (im.mode == "P" and "transparency" in im.info):
        rgba = im.convert("RGBA")
        bg = Image.new("RGB", rgba.size, (255, 255, 255))
        bg.paste(rgba, mask=rgba.split()[-1])
        im = bg
    im = im.convert("RGB")

    w, h = im.size
    if min(w, h) < 120:
        raise ImageLoadError("图片太小，请上传清晰的原图")
    scale = max_side / max(w, h)
    if scale < 1:
        im = im.resize((round(w * scale), round(h * scale)), Image.LANCZOS)
    return np.asarray(im, dtype=np.uint8).copy()
