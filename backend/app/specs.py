"""规格库：加载、搜索，以及“自定义规格”的解析。"""
from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

SPEC_FILE = Path(__file__).resolve().parent / "data" / "specs.json"

BG_COLORS: dict[str, dict[str, Any]] = {
    "white": {"name": "白色", "rgb": (255, 255, 255)},
    "blue": {"name": "蓝色", "rgb": (67, 142, 219)},
    "red": {"name": "红色", "rgb": (255, 0, 0)},
    "lightgray": {"name": "浅灰", "rgb": (235, 235, 235)},
    # 学历证书电子注册图像“浅蓝色”背景的常见参考值（RGB 100,197,255），以学校通知为准
    "lightblue": {"name": "浅蓝", "rgb": (100, 197, 255)},
}

CATEGORIES = ["考公", "考编", "考研", "教资", "等级考试", "职业资格", "学历", "求职", "证件", "签证", "通用尺寸"]

# 头部（头顶到下巴）占照片高度的比例、头顶留白比例：[下限, 目标, 上限]
DEFAULT_HEAD_RATIO = (0.50, 0.58, 0.70)
DEFAULT_TOP_MARGIN = (0.04, 0.08, 0.14)

_HEX_RE = re.compile(r"^#?([0-9a-fA-F]{6})$")
_CUSTOM_RE = re.compile(r"^custom:(\d{2,4})x(\d{2,4}):(\d{0,5})-(\d{0,5}):(\d{2,4})$")


@dataclass
class Spec:
    id: str
    name: str
    short: str
    category: str
    region: str
    width: int
    height: int
    size_mode: str = "exact"  # exact | min
    min_width: int | None = None
    min_height: int | None = None
    mm: list[float] | None = None
    dpi: int = 300
    kb_min: int | None = None
    kb_max: int | None = None
    format: str = "jpg"
    backgrounds: list[str] = field(default_factory=lambda: ["white"])
    head_ratio: tuple[float, float, float] = DEFAULT_HEAD_RATIO
    top_margin: tuple[float, float, float] = DEFAULT_TOP_MARGIN
    rules: list[str] = field(default_factory=list)
    checks: dict[str, bool] = field(default_factory=dict)
    official_tool: dict[str, Any] | None = None
    notes: str = ""
    window: str = ""
    sources: list[dict[str, Any]] = field(default_factory=list)
    verified_at: str | None = None
    status: str = "reference"
    hot: bool = False
    year: int | None = None
    keywords: list[str] = field(default_factory=list)
    custom: bool = False
    alert: str = ""  # 需要醒目提示的重大变化（例如改为官方 App 拍摄）
    verify_note: str = ""  # 核实方式与范围说明

    @property
    def key(self) -> str:
        return self.id

    @property
    def physical_mm(self) -> tuple[float, float]:
        if self.mm:
            return float(self.mm[0]), float(self.mm[1])
        return self.width / self.dpi * 25.4, self.height / self.dpi * 25.4

    def allows_bg(self, bg: str) -> bool:
        return bg in self.backgrounds or (self.custom and parse_hex(bg) is not None)

    def to_public(self, brief: bool = False) -> dict[str, Any]:
        data = asdict(self)
        data["key"] = self.key
        data["physical_mm"] = [round(v, 1) for v in self.physical_mm]
        data["size_text"] = size_text(self)
        data["kb_text"] = kb_text(self)
        data["bg_names"] = [bg_name(b) for b in self.backgrounds]
        if brief:
            for k in ("rules", "sources", "notes", "official_tool", "checks", "head_ratio", "top_margin", "keywords",
                      "verify_note"):
                data.pop(k, None)
            data["has_official_tool"] = bool(self.official_tool and self.official_tool.get("required"))
        return data


def parse_hex(value: str) -> tuple[int, int, int] | None:
    m = _HEX_RE.match(value or "")
    if not m:
        return None
    h = m.group(1)
    return int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)


def bg_rgb(bg: str) -> tuple[int, int, int]:
    if bg in BG_COLORS:
        return tuple(BG_COLORS[bg]["rgb"])  # type: ignore[return-value]
    rgb = parse_hex(bg)
    if rgb is None:
        raise ValueError(f"未知底色：{bg}")
    return rgb


def bg_name(bg: str) -> str:
    if bg in BG_COLORS:
        return BG_COLORS[bg]["name"]
    return f"自定义 #{bg.lstrip('#').upper()}"


def size_text(spec: Spec) -> str:
    if spec.size_mode == "min" and spec.min_width:
        return f"≥{spec.min_width}×{spec.min_height} 像素（导出 {spec.width}×{spec.height}）"
    text = f"{spec.width}×{spec.height} 像素"
    if spec.mm:
        text += f" · {spec.mm[0]:g}×{spec.mm[1]:g}mm"
    return text


def kb_text(spec: Spec) -> str:
    if spec.kb_min and spec.kb_max:
        return f"{spec.kb_min}–{spec.kb_max}KB"
    if spec.kb_max:
        return f"≤{spec.kb_max}KB"
    if spec.kb_min:
        return f"≥{spec.kb_min}KB"
    return "不限"


