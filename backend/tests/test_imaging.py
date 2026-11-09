"""图像：规格库校验、构图、KB 压缩、分析与预审。"""
import io

import numpy as np
import pytest
from PIL import Image

from app.config import settings
from app.imaging import get_engines
from app.imaging.analysis import analyze
from app.imaging.io import ImageLoadError, load_rgb
from app.imaging.precheck import build_report
from app.imaging.render import clothing_rgb, encode_jpeg, plan_crop, print_layout, render, validate_output, watermark_preview
from app.specs import library, make_custom_key, parse_custom, validate_specs, bg_rgb


@pytest.fixture(scope="module")
def analysis(portrait_bytes):
    face, matter = get_engines(settings.models_dir, settings.matting_model)
    return analyze(load_rgb(portrait_bytes), face, matter)


def test_spec_library_valid():
    specs = library.all()
    assert len(specs) >= 30
    assert validate_specs(specs) == []
    for s in specs:
        if s.status == "verified":
            assert s.verified_at and s.verify_note and any(src["official"] for src in s.sources), s.id
    assert library.search("江苏")[0].id == "js-sk-2027"
    # 已核实的关键数值（来自官方原文）
    ncre = library.get("ncre")
    assert (ncre.min_width, ncre.min_height, ncre.kb_min, ncre.kb_max) == (144, 192, 20, 200)
    jp = library.get("visa-jp")
    assert jp.mm == [35, 45] and jp.backgrounds == ["white"]
    assert not library.get("idcard-receipt").checks.get("no_glasses")  # 官方：常戴眼镜者应佩戴眼镜
    assert library.get("ky-fushi").alert  # 2027 考研改为学信网 App 拍摄


def test_validator_rejects_bad_verified_and_distorted_specs():
    from dataclasses import replace

    base = library.get("cun1")
    bad = replace(base, id="x1", status="verified", verified_at="2026-11-09", sources=[], verify_note="")
    assert any("verified" in p for p in validate_specs([bad]))
    distorted = replace(base, id="x2", width=300, height=300)
    assert any("宽高比" in p for p in validate_specs([distorted]))


def test_custom_spec():
    key = make_custom_key(358, 441, 14, 40, 350)
    spec = parse_custom(key)
    assert spec and spec.width == 358 and spec.kb_min == 14 and spec.kb_max == 40 and spec.custom
    assert parse_custom("custom:10x10:-:300") is None
    assert parse_custom(make_custom_key(300, 400, 50, 20)) is None


def test_load_rejects_garbage():
    with pytest.raises(ImageLoadError):
        load_rgb(b"not an image" * 200)


def test_analysis_metrics(analysis):
    assert analysis.ok
    g, m = analysis.geometry, analysis.metrics
    assert m["face_count"] == 1
    assert g["crown_y"] < g["face_y0"] < g["chin_y"]
    assert m["sharpness"] > 25 and 60 < m["face_luma"] < 230
    assert m["roll_corrected"]  # 原图头部略歪，已自动摆正


@pytest.mark.parametrize("spec_id,bg", [("js-sk-2027", "white"), ("gk-2027", "blue"), ("visa-us", "white"),
                                        ("ncre", "blue"), ("idcard-receipt", "white"), ("zk-diploma", "white"),
                                        ("crj-online", "white"), ("visa-jp", "white"), ("kj-qual", "white")])
def test_render_meets_spec(analysis, spec_id, bg):
    spec = library.get(spec_id)
    plan = plan_crop(analysis.geometry, spec)
    assert not plan.needs_upscale
    out = render(analysis.work, analysis.alpha, plan, bg_rgb(bg))
    assert out.shape == (plan.out_h, plan.out_w, 3)
    if spec.size_mode == "exact":
        assert (plan.out_w, plan.out_h) == (spec.width, spec.height)
    else:
        assert plan.out_w >= spec.min_width and plan.out_h >= spec.min_height
    if (plan.out_w, plan.out_h) != (spec.width, spec.height):
        from dataclasses import replace
        spec = replace(spec, width=plan.out_w, height=plan.out_h)
    enc = encode_jpeg(out, spec)
    assert enc.ok
    if spec.kb_max:
        assert len(enc.data) <= spec.kb_max * 1000
    checks = validate_output(enc.data, spec, bg_rgb(bg), plan)
    assert all(c["status"] == "pass" for c in checks), checks
    im = Image.open(io.BytesIO(enc.data))
    assert im.format == "JPEG" and round(im.info["dpi"][0]) == spec.dpi and len(im.getexif()) == 0
    report = build_report(analysis.metrics, spec, bg, plan, enc, clothing_rgb(analysis.work, analysis.alpha, analysis.geometry),
                          bg_rgb(bg))
    assert report["overall"] in ("pass", "warn")
    assert len(report["items"]) >= 10


def test_kb_min_respected(analysis):
    spec = parse_custom(make_custom_key(295, 413, 30, 60))
    plan = plan_crop(analysis.geometry, spec)
    enc = encode_jpeg(render(analysis.work, analysis.alpha, plan, bg_rgb("white")), spec)
    assert enc.ok and 30 * 1024 <= len(enc.data) <= 60 * 1000


def test_small_source_is_not_upscaled(analysis):
    small = dict(analysis.geometry)
    for k in ("cx", "crown_y", "chin_y", "eye_y", "face_x0", "face_x1", "face_y0", "face_w", "face_h", "image_w", "image_h"):
        small[k] = small[k] * 0.15
    us = plan_crop(small, library.get("visa-us"))
    assert us.needs_upscale
    gk = plan_crop(small, library.get("gk-2027"))  # “最小像素”规格回退到最小尺寸，仍不足时标记
    assert gk.out_h >= 413 or gk.needs_upscale


def test_no_face_rejected():
    face, matter = get_engines(settings.models_dir, settings.matting_model)
    rgb = np.tile(np.linspace(40, 220, 640, dtype=np.uint8)[None, :, None], (800, 1, 3))
    a = analyze(rgb, face, matter)
    assert not a.ok and a.reason == "no_face"


def test_preview_and_layout(analysis):
    spec = library.get("cun1")
    plan = plan_crop(analysis.geometry, spec)
    out = render(analysis.work, analysis.alpha, plan, bg_rgb("blue"))
    prev = Image.open(io.BytesIO(watermark_preview(out)))
    assert prev.height >= 480
    layout = Image.open(io.BytesIO(print_layout(out, spec)))
    assert layout.size in ((1800, 1200), (1200, 1800)) and round(layout.info["dpi"][0]) == 300
