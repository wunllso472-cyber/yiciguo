import { useEffect, useRef, useState } from "react";
import { Link, useParams, useSearchParams } from "react-router-dom";
import { api, bgHex, track, type Spec } from "../api";
import SpecDrawing from "../components/SpecDrawing";
import Uploader, { ShootingTips } from "../components/Uploader";
import { PageTitle, Sheet, SpecBadge, Spinner } from "../components/ui";
import { useApp } from "../state";

export default function SpecPage() {
  const { key = "" } = useParams();
  const [search] = useSearchParams();
  const redoOf = search.get("redo") ?? "";
  const [spec, setSpec] = useState<Spec | null>(null);
  const [error, setError] = useState("");
  const [bg, setBg] = useState("");
  const [fbOpen, setFbOpen] = useState(false);
  const makeRef = useRef<HTMLElement>(null);
  const [makeVisible, setMakeVisible] = useState(false);

  useEffect(() => {
    const el = makeRef.current;
    if (!el || typeof IntersectionObserver === "undefined") return;
    const io = new IntersectionObserver(([entry]) => setMakeVisible(entry.isIntersecting), { threshold: 0.2 });
    io.observe(el);
    return () => io.disconnect();
  }, [spec]);

  useEffect(() => {
    setSpec(null);
    const load = key.startsWith("custom:")
      ? api.post<Spec>("/api/specs/custom", parseCustom(key))
      : api.get<Spec>(`/api/specs/${encodeURIComponent(key)}`);
    load
      .then((s) => {
        setSpec(s);
        setBg(s.backgrounds[0]);
        track("spec_view", { spec: s.key });
      })
      .catch((e) => setError((e as Error).message));
  }, [key]);

  if (error) return <div className="page"><p className="form-error">{error}</p><Link to="/">返回首页</Link></div>;
  if (!spec) return <div className="page loading-row"><Spinner label="加载规格…" /></div>;

  const rows: [string, string][] = [
    ["像素尺寸", spec.size_mode === "min" ? `≥${spec.min_width}×${spec.min_height}（导出 ${spec.width}×${spec.height}）` : `${spec.width} × ${spec.height}`],
    ["打印尺寸", `${spec.physical_mm[0]} × ${spec.physical_mm[1]} mm`],
    ["文件大小", spec.kb_text],
    ["文件格式", "JPG"],
    ["底色", spec.bg_names.join("、")],
    ["分辨率", `${spec.dpi} dpi`],
  ];

  return (
    <div className="page spec-page">
      <PageTitle title={`${spec.name}照片要求`} />
      <header className="spec-head">
        <p className="crumb"><Link to="/">规格库</Link> / {spec.category}</p>
        <h1>{spec.name}</h1>
        <div className="spec-tags">
          <SpecBadge spec={spec} />
          {spec.window && <span className="window">{spec.window}</span>}
        </div>
        {spec.alert && <p className="notice notice-strong" role="alert">{spec.alert}</p>}
        {spec.status === "reference" && (
          <p className="notice">这是参考规格，暂未逐条对照官方原文核实（原因见页面底部“资料来源”）。上传前请再看一眼报名系统的要求；不一致时可以<Link to="/custom">按报名系统要求自定义</Link>。</p>
        )}
        {spec.status === "verified" && (
          <p className="verified-line">已于 {spec.verified_at} 对照官方原文核对，来源见页面底部。</p>
        )}
      </header>

      <div className="spec-grid">
        <div className="spec-figure">
          <SpecDrawing
            width={spec.width}
            height={spec.height}
            mm={spec.mm}
            kbText={spec.kb_text}
            dpi={spec.dpi}
            bg={bgHex(bg)}
            bgLabel={`${spec.bg_names[spec.backgrounds.indexOf(bg)] ?? ""}底`}
            headRatio={spec.head_ratio?.[1]}
            minMode={false}
          />
        </div>

        <div className="spec-info">
          <dl className="fields">
            {rows.map(([k, v]) => (
              <div key={k}>
                <dt>{k}</dt>
                <dd>{v}</dd>
              </div>
            ))}
          </dl>
          {spec.rules && spec.rules.length > 0 && (
            <ul className="rules">
              {spec.rules.map((r) => <li key={r}>{r}</li>)}
            </ul>
          )}
          {spec.notes && <p className="notes">{spec.notes}</p>}
        </div>
      </div>

      {spec.official_tool?.required && (
        <section className="callout">
          <h3>这场考试要用官方照片处理工具</h3>
          <p>{spec.official_tool.note}</p>
        </section>
      )}

      {!makeVisible && (
        <div className="sticky-cta">
          <button className="btn btn-primary btn-block" onClick={() => makeRef.current?.scrollIntoView({ behavior: "smooth", block: "center" })}>
            上传照片，免费预审
          </button>
        </div>
      )}

      <section className="make" aria-labelledby="make-title" ref={makeRef} id="make">
        <h2 id="make-title">{redoOf ? "重新拍一张（免费重做）" : "开始制作"}</h2>
        {spec.backgrounds.length > 1 && (
          <div className="bg-pick" role="radiogroup" aria-label="选择底色">
            {spec.backgrounds.map((b, i) => (
              <button key={b} role="radio" aria-checked={bg === b} className={`swatch ${bg === b ? "swatch-on" : ""}`} onClick={() => setBg(b)}>
                <span className="swatch-color" style={{ background: bgHex(b) }} />
                {spec.bg_names[i]}
              </button>
            ))}
          </div>
        )}
        <Uploader specKey={spec.key} bg={bg} redoOf={redoOf} />
        <details className="tips-box">
          <summary>怎么拍更容易一次通过</summary>
          <ShootingTips />
        </details>
      </section>

      {spec.sources && (
        <section className="sources">
          <h3>资料来源</h3>
          {spec.sources.length === 0 ? (
            <p className="fine">暂未收录公告链接。{spec.status === "standard" ? "这是通用尺寸约定。" : "请以报名系统要求为准。"}</p>
          ) : (
            <ul>
              {spec.sources.map((s) => (
                <li key={s.url}>
                  <a href={s.url} target="_blank" rel="noreferrer nofollow">{s.title}</a>
                  <span className={s.official ? "src-official" : "src-third"}>{s.official ? "官方" : "第三方"}</span>
                </li>
              ))}
            </ul>
          )}
          {spec.verify_note && <p className="verify-note">{spec.verify_note}</p>}
          <p className="fine">
            {spec.verified_at ? `核实日期 ${spec.verified_at}。` : ""}官方要求可能随年度调整，最终以报名系统为准。
            <button className="btn-text" onClick={() => setFbOpen(true)}>规格有变化？告诉我们</button>
          </p>
        </section>
      )}
      <FeedbackSheet open={fbOpen} onClose={() => setFbOpen(false)} specId={spec.key} />
    </div>
  );
}

