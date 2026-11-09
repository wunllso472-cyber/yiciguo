# ---------- 前端构建 ----------
FROM node:22-alpine AS web
WORKDIR /web
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci --no-audit --no-fund
COPY frontend/ ./
RUN npm run build

# ---------- 运行环境 ----------
FROM python:3.13-slim
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    YCG_ENV=prod \
    YCG_DATA_DIR=/data \
    YCG_FRONTEND_DIST=/app/frontend/dist \
    YCG_FONT_PATH=/usr/share/fonts/truetype/wqy/wqy-microhei.ttc \
    YCG_WORKERS=1 \
    MALLOC_ARENA_MAX=2
# YCG_WORKERS=1：默认一次只处理一张照片，512MB 内存的实例（如 Render Free）也能跑；内存 ≥2GB 时可设为 2
# MALLOC_ARENA_MAX=2：限制 glibc 每线程内存池数量，减少多线程下的内存碎片
# 中文字体（水印、打印排版用）；mediapipe 运行时需要的图形库
RUN apt-get update \
 && apt-get install -y --no-install-recommends fonts-wqy-microhei libgl1 libglib2.0-0 libegl1 libgles2 \
 && rm -rf /var/lib/apt/lists/*
WORKDIR /app/backend
COPY backend/requirements.txt .
RUN pip install -r requirements.txt && pip install --no-deps mediapipe==1.2.2
COPY backend/app ./app
COPY backend/scripts ./scripts
# 模型需提前用 scripts/download_models.py 下载到 backend/models
COPY backend/models ./models
COPY --from=web /web/dist /app/frontend/dist
RUN useradd -m -u 10001 app && mkdir -p /data && chown app /data
EXPOSE 8000
# 入口脚本以 root 启动：把 /data（可能是 root 所有的挂载盘）交给 app 用户（uid 10001）后降权，
# 再以单进程运行 uvicorn，监听 $PORT（Render 会注入；docker compose 下默认 8000）
CMD ["python", "scripts/entrypoint.py"]
