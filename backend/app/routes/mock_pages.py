"""模拟的“支付宝托管购买页”（仅 YCG_PAY_MODE=mock 时注册，生产环境不存在这些路由）。"""
from __future__ import annotations

import html

from fastapi import APIRouter, Form, HTTPException
from fastapi.responses import HTMLResponse, RedirectResponse

from ..payments import payments
from ..payments.mock import MOCK_PRODUCTS, MockNowPayClient

router = APIRouter(prefix="/mock/pay", tags=["mock"])

PAGE = """<!doctype html><html lang="zh-CN"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><title>模拟收银台</title>
<style>
body{{margin:0;font-family:-apple-system,"PingFang SC","Microsoft YaHei",sans-serif;background:#f2f3f5;color:#1d2129}}
.wrap{{max-width:420px;margin:0 auto;padding:24px 16px}}
.tag{{display:inline-block;background:#fff3cd;color:#8a6100;border-radius:6px;padding:4px 10px;font-size:13px}}
.card{{background:#fff;border-radius:14px;padding:20px;margin-top:16px}}
h1{{font-size:18px;margin:12px 0 4px}} .muted{{color:#86909c;font-size:13px}}
label{{display:flex;justify-content:space-between;align-items:center;border:1px solid #e5e6eb;border-radius:10px;padding:12px 14px;margin-top:10px;cursor:pointer}}
label b{{font-size:18px}} input{{margin-right:8px}}
button{{width:100%;border:0;border-radius:10px;padding:14px;font-size:16px;margin-top:14px;cursor:pointer}}
.pay{{background:#1677ff;color:#fff}} .cancel{{background:#fff;color:#4e5969;border:1px solid #e5e6eb}}
</style></head><body><div class="wrap">
<span class="tag">⚠ 本地模拟收银台 · 不会产生真实扣款</span>
<div class="card"><h1>{name}</h1><div class="muted">受益人：{buyer}　请求号：{req}</div>
<form method="post" action="/mock/pay/{link}/confirm">{options}
<button class="pay" type="submit">确认支付（模拟）</button></form>
<form method="post" action="/mock/pay/{link}/cancel"><button class="cancel" type="submit">取消支付</button></form>
</div></div></body></html>"""

DONE = """<!doctype html><html lang="zh-CN"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><title>模拟收银台</title></head>
<body style="font-family:sans-serif;text-align:center;padding:60px 16px;color:#1d2129">
<h2>{title}</h2><p style="color:#86909c">{tip}</p></body></html>"""


def _client() -> MockNowPayClient:
    if not isinstance(payments.client, MockNowPayClient):
        raise HTTPException(404)
    return payments.client


@router.get("/{link_id}", response_class=HTMLResponse)
def page(link_id: str):
    client = _client()
    link = client.get_link(link_id)
    if link is None:
        raise HTTPException(404, "链接不存在")
    if link.status != "open":
        return DONE.format(title="该购买链接已处理", tip=f"状态：{link.status}")
    p = MOCK_PRODUCTS[link.product]
    opts = [o for o in p["charging_options"] if not link.sku_id or o["sku_id"] == link.sku_id]
    options = "".join(
        f'<label><span><input type="radio" name="sku_id" value="{html.escape(o["sku_id"])}" {"checked" if i == 0 else ""}>'
        f'{html.escape(o["display_name"])}</span><b>¥{html.escape(o["price"])}</b></label>'
        for i, o in enumerate(opts)
    )
    return PAGE.format(name=html.escape(p["product_name"]), buyer=html.escape(link.buyer[:7]),
                       req=html.escape(link.out_request_no or "-"), link=html.escape(link_id), options=options)


def _back(link, title: str):
    if link and link.callback_url:
        return RedirectResponse(link.callback_url, status_code=303)
    return HTMLResponse(DONE.format(title=title, tip="请回到原页面，点击“我已支付，刷新”"))


@router.post("/{link_id}/confirm")
def confirm(link_id: str, sku_id: str = Form("")):
    link = _client().complete_link(link_id, sku_id or None)
    if link is None:
        raise HTTPException(404)
    return _back(link, "支付成功（模拟）")


@router.post("/{link_id}/cancel")
def cancel(link_id: str):
    link = _client().cancel_link(link_id)
    return _back(link, "已取消支付")
