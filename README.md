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

## 部署（Docker）

`docker compose` 起两个容器：

| 容器 | 作用 |
|---|---|
| `app` | 应用本身。镜像里已包含前端构建产物和两个模型；以非 root 用户（uid **10001**）运行，监听容器内 8000 端口，不直接对外 |
| `caddy` | 反向代理，自动申请和续期 HTTPS 证书，对外开放 80/443 |

宿主机上的目录：

```
yiciguo/
├─ .env              只给 docker compose 用：YCG_DOMAIN=你的域名（不要提交到 git）
├─ backend/.env      应用配置（密钥、支付参数），挂进 app 容器
├─ data/             照片和数据库 → 容器内 /data，需要授权给 uid 10001
└─ secrets/          支付宝密钥文件 → 容器内 /secrets（只读），需要授权给 uid 10001
```

### 1. 准备服务器

- Linux，**2 核 4G 起**，已安装 Docker 和 Compose 插件（`docker compose version` 能输出版本号）。
- 域名的 A 记录解析到服务器公网 IP。**国内服务器必须先完成 ICP 备案**，否则 80/443 访问会被拦截，证书也申请不下来。
- 安全组和防火墙放行 **80、443**。8000 不需要对外开放。

### 2. 拉取代码

```bash
git clone https://github.com/wunllso472-cyber/yiciguo.git
cd yiciguo
```

两个模型文件（`backend/models`，约 29MB）已经在仓库里，不用再运行 `download_models.py`。

### 3. 配置 `backend/.env`

先把域名写进变量，下面的命令都会用到：

```bash
DOMAIN=你的域名            # 例如 photo.example.com，不带 https:// 和末尾斜杠
```

**首次部署**（还没有 `backend/.env`）：

```bash
cp backend/.env.example backend/.env
sed -i "s#^YCG_BASE_URL=.*#YCG_BASE_URL=https://$DOMAIN#"                 backend/.env
sed -i "s/^YCG_SECRET_KEY=.*/YCG_SECRET_KEY=$(openssl rand -hex 32)/"     backend/.env
sed -i "s/^YCG_ADMIN_TOKEN=.*/YCG_ADMIN_TOKEN=$(openssl rand -hex 16)/"   backend/.env
sed -i "s/^YCG_PAY_MODE=.*/YCG_PAY_MODE=off/"                             backend/.env
grep -E "^YCG_(BASE_URL|SECRET_KEY|ADMIN_TOKEN|PAY_MODE)=" backend/.env   # 检查；ADMIN_TOKEN 记下来，登录 /admin 用
```

**已经有 `backend/.env`、只是补配置**：只执行需要的那几行。**生成 `YCG_SECRET_KEY` 的那行只能执行一次**：密钥一换，已发出的下载链接和用户的登录状态全部失效，用户只能靠取件码找回照片。

| 变量 | 生产环境怎么填 | 不填或填错会怎样 |
|---|---|---|
| `YCG_ENV` | 不用管 | `docker-compose.yml` 已固定为 `prod`，`.env` 里写什么都会被覆盖 |
| `YCG_BASE_URL` | `https://你的域名` | 支付返回地址、分享链接都用它拼接；不是 `https://` 时付款后不会跳回本站 |
| `YCG_SECRET_KEY` | 随机字符串，生成后不再更换 | 为空时启动报错“生产环境必须设置 YCG_SECRET_KEY” |
| `YCG_ADMIN_TOKEN` | 随机字符串 | 为空时 `/admin` 看板无法登录 |
| `YCG_PAY_MODE` | 即刻收白名单获批前填 `off`，获批后改成 `nowpay` | 填 `mock` 时启动报错（生产环境禁止模拟支付）；`off` 时网站能正常使用，点支付提示“支付暂未开通” |
| `YCG_SHOWCASE_URL` | 拿到 AI付官网作品详情页链接后填 | 付款成功页“去点赞”按钮跳到活动首页 |
| `YCG_WORKERS` | 4G 内存填 `2`，2G 内存填 `1` | 太大会在同时处理多张照片时内存不足，容器被杀 |

**开通真实支付**（`YCG_PAY_MODE=nowpay`）时，再填下面这几项。密钥文件路径填的是**容器内路径**：

```ini
YCG_PAY_MODE=nowpay
ALIPAY_APP_ID=开放平台应用ID
ALIPAY_PRIVATE_KEY_FILE=/secrets/app_private_key.pem
ALIPAY_PUBLIC_KEY_FILE=/secrets/alipay_public_key.pem
NOWPAY_PRODUCT_COUNT=即刻收小程序里「照片导出」的商品ID
NOWPAY_PRODUCT_MONTHLY=「备考季月卡」的商品ID（没建可以留空）
```

把密钥放进宿主机的 `secrets/`。带不带 `-----BEGIN ...-----` 头尾都行，PKCS1 和 PKCS8 格式都支持：

```bash
mkdir -p secrets
cp 应用私钥.txt   secrets/app_private_key.pem      # 应用私钥
cp 支付宝公钥.txt secrets/alipay_public_key.pem    # 支付宝公钥，不是“应用公钥”
```

### 4. 设置域名，给目录授权

```bash
echo "YCG_DOMAIN=$DOMAIN" > .env            # 项目根目录的 .env，Caddy 用它申请证书
mkdir -p data secrets
sudo chmod 400 secrets/*.pem 2>/dev/null || true   # 有密钥文件时收紧权限（没有会跳过）
sudo chown -R 10001:10001 data secrets
sudo chmod 700 secrets
```

