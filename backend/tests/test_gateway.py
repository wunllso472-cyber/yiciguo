"""RSA2 签名、响应验签、原始节点提取。"""
import base64
import json
from urllib.parse import parse_qs

import httpx
import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa

from app.payments.gateway import (
    AlipayGateway,
    GatewayError,
    extract_node,
    load_private_key,
    rsa2_sign,
    rsa2_verify,
    sign_content,
)


@pytest.fixture(scope="module")
def keys():
    priv = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    pkcs8_b64 = base64.b64encode(priv.private_bytes(serialization.Encoding.DER, serialization.PrivateFormat.PKCS8,
                                                    serialization.NoEncryption())).decode()
    pkcs1_b64 = base64.b64encode(priv.private_bytes(serialization.Encoding.DER,
                                                    serialization.PrivateFormat.TraditionalOpenSSL,
                                                    serialization.NoEncryption())).decode()
    pub_b64 = base64.b64encode(priv.public_key().public_bytes(serialization.Encoding.DER,
                                                              serialization.PublicFormat.SubjectPublicKeyInfo)).decode()
    return priv, pkcs8_b64, pkcs1_b64, pub_b64


def signed_body(priv, node_key: str, node: dict) -> str:
    raw = json.dumps(node, ensure_ascii=False, separators=(",", ":"))
    sig = rsa2_sign(raw, priv)
    return '{"%s":%s,"sign":"%s"}' % (node_key, raw, sig)


def test_sign_content_sorted_and_skips_empty():
    s = sign_content({"b": "2", "a": "1", "sign": "x", "c": "", "biz_content": '{"k":"v"}'})
    assert s == 'a=1&b=2&biz_content={"k":"v"}'


def test_load_keys_without_pem_headers(keys):
    priv, pkcs8, pkcs1, _ = keys
    for k in (pkcs8, pkcs1):
        loaded = load_private_key(k)
        assert loaded.private_numbers() == priv.private_numbers()


def test_build_params_signature_verifies(keys):
    priv, pkcs8, _, pub = keys
    gw = AlipayGateway("2021000000000001", pkcs8, pub)
    params = gw.build_params("alipay.aipay.nowpaydirect.quota.query", {"out_product_id": "np_x", "external_buyer_id": "u1"})
    assert params["sign_type"] == "RSA2" and params["version"] == "1.0" and params["charset"] == "utf-8"
    assert json.loads(params["biz_content"]) == {"out_product_id": "np_x", "external_buyer_id": "u1"}
    assert rsa2_verify(sign_content(params), params["sign"], priv.public_key())


def test_extract_node_handles_nested_and_escaped():
    body = '{"x_response":{"a":"}{\\"","b":{"c":[1,{"d":2}]}},"sign":"abc"}'
    assert extract_node(body, "x_response") == '{"a":"}{\\"","b":{"c":[1,{"d":2}]}}'
    assert extract_node(body, "missing") is None


def test_parse_success_and_tamper(keys):
    priv, pkcs8, _, pub = keys
    gw = AlipayGateway("app", pkcs8, pub)
    m = "alipay.aipay.nowpaydirect.quota.query"
    body = signed_body(priv, "alipay_aipay_nowpaydirect_quota_query_response",
                       {"code": "10000", "msg": "Success", "quota_unit": "COUNT", "total": 3, "used": 1, "remaining": 2})
    assert gw.parse_response(m, body)["remaining"] == 2
    with pytest.raises(GatewayError) as e:
        gw.parse_response(m, body.replace('"remaining":2', '"remaining":9'))
    assert e.value.code == "SIGN_INVALID" and e.value.unknown


def test_parse_business_error_is_definite(keys):
    priv, pkcs8, _, pub = keys
    gw = AlipayGateway("app", pkcs8, pub)
    m = "alipay.aipay.nowpaydirect.quota.verify"
    body = signed_body(priv, "alipay_aipay_nowpaydirect_quota_verify_response",
                       {"code": "40004", "msg": "Business Failed", "sub_code": "NOW_PAY_QUOTA_INSUFFICIENT", "sub_msg": "额度不足"})
    with pytest.raises(GatewayError) as e:
        gw.parse_response(m, body)
    assert e.value.sub_code == "NOW_PAY_QUOTA_INSUFFICIENT" and not e.value.unknown
    body = signed_body(priv, "alipay_aipay_nowpaydirect_quota_verify_response",
                       {"code": "20000", "msg": "Service Currently Unavailable", "sub_code": "isp.unknow-error"})
    with pytest.raises(GatewayError) as e:
        gw.parse_response(m, body)
    assert e.value.unknown


def test_unsigned_success_is_rejected(keys):
    _, pkcs8, _, pub = keys
    gw = AlipayGateway("app", pkcs8, pub)
    with pytest.raises(GatewayError) as e:
        gw.parse_response("a.b", '{"a_b_response":{"code":"10000","msg":"Success"}}')
    assert e.value.code == "SIGN_MISSING" and e.value.unknown
    with pytest.raises(GatewayError) as e:
        gw.parse_response("a.b", '{"error_response":{"code":"40002","msg":"Invalid Arguments","sub_code":"isv.invalid-signature"}}')
    assert e.value.code == "40002" and not e.value.unknown


def test_call_posts_form_and_handles_network_error(keys):
    priv, pkcs8, _, pub = keys
    seen = {}

    def handler(request: httpx.Request):
        form = parse_qs(request.content.decode())
        seen.update({k: v[0] for k, v in form.items()})
        node = {"code": "10000", "msg": "Success", "capability_status": "ENABLED", "charging_options": []}
        return httpx.Response(200, text=signed_body(priv, "alipay_aipay_nowpaydirect_charge_query_response", node))

    gw = AlipayGateway("app", pkcs8, pub, http=httpx.Client(transport=httpx.MockTransport(handler)))
    node = gw.call("alipay.aipay.nowpaydirect.charge.query", {"out_product_id": "np_1"})
    assert node["capability_status"] == "ENABLED"
    assert seen["method"] == "alipay.aipay.nowpaydirect.charge.query" and "sign" in seen

    def boom(request):
        raise httpx.ConnectTimeout("timeout")

    gw2 = AlipayGateway("app", pkcs8, pub, http=httpx.Client(transport=httpx.MockTransport(boom)))
    with pytest.raises(GatewayError) as e:
        gw2.call("alipay.aipay.nowpaydirect.quota.verify", {})
    assert e.value.unknown
