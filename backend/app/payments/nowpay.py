"""即刻收（Vibe Pay 智能收款套件）直连模式 OpenAPI 封装。

接口与字段以官方文档为准：https://aipay.alipay.com/docs/vibe-pay/nowpay/llms.txt
- charge.query      商品收费能力与档位
- purchase.consult  买断/时长包访问决策（本产品的“备考季月卡”）
- quota.query       次数包余额（以 remaining 为准）
- purchase.create   获取购买入口（out_request_no 幂等，30 分钟有效）
- quota.verify      核销（amount 显式传 1，只有 SUCCEEDED 才算扣减成功）
- quota.refresh     用原 out_request_no 查询核销结果（不会新扣）
"""
from __future__ import annotations

from typing import Any, Protocol

from .gateway import AlipayGateway, GatewayError

M_CHARGE_QUERY = "alipay.aipay.nowpaydirect.charge.query"
M_PURCHASE_CONSULT = "alipay.aipay.nowpaydirect.purchase.consult"
M_QUOTA_QUERY = "alipay.aipay.nowpaydirect.quota.query"
M_PURCHASE_CREATE = "alipay.aipay.nowpaydirect.purchase.create"
M_QUOTA_VERIFY = "alipay.aipay.nowpaydirect.quota.verify"
M_QUOTA_REFRESH = "alipay.aipay.nowpaydirect.quota.refresh"

# 业务错误码
QUOTA_INSUFFICIENT = "NOW_PAY_QUOTA_INSUFFICIENT"
CONSUME_NOT_FOUND = "CONSUME_REQUEST_NOT_FOUND"
CONSUME_CONFLICT = "NOW_PAY_QUOTA_CONSUME_CONFLICT"
LINK_CREATING = "NOW_PAY_PURCHASE_LINK_CREATING"
ORDER_CONFLICT = "NOW_PAY_ORDER_CONFLICT"
NOT_PURCHASABLE = "NOW_PAY_PRODUCT_NOT_PURCHASABLE"
OPTION_UNAVAILABLE = "NOW_PAY_CHARGING_OPTION_UNAVAILABLE"

NowPayError = GatewayError


class NowPayClient(Protocol):
    def charge_query(self, product_id: str) -> dict[str, Any]: ...

    def purchase_consult(self, product_id: str, buyer: str, callback_url: str | None = None) -> dict[str, Any]: ...

    def quota_query(self, product_id: str, buyer: str) -> dict[str, Any]: ...

    def purchase_create(self, out_request_no: str, product_id: str, buyer: str, sku_id: str | None,
                        callback_url: str | None) -> dict[str, Any]: ...

    def quota_verify(self, out_request_no: str, product_id: str, buyer: str, amount: int,
                     consume_reason: str) -> dict[str, Any]: ...

    def quota_refresh(self, out_request_no: str, product_id: str, buyer: str) -> dict[str, Any]: ...


class DirectNowPayClient:
    """直连模式：应用服务端用自己的应用凭证签名调用。"""

    def __init__(self, gateway: AlipayGateway):
        self.gw = gateway

    def charge_query(self, product_id: str) -> dict[str, Any]:
        return self.gw.call(M_CHARGE_QUERY, {"out_product_id": product_id})

    def purchase_consult(self, product_id: str, buyer: str, callback_url: str | None = None) -> dict[str, Any]:
        biz: dict[str, Any] = {"out_product_id": product_id, "external_buyer_id": buyer}
        if callback_url:
            biz["callback_url"] = callback_url
        return self.gw.call(M_PURCHASE_CONSULT, biz)

    def quota_query(self, product_id: str, buyer: str) -> dict[str, Any]:
        return self.gw.call(M_QUOTA_QUERY, {"out_product_id": product_id, "external_buyer_id": buyer})

    def purchase_create(self, out_request_no: str, product_id: str, buyer: str, sku_id: str | None,
                        callback_url: str | None) -> dict[str, Any]:
        biz: dict[str, Any] = {"out_request_no": out_request_no, "out_product_id": product_id, "external_buyer_id": buyer}
        if sku_id:
            biz["sku_id"] = sku_id
        if callback_url:
            biz["callback_url"] = callback_url
        return self.gw.call(M_PURCHASE_CREATE, biz)

    def quota_verify(self, out_request_no: str, product_id: str, buyer: str, amount: int,
                     consume_reason: str) -> dict[str, Any]:
        return self.gw.call(M_QUOTA_VERIFY, {
            "out_request_no": out_request_no,
            "out_product_id": product_id,
            "external_buyer_id": buyer,
            "amount": int(amount),
            "consume_reason": consume_reason[:256],
        })

    def quota_refresh(self, out_request_no: str, product_id: str, buyer: str) -> dict[str, Any]:
        return self.gw.call(M_QUOTA_REFRESH, {
            "out_request_no": out_request_no, "out_product_id": product_id, "external_buyer_id": buyer,
        })
