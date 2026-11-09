"""支付：即刻收直连（生产）或本地模拟（开发演示）。"""
from __future__ import annotations

from ..config import settings
from .service import PaymentService, PayError  # noqa: F401


def build_service() -> PaymentService:
    mode = settings.pay_mode
    if mode == "nowpay":
        from .gateway import AlipayGateway
        from .nowpay import DirectNowPayClient

        gw = AlipayGateway(
            app_id=settings.alipay_app_id,
            private_key=settings.alipay_private_key,
            alipay_public_key=settings.alipay_public_key,
            gateway=settings.alipay_gateway,
            app_auth_token=settings.alipay_app_auth_token,
        )
        if not settings.nowpay_product_count:
            raise RuntimeError("YCG_PAY_MODE=nowpay 时必须配置 NOWPAY_PRODUCT_COUNT（即刻收小程序里复制的商品 ID）")
        return PaymentService(DirectNowPayClient(gw), settings.nowpay_product_count, settings.nowpay_product_monthly,
                              settings.base_url, mode)
    if mode == "mock":
        from .mock import MOCK_COUNT_PRODUCT, MOCK_MONTHLY_PRODUCT, MockNowPayClient

        return PaymentService(MockNowPayClient(settings.base_url), MOCK_COUNT_PRODUCT, MOCK_MONTHLY_PRODUCT,
                              settings.base_url, mode)
    return PaymentService(None, "", "", settings.base_url, "off")


payments = build_service()
