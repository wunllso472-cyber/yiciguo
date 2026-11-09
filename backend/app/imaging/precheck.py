"""免费 AI 预审报告：把分析指标 + 当前规格 + 渲染结果，转成逐项“通过/警告/不通过 + 修改建议”。

阈值说明：这些都是工程经验阈值（见 tests/test_imaging.py 的校准用例），只作为参考提示，不代表报名系统的审核结论。
"""
from __future__ import annotations

from typing import Any

from ..specs import Spec, bg_name
from .render import CropPlan, EncodeResult, color_distance

REJECT_REASONS = {
    "no_face": ("未检测到人脸", "请上传本人正面、五官清晰的照片，脸部不要太小或被遮挡。"),
    "multi_face": ("检测到多张人脸", "报名照只能有本人，请裁掉或重拍，背景中不要出现其他人脸（包括海报、屏幕）。"),
    "crown_cut": ("头顶被截断", "照片里头顶不完整，请重拍：头顶上方留出一些空间，露出双肩。"),
}

SHARP_PASS = 60.0
SHARP_WARN = 25.0


def _item(cid: str, label: str, status: str, value: str, tip: str = "") -> dict[str, str]:
    return {"id": cid, "label": label, "status": status, "value": value, "tip": tip}


def rejection_report(reason: str, metrics: dict[str, Any]) -> dict[str, Any]:
    title, tip = REJECT_REASONS.get(reason, ("无法处理这张照片", "请换一张正面清晰的照片再试。"))
    value = f"{metrics.get('face_count', 0)} 张" if reason in ("no_face", "multi_face") else "不完整"
    return {
        "overall": "fail",
        "summary": f"{title}，无法继续制作",
        "items": [_item(reason, title, "fail", value, tip)],
        "counts": {"pass": 0, "warn": 0, "fail": 1},
    }