一定要做这一步：容器里的程序以 uid 10001 运行。`./data` 如果是 Docker 自动创建的，属于 root，程序写不进去，启动时会报 `unable to open database file` 或 `PermissionError: '/data/...'`。

授权之后 `secrets/` 只有 uid 10001 能进。以后再放密钥文件（比如开通支付时），要用 `sudo cp`，放完重新执行上面后三行。

### 5. 构建并启动

```bash
docker compose up -d --build         # 首次构建要几分钟（npm、pip、mediapipe）
docker compose ps                    # 两个容器都是 running / Up
docker compose logs -f app           # 看到「启动：env=prod pay_mode=off base_url=https://…」就是启动成功，Ctrl+C 退出
curl https://$DOMAIN/api/health      # 返回 {"ok":true,"pay_mode":"off"}
```

第一次访问前，Caddy 要花 10–60 秒申请证书，进度用 `docker compose logs caddy` 查看。

### 日常运维

| 要做什么 | 命令 |
|---|---|
| 只改了 `backend/.env` 或密钥文件 | `docker compose up -d --force-recreate app`（不需要重新构建） |
| 更新代码（包括规格库 `specs.json`） | `git pull && docker compose up -d --build` |
| 看日志 | `docker compose logs -f --tail=200 app` |
| 重启 | `docker compose restart app` |
| 停止 | `docker compose down`（数据在 `./data`，不会丢）。**不要加 `-v`**：会删掉 Caddy 存的证书，频繁重新申请可能被限流 |
| 备份数据库 | 见下方 |

照片 24 小时后自动删除，不用备份；数据库建议每天备份一次。运行中也可以安全备份：

```bash
docker compose exec app python -c "import sqlite3;s=sqlite3.connect('/data/yiciguo.db');d=sqlite3.connect('/data/backup.db');s.backup(d);d.close()"
sudo cp data/backup.db ~/yiciguo-$(date +%F).db
```

- 应用以**单进程**运行（对账/清理线程、限流、核销锁都在进程内），不要开多副本；吞吐量用 `YCG_WORKERS` 调。
- 规格库 `specs.json` 打包在镜像里，在服务器上直接改文件不会生效，要重新构建（`docker compose up -d --build`）。

### 常见报错

容器启动失败时，`docker compose ps` 里 `app` 会一直处于 `Restarting`，用 `docker compose logs --tail=50 app` 看最后的报错。

| 报错或现象 | 原因与处理 |
|---|---|
| `RuntimeError: 生产环境必须设置 YCG_SECRET_KEY` | `backend/.env` 里 `YCG_SECRET_KEY=` 是空的。按第 3 步生成，再执行 `docker compose up -d --force-recreate app` |
| `RuntimeError: 生产环境禁止使用模拟支付（YCG_PAY_MODE=mock）` | `.env.example` 默认是 `mock`，改成 `off`（白名单获批前）或 `nowpay` |
| `ValueError: 缺少 ALIPAY_APP_ID / ALIPAY_PRIVATE_KEY / ALIPAY_PUBLIC_KEY` | `nowpay` 模式下三项缺了至少一项。`*_FILE` 要填容器内路径 `/secrets/...` |
| `RuntimeError: YCG_PAY_MODE=nowpay 时必须配置 NOWPAY_PRODUCT_COUNT` | 填入即刻收小程序商品详情页里复制的商品 ID |
| `FileNotFoundError` / `PermissionError` 指向 `/secrets/...` | 宿主机 `secrets/` 里没有这个文件，或者没授权给 uid 10001（第 4 步） |
| `ValueError: Could not deserialize key data` | 密钥文件内容不对：私钥填成了公钥，或者 `ALIPAY_PUBLIC_KEY_FILE` 填成了“应用公钥”（应该填“支付宝公钥”） |
| `unable to open database file` / `PermissionError: '/data/...'` | `./data` 没授权给 uid 10001（第 4 步） |
| `ImportError: libGL.so.1` 等缺少 `.so` 库 | mediapipe 缺系统库：把缺的包加到 `Dockerfile` 的 `apt-get install` 那一行，重新构建 |
| 浏览器打不开、证书报错 | 依次检查：域名是否已解析到本机（`ping 域名`）、80/443 是否放行、国内服务器是否已备案、根目录 `.env` 里的 `YCG_DOMAIN` 是否正确。详情看 `docker compose logs caddy` |
| 能打开网站，点支付提示“支付暂未开通” | `YCG_PAY_MODE=off` 时就是这样，属于正常。获批后按第 3 步改成 `nowpay` |
| 处理照片时容器重启，`dmesg` 里有 `Out of memory` | 内存不够：`YCG_WORKERS` 改成 `1`，或者升级服务器配置 |
| 国内服务器拉取 `node`、`python`、`caddy` 镜像超时 | 在 `/etc/docker/daemon.json` 配置 `registry-mirrors` 镜像加速，然后 `sudo systemctl restart docker` |

## 规格库维护

编辑 `backend/app/data/specs.json`。本地开发时调用 `POST /api/admin/specs/reload`（带 `Authorization: Bearer <YCG_ADMIN_TOKEN>`）或重启即可生效；Docker 部署时规格库打包在镜像里，要提交后在服务器上执行 `git pull && docker compose up -d --build`。启动时会校验：

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