def _from_dict(raw: dict[str, Any]) -> Spec:
    raw = dict(raw)
    for key in ("head_ratio", "top_margin"):
        if key in raw and raw[key] is not None:
            raw[key] = tuple(raw[key])
        else:
            raw.pop(key, None)
    known = Spec.__dataclass_fields__.keys()
    return Spec(**{k: v for k, v in raw.items() if k in known})


class SpecLibrary:
    def __init__(self, path: Path = SPEC_FILE):
        self.path = path
        self.reload()

    def reload(self) -> None:
        payload = json.loads(self.path.read_text(encoding="utf-8"))
        specs = [_from_dict(item) for item in payload["specs"]]
        problems = validate_specs(specs)
        if problems:
            raise ValueError("规格库校验失败：\n" + "\n".join(problems))
        self._specs = {s.id: s for s in specs}
        self._order = [s.id for s in specs]

    def all(self) -> list[Spec]:
        return [self._specs[i] for i in self._order]

    def get(self, key: str) -> Spec | None:
        if key.startswith("custom:"):
            return parse_custom(key)
        return self._specs.get(key)

    def search(self, q: str = "", category: str = "") -> list[Spec]:
        q = (q or "").strip().lower()
        result = []
        for spec in self.all():
            if category and spec.category != category:
                continue
            if q:
                hay = " ".join([spec.name, spec.short, spec.region, spec.category, *spec.keywords]).lower()
                if not all(token in hay for token in q.split()):
                    continue
            result.append(spec)
        # 热门、已核实的排前面
        result.sort(key=lambda s: (not s.hot, s.status != "verified", self._order.index(s.id)))
        return result


def validate_specs(specs: list[Spec]) -> list[str]:
    problems: list[str] = []
    seen: set[str] = set()
    for s in specs:
        where = f"[{s.id}]"
        if s.id in seen:
            problems.append(f"{where} id 重复")
        seen.add(s.id)
        if not (40 <= s.width <= 2400 and 40 <= s.height <= 2400):
            problems.append(f"{where} 像素尺寸不合理")
        if s.size_mode == "min" and (not s.min_width or s.width < s.min_width or s.height < (s.min_height or 0)):
            problems.append(f"{where} min 模式下导出尺寸必须 ≥ 最小尺寸")
        if s.kb_min and s.kb_max and s.kb_min >= s.kb_max:
            problems.append(f"{where} KB 下限必须小于上限")
        for bg in s.backgrounds:
            if bg not in BG_COLORS:
                problems.append(f"{where} 未知底色 {bg}")
        if s.category not in CATEGORIES:
            problems.append(f"{where} 未知分类 {s.category}")
        if s.status not in {"verified", "reference", "standard"}:
            problems.append(f"{where} 未知状态 {s.status}")
        if s.status == "verified":
            if not s.verified_at or not any(src.get("official") for src in s.sources) or not s.verify_note:
                problems.append(f"{where} verified 规格必须有官方来源、核实日期和核实说明")
        if s.mm:
            ratio_px, ratio_mm = s.width / s.height, s.mm[0] / s.mm[1]
            if abs(ratio_px - ratio_mm) / ratio_mm > 0.02:
                problems.append(f"{where} 像素宽高比与毫米尺寸不一致（打印会变形）")
        lo, mid, hi = s.head_ratio
        if not (0.3 <= lo <= mid <= hi <= 0.9):
            problems.append(f"{where} head_ratio 不合理")
    return problems


def make_custom_key(width: int, height: int, kb_min: int | None, kb_max: int | None, dpi: int = 300) -> str:
    return f"custom:{width}x{height}:{kb_min or ''}-{kb_max or ''}:{dpi}"


def parse_custom(key: str) -> Spec | None:
    m = _CUSTOM_RE.match(key)
    if not m:
        return None
    w, h = int(m.group(1)), int(m.group(2))
    kb_min = int(m.group(3)) if m.group(3) else None
    kb_max = int(m.group(4)) if m.group(4) else None
    dpi = int(m.group(5))
    if not (60 <= w <= 2000 and 60 <= h <= 2000 and 72 <= dpi <= 1200):
        return None
    if kb_min and kb_max and kb_min >= kb_max:
        return None
    if kb_max is not None and kb_max < 3:
        return None
    ratio = h / w
    head = DEFAULT_HEAD_RATIO if ratio >= 1.15 else (0.50, 0.58, 0.69)
    return Spec(
        id=key,
        name=f"自定义规格 {w}×{h}",
        short=f"自定义 {w}×{h}",
        category="通用尺寸",
        region="自定义",
        width=w,
        height=h,
        dpi=dpi,
        kb_min=kb_min,
        kb_max=kb_max,
        backgrounds=["white", "blue", "red", "lightgray"],
        head_ratio=head,
        notes="按你输入的报名系统要求生成。",
        status="standard",
        custom=True,
    )


library = SpecLibrary()
