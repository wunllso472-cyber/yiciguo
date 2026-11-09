# 一次过 · 报名照片过审助手

PAYATHON 2026 · Vibe Pay 主赛道作品。对应方案文档：`../报名照方向_产品方案与开发计划.md`。

**一句话**：按考试规格库生成报名照——免费 AI 预审 + 自动换底/裁剪/压到目标 KB，¥0.99 下载无水印合规照片，被驳回免费重做。

```
yiciguo/
├─ backend/                 FastAPI + 本地 CPU 图像管线 + 即刻收直连支付
│  ├─ app/
│  │  ├─ data/specs.json    规格库（31 条，12 条已对照官方原文核实）
│  │  ├─ imaging/           人脸关键点、抠图、构图、KB 压缩、预审、水印、打印排版
│  │  ├─ payments/          RSA2 网关、即刻收 6 个接口、模拟收银台、支付状态机
│  │  ├─ routes/            HTTP 接口 + 前端托管（含规格页 SEO）
│  │  └─ pipeline.py        上传后处理与渲染缓存
│  ├─ models/               face_landmarker.task、MODNet ONNX（约 29MB）
│  ├─ scripts/download_models.py
│  └─ tests/                39 个测试（签名验签、支付状态机、图像、规格库、端到端）
├─ frontend/                React + Vite H5（移动端优先，兼容 PC）
├─ Dockerfile · docker-compose.yml · Caddyfile
```

## 已实现的功能

| 方案优先级 | 功能 | 状态 |
|---|---|---|
| P0 | 规格库：尺寸/最小像素/KB 上下限/底色/DPI/头部比例/规则/官方工具/来源链接/核实状态与说明/重大变化提醒，搜索与分类；**自定义规格**（按报名系统要求输入） | ✅ 31 条（12 条已核实）+ 自定义 |
| P0 | 上传与拍照：JPG/PNG/WebP/HEIC，手机端先压缩再上传，EXIF 方向矫正，转 sRGB | ✅ |
| P0 | 处理管线：MediaPipe 478 点关键点 → 两眼连线自动摆正 → MODNet 抠图（只保留与人脸相连的前景）→ 按头部占比/头顶留白构图 → 前景色还原后换底 → 二分搜索 JPEG 质量压到 KB 区间 → 写 DPI、去 EXIF；源图不足时**不放大**并提示重拍 | ✅ 单张约 0.6–1.5 秒（CPU） |
| P0 | 免费预审报告：人脸数、正面姿态、头部水平、清晰度、曝光、阴阳脸、双眼睁开、表情、眉毛遮挡、露耳（规格要求时）、眼镜反光、不戴眼镜提醒、源图像素、构图完整、原背景、衣服与底色、压缩质量，逐项通过/注意/不通过 + 修改建议 | ✅ 12–17 项 |
| P0 | 成品实测：对生成的 JPG 复核像素、KB、格式、DPI、EXIF、背景色、头部比例 | ✅ |
| P0 | 支付与交付：即刻收直连（charge.query / quota.query / purchase.create / quota.verify / quota.refresh / purchase.consult），先生成成品再核销，完整异常处理（见下） | ✅ |
| P0 | 我的照片：匿名用户 + 8 位取件码换设备找回；24 小时自动删除；可立即删除 | ✅ |
| P0 | 单独的人脸信息处理同意弹窗、隐私规则、用户协议 | ✅ |
| P1 | 6 寸相纸打印排版（300dpi、裁切线） | ✅ |
| P1 | 官方工具指引（国考等） | ✅ 规格页 + 交付页 |
| P1 | 被驳回免费重做（每张付费照片 7 天内 1 次，不再核销） | ✅ |
| P1 | 分享裂变：对方用邀请链接完成首张照片，双方各得 1 次免费导出（本站发放，不走支付） | ✅ |
| P1 | 导出成功页引导去 AI付官网点赞 | ✅ `YCG_SHOWCASE_URL` |
| P1 | 实时拍摄引导（MediaPipe 前端） | ⏳ 未做，目前是拍摄要点 + 预审后重拍 |
| P2 | 签证照（美/日/申根/韩）、规格纠错众包、运营看板（漏斗/付费人数/热门规格/纠错） | ✅ |
| 其他 | 每条规格独立 SEO 页（服务端注入 title/description/正文摘要）、sitemap.xml、robots.txt、漏斗埋点 | ✅ |

