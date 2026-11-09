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
    YCG_FONT_PATH=/usr/share/fonts/truetype/wqy/wqy-microhei.ttc
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
USER app
EXPOSE 8000
# 单进程运行：后台对账/清理线程、限流与锁都在进程内；吞吐靠 YCG_WORKERS 线程调节
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--proxy-headers", "--forwarded-allow-ips", "*"]
