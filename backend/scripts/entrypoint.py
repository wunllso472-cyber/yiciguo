"""容器启动入口。

1. 以 root 启动时，先把数据目录（默认 /data）的所有权交给 app 用户，再降权运行。
   云平台挂载的持久化磁盘（如 Render Disk）和 docker compose 自动创建的 ./data 往往属于 root，
   直接以非 root 用户运行会写不进数据库。
2. 监听端口取环境变量 PORT（Render 等平台会注入），没有时用 8000。
"""
from __future__ import annotations

import os
import pwd
import sys

APP_USER = "app"


def _fix_owner(path: str, uid: int, gid: int) -> None:
    os.makedirs(path, exist_ok=True)
    for root, _dirs, files in os.walk(path):
        for p in (root, *(os.path.join(root, f) for f in files)):
            st = os.lstat(p)
            if st.st_uid != uid or st.st_gid != gid:
                os.lchown(p, uid, gid)


def _drop_privileges() -> None:
    pw = pwd.getpwnam(APP_USER)
    _fix_owner(os.environ.get("YCG_DATA_DIR", "/data"), pw.pw_uid, pw.pw_gid)
    os.initgroups(APP_USER, pw.pw_gid)
    os.setgid(pw.pw_gid)
    os.setuid(pw.pw_uid)
    os.environ["HOME"] = pw.pw_dir
    os.environ["USER"] = APP_USER


def main() -> None:
    if os.geteuid() == 0:
        _drop_privileges()
    port = os.environ.get("PORT", "").strip() or "8000"
    # 单进程运行：后台对账/清理线程、限流与锁都在进程内；吞吐靠 YCG_WORKERS 线程调节
    args = ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", port,
            "--proxy-headers", "--forwarded-allow-ips", "*", *sys.argv[1:]]
    sys.stdout.flush()
    os.execvp(args[0], args)


if __name__ == "__main__":
    main()