## 本地运行

需要 Python 3.11+、Node 18+。

```bash
# 后端
cd backend
python -m venv .venv
.venv/Scripts/pip install -r requirements.txt          # Linux/macOS 用 .venv/bin/pip
.venv/Scripts/pip install --no-deps mediapipe==1.2.2
python scripts/download_models.py                       # 已下载过可跳过
cp .env.example .env                                    # 默认 YCG_PAY_MODE=mock
.venv/Scripts/python -m uvicorn app.main:app --port 8000

# 前端（另开终端）
cd frontend
npm install
npm run dev        # http://localhost:5173 ，接口自动转发到 8000
npm run build      # 构建到 frontend/dist，后端直接托管：http://127.0.0.1:8000

# 测试
cd backend && .venv/Scripts/python -m pytest -q
```

模拟支付模式下，“支付”会打开本站的模拟收银台（醒目标注“不会产生真实扣款”），可以完整演示：选档位 → 扫码/跳转 → 确认或取消 → 返回确认 → 自动解锁。生产环境（`YCG_ENV=prod`）禁止 mock 模式，启动会直接报错。

## 支付接入（即刻收直连）

1. 白名单获批后，在支付宝搜“即刻收”管理小程序：完成认证签约，建两个商品
   - 商品 A「照片导出」：次数包 `QUANTITY / COUNT`，档位 1 次 ¥0.99、3 次 ¥1.99、10 次 ¥4.99
   - 商品 B「备考季月卡」：时长包 `ONE_TIME_DURATION / MONTH` ¥9.9（可选）
2. 支付宝开放平台应用：配置 RSA2 密钥，拿到 `app_id`、应用私钥、**支付宝公钥**，开通接口权限。
3. `backend/.env`：`YCG_PAY_MODE=nowpay`，填 `ALIPAY_*`、`NOWPAY_PRODUCT_COUNT`（小程序商品详情页复制的 ID）、`NOWPAY_PRODUCT_MONTHLY`；`YCG_BASE_URL` 必须是 HTTPS（`callback_url` 要求 HTTPS）。
4. **报名参赛、即刻收签约、开放平台应用必须是同一个支付宝账号主体**，否则付费人数不计入。

### 状态机要点（与官方文档对齐，均有测试覆盖）

| 场景 | 处理 |
|---|---|
| 商品状态 | 只有 `capability_status=ENABLED` 且有档位才展示购买；档位非空不代表可买 |
| 重复点击购买 | 同用户/同档位/同照片，复用 30 分钟内未过期的购买入口 |
| `purchase.create` 超时 / `LINK_CREATING` | 用**原请求号 + 原参数**重试 |
| 手机端 | 直接跳转返回的 `purchase_url`（不拼接不解析）；2.5 秒没离开页面提示改用二维码 |
| 电脑端 | 展示 `purchase_qr_code` 二维码，页面轮询 |
| 微信内 | 不跳转（会被拦截），展示二维码 + “右上角在浏览器打开”引导 |
| 付款后确认 | 没有异步通知：返回页 + 原页面切回时由服务端 `quota.query`/`purchase.consult` 查询；余额比下单前增加才算到账；查不到只提示稍后刷新，**绝不自动再次发起支付** |
| 余额查询失败 | 不当作 0，提示稍后重试 |
| 交付核销 | 先在服务端生成并校验无水印成品，再 `quota.verify(amount=1)`；成品校验不通过不核销 |
| 核销请求号 | 每张照片每次尝试唯一（`cs<照片ID><序号>`），落库后再调用 |
| `SUCCEEDED` | 解锁照片 |
| `NOW_PAY_QUOTA_INSUFFICIENT` / `FAILED` | 不解锁，引导购买；之后用新序号重新核销 |
| 超时 / `PROCESSING` / 系统错误 | 标记待确认，`quota.refresh` 用原请求号查；查不到记录则原参数重试 verify；后台线程指数退避持续对账，成功后自动解锁 |
| 支付宝 App 内打开返回页 | 返回地址带 HMAC 签名，无 Cookie 也能查看结果和下载，并展示取件码 |
| 退款 | 文档没有退款/撤销核销接口：生成失败不扣次数；被驳回免费重做；其余人工处理（FAQ 已写明） |