def build_report(
    metrics: dict[str, Any],
    spec: Spec,
    bg: str,
    plan: CropPlan,
    encoded: EncodeResult,
    clothing: tuple[int, int, int] | None,
    bg_rgb: tuple[int, int, int],
) -> dict[str, Any]:
    items: list[dict[str, str]] = []
    checks = spec.checks or {}

    items.append(_item("face_count", "人脸检测", "pass", "1 张正脸"))

    # 姿态
    yaw, pitch = abs(metrics["yaw"]), abs(metrics["pitch"])
    if yaw <= 8 and pitch <= 12:
        items.append(_item("pose", "正面姿态", "pass", f"转头 {yaw:.0f}° · 俯仰 {pitch:.0f}°"))
    elif yaw <= 15 and pitch <= 20:
        items.append(_item("pose", "正面姿态", "warn", f"转头 {yaw:.0f}° · 俯仰 {pitch:.0f}°",
                           "头部略有偏转或俯仰，建议平视镜头、下巴微收、肩膀放正。"))
    else:
        items.append(_item("pose", "正面姿态", "fail", f"转头 {yaw:.0f}° · 俯仰 {pitch:.0f}°",
                           "头部明显偏转或抬头/低头，报名照要求正面，请平视镜头重拍。"))

    roll = abs(metrics["roll"])
    if metrics.get("roll_corrected"):
        items.append(_item("roll", "头部水平", "pass", f"已自动摆正 {roll:.0f}°"))
    elif roll > 15:
        items.append(_item("roll", "头部水平", "warn", f"歪斜 {roll:.0f}°", "头部歪斜较大，请保持头部端正后重拍。"))
    else:
        items.append(_item("roll", "头部水平", "pass", "端正"))

    # 清晰度
    sharp = metrics["sharpness"]
    if sharp >= SHARP_PASS:
        items.append(_item("sharpness", "清晰度", "pass", f"清晰（{sharp:.0f}）"))
    elif sharp >= SHARP_WARN:
        items.append(_item("sharpness", "清晰度", "warn", f"略模糊（{sharp:.0f}）",
                           "对焦不够清晰：擦干净镜头、保持手稳，光线充足时再拍。"))
    else:
        items.append(_item("sharpness", "清晰度", "fail", f"模糊（{sharp:.0f}）",
                           "照片模糊，可能会被驳回。请在光线充足处、对焦到脸部后重拍。"))

    # 曝光
    luma, clip = metrics["face_luma"], metrics["face_clip"]
    if luma < 60 or luma > 232:
        items.append(_item("exposure", "曝光", "fail", "过暗" if luma < 60 else "过曝",
                           "脸部太暗看不清" if luma < 60 else "脸部过亮丢失细节，请避开强光直射。"))
    elif luma < 85 or luma > 212 or clip > 0.12:
        items.append(_item("exposure", "曝光", "warn", "偏暗" if luma < 85 else "偏亮",
                           "建议面向窗户或柔和灯光拍摄，避免逆光和强光直射。"))
    else:
        items.append(_item("exposure", "曝光", "pass", "正常"))

    # 光照均匀（阴阳脸）
    diff = metrics["light_diff"]
    if diff <= 0.15:
        items.append(_item("lighting", "光照均匀", "pass", f"左右脸亮度差 {diff * 100:.0f}%"))
    elif diff <= 0.35:
        items.append(_item("lighting", "光照均匀", "warn", f"左右脸亮度差 {diff * 100:.0f}%",
                           "有轻微阴阳脸，建议正对光源，或用白纸在暗侧补光。"))
    else:
        items.append(_item("lighting", "光照均匀", "fail", f"左右脸亮度差 {diff * 100:.0f}%",
                           "阴阳脸明显，容易被驳回。请正对窗户或灯光重拍。"))

    # 双眼睁开
    blink = metrics["blink"]
    if blink > 0.6:
        items.append(_item("eyes", "双眼睁开", "fail", "疑似闭眼", "请自然睁开双眼重拍。"))
    elif blink > 0.45:
        items.append(_item("eyes", "双眼睁开", "warn", "眼睛偏眯", "请自然睁眼，不要眯眼或大笑。"))
    else:
        items.append(_item("eyes", "双眼睁开", "pass", "正常"))

    # 表情
    neutral = checks.get("neutral_expression", False)
    if metrics["jaw_open"] > 0.25:
        items.append(_item("expression", "表情自然", "warn", "嘴巴张开", "请自然闭嘴，表情平和。"))
    elif metrics["smile"] > 0.55 and neutral:
        items.append(_item("expression", "表情自然", "warn", "露齿笑",
                           "该规格要求表情自然，露齿大笑可能被驳回，建议嘴巴闭合、微笑即可。"))
    else:
        items.append(_item("expression", "表情自然", "pass", "自然"))

    # 眉毛/额头
    brow = metrics.get("brow_skin")
    if brow is not None and brow < 0.35:
        status = "warn"
        tip = "刘海可能遮挡额头或眉毛" + ("，该规格要求露出眉毛，请把刘海撩开后重拍。" if checks.get("eyebrows_visible") else "，建议露出眉毛。")
        items.append(_item("brows", "露出眉毛", status, "可能被遮挡", tip))
    elif brow is not None:
        items.append(_item("brows", "露出眉毛", "pass", "未见遮挡"))

    # 耳朵（启发式，仅在规格要求时提示）
    if checks.get("ears_visible"):
        ears = [v for v in metrics.get("ear_skin", []) if v is not None]
        if ears and max(ears) < 0.2:
            items.append(_item("ears", "露出双耳", "warn", "可能被头发遮挡",
                               "该规格要求露耳，请把头发别到耳后再拍（本项为启发式检测，仅供参考）。"))
        else:
            items.append(_item("ears", "露出双耳", "pass", "未见明显遮挡"))

    # 眼镜反光
    glare = metrics["glare"]
    if glare > 0.04:
        items.append(_item("glare", "眼镜反光", "warn", "检测到眼部高光",
                           "镜片反光会遮挡眼睛，请调整角度或摘掉眼镜重拍。"))
    else:
        items.append(_item("glare", "眼镜反光", "pass", "未发现反光"))
    if checks.get("no_glasses"):
        items.append(_item("no_glasses", "不戴眼镜", "info", "请自行确认", "该规格要求不戴眼镜，请摘镜拍摄。"))

    # 源图像素
    face_px = metrics.get("face_px", 0)
    if plan.needs_upscale:
        items.append(_item("resolution", "源图像素", "fail", f"脸部仅 {face_px:.0f}px",
                           f"源图分辨率不够输出 {plan.out_w}×{plan.out_h}，不能放大使用。请用后置摄像头或靠近一些重拍。"))
    else:
        items.append(_item("resolution", "源图像素", "pass", f"充足（无需放大）"))

    # 构图
    problems = []
    if plan.overflow_bottom > 0.06:
        problems.append("肩部不完整")
    if plan.overflow_top > 0.02:
        problems.append("头顶空间不足")
    if plan.overflow_side > 0.10:
        problems.append("左右空间不足")
    if problems:
        items.append(_item("framing", "构图完整", "warn", "、".join(problems),
                           "拍摄时离镜头远一点，头顶上方留空，露出双肩，人在画面正中。"))
    else:
        items.append(_item("framing", "构图完整", "pass", f"头部占 {plan.head_ratio * 100:.0f}%"))

    # 背景
    if metrics["bg_edge"] > 0.10 or metrics["bg_std"] > 45:
        items.append(_item("background", "原背景", "warn", "较杂乱",
                           "背景越干净，换底边缘越自然。建议在白墙或纯色墙前拍摄。"))
    else:
        items.append(_item("background", "原背景", "pass", "干净"))

    # 衣服与底色
    if clothing is not None:
        de = color_distance(clothing, bg_rgb)
        if de < 18:
            items.append(_item("clothing", "衣服与底色", "warn", f"与{bg_name(bg)}接近",
                               "衣服颜色和底色太接近，边界不清。建议换深色上衣，或在允许时换另一种底色。"))
        else:
            items.append(_item("clothing", "衣服与底色", "pass", "区分明显"))

    # 编码
    if not encoded.ok:
        msg = (f"无法压缩到 {spec.kb_max}KB 以内" if encoded.problem == "kb_too_small"
               else f"文件小于 {spec.kb_min}KB 下限")
        items.append(_item("encode", "文件大小", "fail", msg, "该规格的 KB 限制与像素尺寸冲突，请核对报名系统要求。"))
    elif encoded.quality < 45:
        items.append(_item("encode", "压缩质量", "warn", f"JPEG 质量 {encoded.quality}",
                           "为满足 KB 上限压缩较多，画质会有损失，属正常现象。"))

    counts = {s: sum(1 for i in items if i["status"] == s) for s in ("pass", "warn", "fail")}
    overall = "fail" if counts["fail"] else ("warn" if counts["warn"] else "pass")
    summary = {
        "pass": f"{len(items)} 项检测全部通过",
        "warn": f"{counts['warn']} 项需要注意，其余通过",
        "fail": f"{counts['fail']} 项不通过，建议按提示重拍",
    }[overall]
    return {"overall": overall, "summary": summary, "items": items, "counts": counts}
