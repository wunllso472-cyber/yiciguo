"""支付宝开放平台网关：RSA2（SHA256withRSA）签名与验签，公钥模式。

不依赖官方 Python SDK：按开放平台规则把公共参数 + biz_content 排序拼接后签名；
响应验签时取响应 JSON 里 `<method>_response` 节点的**原始文本**（不能重新序列化）。
"""
from __future__ import annotations

import base64
import json
import logging
from datetime import datetime, timedelta, timezone
from typing import Any

import httpx
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding, rsa

log = logging.getLogger("yiciguo.alipay")

CN_TZ = timezone(timedelta(hours=8))

# 结果未知（可能已经执行）：写操作必须用原请求号查询或重试，不能换号
UNKNOWN_SUB_CODES = {"SYSTEM_ERROR", "isp.unknow-error", "aop.ACQ.SYSTEM_ERROR", "isp.unknown-error"}


class GatewayError(Exception):
    def __init__(self, code: str, msg: str = "", sub_code: str | None = None, sub_msg: str | None = None,
                 unknown: bool = False):
        super().__init__(f"{code} {msg} {sub_code or ''} {sub_msg or ''}".strip())
        self.code = code
        self.msg = msg
        self.sub_code = sub_code
        self.sub_msg = sub_msg
        self.unknown = unknown


def _pem(key: str, kind: str) -> bytes:
    key = key.strip()
    if "-----BEGIN" in key:
        return key.encode()
    body = "".join(key.split())
    lines = "\n".join(body[i:i + 64] for i in range(0, len(body), 64))
    return f"-----BEGIN {kind}-----\n{lines}\n-----END {kind}-----\n".encode()


def load_private_key(key: str) -> rsa.RSAPrivateKey:
    key = key.strip()
    if "-----BEGIN" in key:
        return serialization.load_pem_private_key(key.encode(), password=None)  # type: ignore[return-value]
    der = base64.b64decode("".join(key.split()))
    return serialization.load_der_private_key(der, password=None)  # type: ignore[return-value]


def load_public_key(key: str) -> rsa.RSAPublicKey:
    return serialization.load_pem_public_key(_pem(key, "PUBLIC KEY"))  # type: ignore[return-value]


def sign_content(params: dict[str, str]) -> str:
    items = sorted((k, v) for k, v in params.items() if k != "sign" and v not in (None, ""))
    return "&".join(f"{k}={v}" for k, v in items)


def rsa2_sign(content: str, private_key: rsa.RSAPrivateKey) -> str:
    sig = private_key.sign(content.encode("utf-8"), padding.PKCS1v15(), hashes.SHA256())
    return base64.b64encode(sig).decode()


def rsa2_verify(content: str, signature: str, public_key: rsa.RSAPublicKey) -> bool:
    try:
        public_key.verify(base64.b64decode(signature), content.encode("utf-8"), padding.PKCS1v15(), hashes.SHA256())
        return True
    except Exception:  # noqa: BLE001
        return False


def extract_node(body: str, node_key: str) -> str | None:
    """返回 `"node_key": {...}` 中对象部分的原始文本（括号配对，处理字符串转义）。"""
    marker = f'"{node_key}"'
    idx = body.find(marker)
    if idx < 0:
        return None
    start = body.find("{", idx + len(marker))
    if start < 0:
        return None
    colon = body.find(":", idx + len(marker))
    if colon < 0 or colon > start:
        return None
    depth, in_str, esc = 0, False, False
    for i in range(start, len(body)):
        ch = body[i]
        if in_str:
            if esc:
                esc = False
            elif ch == "\\":
                esc = True
            elif ch == '"':
                in_str = False
            continue
        if ch == '"':
            in_str = True
        elif ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                return body[start: i + 1]
    return None


class AlipayGateway:
    def __init__(self, app_id: str, private_key: str, alipay_public_key: str,
                 gateway: str = "https://openapi.alipay.com/gateway.do", app_auth_token: str = "",
                 timeout: float = 10.0, http: httpx.Client | None = None):
        if not (app_id and private_key and alipay_public_key):
            raise ValueError("缺少 ALIPAY_APP_ID / ALIPAY_PRIVATE_KEY / ALIPAY_PUBLIC_KEY")
        self.app_id = app_id
        self.private_key = load_private_key(private_key)
        self.public_key = load_public_key(alipay_public_key)
        self.gateway = gateway
        self.app_auth_token = app_auth_token
        self.http = http or httpx.Client(timeout=timeout)

    def build_params(self, method: str, biz: dict[str, Any], now: datetime | None = None) -> dict[str, str]:
        now = now or datetime.now(CN_TZ)
        params = {
            "app_id": self.app_id,
            "method": method,
            "format": "JSON",
            "charset": "utf-8",
            "sign_type": "RSA2",
            "timestamp": now.strftime("%Y-%m-%d %H:%M:%S"),
            "version": "1.0",
            "biz_content": json.dumps(biz, ensure_ascii=False, separators=(",", ":")),
        }
        if self.app_auth_token:
            params["app_auth_token"] = self.app_auth_token
        params["sign"] = rsa2_sign(sign_content(params), self.private_key)
        return params

    def call(self, method: str, biz: dict[str, Any]) -> dict[str, Any]:
        params = self.build_params(method, biz)
        try:
            resp = self.http.post(self.gateway, data=params,
                                  headers={"Content-Type": "application/x-www-form-urlencoded;charset=utf-8"})
        except httpx.HTTPError as exc:
            raise GatewayError("NETWORK", str(exc), unknown=True) from exc
        if resp.status_code >= 500:
            raise GatewayError("HTTP_" + str(resp.status_code), "网关异常", unknown=True)
        return self.parse_response(method, resp.content.decode("utf-8", errors="replace"))

    def parse_response(self, method: str, body: str) -> dict[str, Any]:
        node_key = method.replace(".", "_") + "_response"
        raw = extract_node(body, node_key)
        is_error_node = False
        if raw is None:
            raw = extract_node(body, "error_response")
            is_error_node = True
        if raw is None:
            raise GatewayError("PARSE", "无法解析网关响应", unknown=True)
        try:
            signature = json.loads(body).get("sign")
        except json.JSONDecodeError as exc:
            raise GatewayError("PARSE", "响应不是合法 JSON", unknown=True) from exc
        node = json.loads(raw)
        code = str(node.get("code", ""))
        if signature:
            if not rsa2_verify(raw, signature, self.public_key):
                log.error("响应验签失败 method=%s", method)
                raise GatewayError("SIGN_INVALID", "响应验签失败", unknown=True)
        elif code == "10000" or not is_error_node:
            # 成功响应必须带签名；没有签名一律按结果未知处理
            raise GatewayError("SIGN_MISSING", "响应缺少签名", unknown=True)
        if code != "10000":
            sub_code = node.get("sub_code")
            unknown = code == "20000" or (sub_code in UNKNOWN_SUB_CODES)
            raise GatewayError(code, node.get("msg", ""), sub_code, node.get("sub_msg"), unknown=unknown)
        return node