## 部署

```bash
# 服务器（2C4G 起），已装 Docker；域名已解析且完成 ICP 备案
cp backend/.env.example backend/.env       # 填 YCG_ENV=prod、YCG_SECRET_KEY、支付配置……
mkdir secrets && cp 应用私钥.pem secrets/app_private_key.pem && cp 支付宝公钥.pem secrets/alipay_public_key.pem
#   .env 里：ALIPAY_PRIVATE_KEY_FILE=/secrets/app_private_key.pem  ALIPAY_PUBLIC_KEY_FILE=/secrets/alipay_public_key.pem
YCG_DOMAIN=你的域名 docker compose up -d --build
```

- 应用以**单进程**运行（对账/清理线程、限流、核销锁都在进程内）；用 `YCG_WORKERS` 调整同时处理的照片数。
- 照片和数据库在 `./data`，请定期备份数据库（照片 24 小时自动删除，不需要备份）。
- 国内服务器访问不了 Google/GitHub 的话，在本地运行 `download_models.py` 后把 `backend/models` 一起上传。
- Dockerfile 未在本机实际构建验证（本机没有 Docker），首次部署请留意 mediapipe 在 Linux 下的系统库依赖。

## 规格库维护

编辑 `backend/app/data/specs.json`，然后调用 `POST /api/admin/specs/reload`（带 `Authorization: Bearer <YCG_ADMIN_TOKEN>`）或重启。启动时会校验：

- `status=verified` 必须有 `official: true` 的来源和 `verified_at`，否则拒绝启动；
- 底色、分类、KB 区间、头部比例都会做合法性检查。

运营看板：`/admin`（输入管理员令牌）。用户提交的规格纠错也在这里查看。

## 上线前必须人工完成

1. **规格库**：31 条，其中 12 条已于 2026-11-09 对照官方原文核实，详见 `规格核实记录.md`。美国签证、申根签证、韩国签证三条的官方页面无法自动读取，需要人工打开链接复核；2026 年度的数值（计算机等级、会计职称、人事考试网）在 2027 年度公告发布后要复核。
2. 替换 FAQ 里的客服邮箱占位（`frontend/src/pages/TextPages.tsx`）。
3. 设置 `YCG_SHOWCASE_URL` 为 AI付官网上本作品的详情页。
4. 真机测试矩阵：iOS Safari、安卓 Chrome、支付宝内置浏览器、微信内置浏览器、PC Chrome、PC Edge，各跑一遍真实 ¥0.99 支付。
5. 用真实考生照片（征得同意）抽检抠图效果：浅色衣服+白底、长发、刘海、眼镜。预审阈值是工程经验值（见 `imaging/precheck.py`），可按反馈微调。

## 已知限制

- 抠图对“衣服颜色接近原背景”或背景很杂乱的照片边缘会变差，预审会提示重拍；未接入更重的 BiRefNet 模型（CPU 太慢）。
- “露耳”“眉毛遮挡”是基于肤色的启发式检测，只做提醒不拦截；“是否戴眼镜”只做提醒，反光是实测。
- 国考等要求官方工具处理的考试，本产品只生成合规源照片，不能替代官方工具。
