// 自定义规格：照着报名系统写的要求填，生成完全一致的照片。
import { useMemo, useState } from "react";
import { useNavigate, useSearchParams } from "react-router-dom";
import { api, track, type PhotoView, type Spec } from "../api";
import SpecDrawing from "../components/SpecDrawing";
import { PageTitle } from "../components/ui";
import { useApp } from "../state";

const PRESETS = [
  { name: "1 寸", w: 295, h: 413 },
  { name: "小 2 寸", w: 413, h: 531 },
  { name: "2 寸", w: 413, h: 579 },
  { name: "3:4", w: 480, h: 640 },
  { name: "身份证回执", w: 358, h: 441 },
];

export default function CustomPage() {
  const nav = useNavigate();
  const [search] = useSearchParams();
  const photoId = search.get("photo");
  const { toast } = useApp();
  const [w, setW] = useState("295");
  const [h, setH] = useState("413");
  const [kbMin, setKbMin] = useState("");
  const [kbMax, setKbMax] = useState("");
  const [dpi, setDpi] = useState("300");
  const [busy, setBusy] = useState(false);

  const problems = useMemo(() => {
    const out: string[] = [];
    const W = Number(w), H = Number(h);
    if (!(W >= 60 && W <= 2000 && H >= 60 && H <= 2000)) out.push("像素宽高需在 60–2000 之间");
    if (kbMin && kbMax && Number(kbMin) >= Number(kbMax)) out.push("KB 下限要小于上限");
    if (kbMax && Number(kbMax) < 3) out.push("KB 上限至少 3");
    return out;
  }, [w, h, kbMin, kbMax]);

  const submit = async () => {
    setBusy(true);
    try {
      const spec = await api.post<Spec>("/api/specs/custom", {
        width: Number(w),
        height: Number(h),
        kb_min: kbMin ? Number(kbMin) : null,
        kb_max: kbMax ? Number(kbMax) : null,
        dpi: Number(dpi) || 300,
      });
      track("custom_spec", { key: spec.key });
      if (photoId) {
        await api.post<PhotoView>(`/api/photos/${photoId}/select`, { spec_key: spec.key, bg: null });
        nav(`/photo/${photoId}`);
      } else {
        nav(`/spec/${encodeURIComponent(spec.key)}`);
      }
    } catch (e) {
      toast((e as Error).message);
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="page custom-page">
      <PageTitle title="自定义规格" />
      <h1>按报名系统的要求生成</h1>
      <p className="lede">把报名页面写的像素和文件大小照着填进来，生成的照片会完全符合。</p>

      <div className="spec-grid">
        <div className="spec-figure">
          <SpecDrawing width={Number(w) || 295} height={Number(h) || 413} bg="#FFFFFF" bgLabel="底色可选"
            kbText={kbMax ? `${kbMin ? `${kbMin}–` : "≤"}${kbMax}KB` : kbMin ? `≥${kbMin}KB` : "不限"} dpi={Number(dpi) || 300} />
        </div>
        <div className="form">
          <div className="presets" aria-label="常用尺寸">
            {PRESETS.map((p) => (
              <button key={p.name} className="chip" onClick={() => { setW(String(p.w)); setH(String(p.h)); }}>{p.name}</button>
            ))}
          </div>
          <div className="form-row">
            <label><span>宽（像素）</span><input inputMode="numeric" value={w} onChange={(e) => setW(e.target.value.replace(/\D/g, ""))} /></label>
            <label><span>高（像素）</span><input inputMode="numeric" value={h} onChange={(e) => setH(e.target.value.replace(/\D/g, ""))} /></label>
          </div>
          <div className="form-row">
            <label><span>最小 KB（可空）</span><input inputMode="numeric" value={kbMin} onChange={(e) => setKbMin(e.target.value.replace(/\D/g, ""))} /></label>
            <label><span>最大 KB（可空）</span><input inputMode="numeric" value={kbMax} onChange={(e) => setKbMax(e.target.value.replace(/\D/g, ""))} /></label>
          </div>
          <label><span>分辨率 dpi</span><input inputMode="numeric" value={dpi} onChange={(e) => setDpi(e.target.value.replace(/\D/g, ""))} /></label>
          {problems.map((p) => <p key={p} className="form-error">{p}</p>)}
          <button className="btn btn-primary btn-block" disabled={busy || problems.length > 0} onClick={submit}>
            {photoId ? "用这个规格重新生成" : "下一步：上传照片"}
          </button>
          <p className="fine">底色在下一步选择（白、蓝、红、浅灰）。</p>
        </div>
      </div>
    </div>
  );
}
