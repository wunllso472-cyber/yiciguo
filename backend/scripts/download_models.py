"""下载本地推理所需的两个模型到 backend/models/（构建镜像前在能访问 GitHub/Google 的机器上运行一次）。

- face_landmarker.task  MediaPipe Face Landmarker（Apache-2.0）
- modnet_photographic_portrait_matting.onnx  MODNet 人像抠图（Apache-2.0，经 HivisionIDPhotos 发布页分发）

国内服务器访问不了这些地址时：在本地下载好，随代码一起上传或打进镜像即可。
用法：python scripts/download_models.py [--mirror https://你的镜像前缀/]
"""
from __future__ import annotations

import argparse
import hashlib
import sys
import urllib.request
from pathlib import Path

MODELS = {
    "face_landmarker.task": "https://storage.googleapis.com/mediapipe-models/face_landmarker/face_landmarker/float16/1/face_landmarker.task",
    "modnet_photographic_portrait_matting.onnx": "https://github.com/Zeyi-Lin/HivisionIDPhotos/releases/download/pretrained-model/modnet_photographic_portrait_matting.onnx",
}
MIN_SIZE = {"face_landmarker.task": 3_000_000, "modnet_photographic_portrait_matting.onnx": 20_000_000}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--mirror", default="", help="镜像前缀，会拼上文件名，例如 https://example.com/models/")
    parser.add_argument("--dir", default=str(Path(__file__).resolve().parent.parent / "models"))
    args = parser.parse_args()
    out_dir = Path(args.dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    for name, url in MODELS.items():
        target = out_dir / name
        if target.exists() and target.stat().st_size >= MIN_SIZE[name]:
            print(f"已存在 {name}")
            continue
        src = args.mirror.rstrip("/") + "/" + name if args.mirror else url
        print(f"下载 {name} ← {src}")
        tmp = target.with_suffix(target.suffix + ".part")
        urllib.request.urlretrieve(src, tmp)
        if tmp.stat().st_size < MIN_SIZE[name]:
            tmp.unlink()
            print(f"下载的 {name} 大小异常，请检查网络或镜像地址", file=sys.stderr)
            return 1
        tmp.replace(target)
        digest = hashlib.sha256(target.read_bytes()).hexdigest()[:16]
        print(f"完成 {name}（sha256 前 16 位 {digest}）")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