function parseCustom(key: string) {
  const m = key.match(/^custom:(\d+)x(\d+):(\d*)-(\d*):(\d+)$/);
  if (!m) return {};
  return {
    width: Number(m[1]),
    height: Number(m[2]),
    kb_min: m[3] ? Number(m[3]) : null,
    kb_max: m[4] ? Number(m[4]) : null,
    dpi: Number(m[5]),
  };
}

function FeedbackSheet({ open, onClose, specId }: { open: boolean; onClose: () => void; specId: string }) {
  const { toast } = useApp();
  const [content, setContent] = useState("");
  const [url, setUrl] = useState("");
  const [busy, setBusy] = useState(false);
  const submit = async () => {
    setBusy(true);
    try {
      await api.post("/api/specs/feedback", { spec_id: specId, content, url: url || null });
      toast("已收到，核实后会更新规格");
      setContent("");
      setUrl("");
      onClose();
    } catch (e) {
      toast((e as Error).message);
    } finally {
      setBusy(false);
    }
  };
  return (
    <Sheet open={open} onClose={onClose} title="报告规格变化">
      <div className="form">
        <label>
          <span>哪里不对</span>
          <textarea rows={4} value={content} onChange={(e) => setContent(e.target.value)} placeholder="例如：今年改成 ≤50KB，蓝底" />
        </label>
        <label>
          <span>公告链接（可选）</span>
          <input type="url" value={url} onChange={(e) => setUrl(e.target.value)} placeholder="https://" />
        </label>
        <button className="btn btn-primary btn-block" disabled={busy || content.trim().length < 4} onClick={submit}>提交</button>
      </div>
    </Sheet>
  );
}
