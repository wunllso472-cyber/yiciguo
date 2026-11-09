import { useEffect, useMemo, useState } from "react";
import { Link } from "react-router-dom";
import { api, track, type SpecList } from "../api";
import SpecDrawing from "../components/SpecDrawing";
import { PageTitle, SpecRow, Spinner } from "../components/ui";
import { prefersReducedMotion } from "../env";

export default function Home() {
  const [q, setQ] = useState("");
  const [cat, setCat] = useState("");
  const [data, setData] = useState<SpecList | null>(null);
  const [error, setError] = useState("");
  const [showAll, setShowAll] = useState(false);

  useEffect(() => {
    track("visit", { ref: document.referrer.slice(0, 60) });
  }, []);

  useEffect(() => {
    const t = window.setTimeout(() => {
      const params = new URLSearchParams({ q, category: cat });
      api
        .get<SpecList>(`/api/specs?${params}`)
        .then((d) => {
          setData(d);
          setError("");
        })
        .catch((e) => setError((e as Error).message));
    }, q ? 220 : 0);
    return () => window.clearTimeout(t);
  }, [q, cat]);

  const animate = useMemo(() => !prefersReducedMotion(), []);
  const filtering = Boolean(q || cat);
  const visible = data ? (filtering || showAll ? data.items : data.items.filter((s) => s.hot)) : [];

  return (
    <div className="home">
      <PageTitle title="" />
      <section className="hero">
        <div className="hero-text">
          <h1>报名照片，<br />一次过审</h1>
          <p className="lede">
            按考试公告要求的像素、文件大小和底色生成照片。上传前免费预审，哪里不合格、怎么改，逐条告诉你。
          </p>
        </div>
        <div className="hero-drawing" aria-hidden="false">
          <SpecDrawing width={413} height={531} mm={[35, 45]} kbText="≤20KB" dpi={300} bg="#438EDB" bgLabel="蓝底" animate={animate} />
        </div>
      </section>

      <section className="finder" aria-label="查找考试规格">
        <label className="search">
          <span className="sr-only">搜索考试</span>
          <input
            type="search"
            value={q}
            onChange={(e) => setQ(e.target.value)}
            placeholder="搜考试，比如：江苏省考、考研确认、教资"
            enterKeyHint="search"
          />
        </label>
        <div className="chips" role="tablist" aria-label="分类">
          {["", ...(data?.categories ?? [])].map((c) => (
            <button key={c || "all"} role="tab" aria-selected={cat === c} className={`chip ${cat === c ? "chip-on" : ""}`} onClick={() => setCat(c)}>
              {c || "全部"}
            </button>
          ))}
        </div>
        {error && <p className="form-error">{error}</p>}
        {!data && !error && <div className="loading-row"><Spinner label="加载规格库…" /></div>}
        {data && (
          <div className="spec-list">
            {visible.map((s) => (
              <SpecRow key={s.key} spec={s} />
            ))}
            {!filtering && !showAll && data.items.length > visible.length && (
              <button className="spec-more" onClick={() => setShowAll(true)}>
                查看全部 {data.items.length} 种规格
              </button>
            )}
            {data.items.length === 0 && (
              <div className="empty">
                <p>没找到“{q}”。报名系统写了像素和 KB 要求的话，可以直接按要求生成。</p>
                <Link to="/custom" className="btn btn-ghost">按报名系统要求自定义</Link>
              </div>
            )}
          </div>
        )}
        <p className="spec-foot">
          共 {data?.total ?? "…"} 种规格。找不到你的考试？<Link to="/custom">按报名系统的要求自定义</Link>
        </p>
      </section>

      <section className="steps" aria-labelledby="steps-title">
        <h2 id="steps-title">三步拿到合规照片</h2>
        <ol>
          <li>
            <strong>选考试</strong>
            <span>规格卡写明尺寸、KB、底色，标出资料来源和是否已核实。</span>
          </li>
          <li>
            <strong>拍照或上传，免费预审</strong>
            <span>检测姿态、清晰度、光照、眉耳遮挡、反光等十余项，自动换底、裁剪、压到目标 KB。</span>
          </li>
          <li>
            <strong>¥0.99 下载</strong>
            <span>无水印照片 + 6 寸打印排版；同一张照片换任何规格都不再收费。</span>
          </li>
        </ol>
      </section>

      <section className="promises" aria-label="我们的承诺">
        <div>
          <h3>不美颜</h3>
          <p>大多数考试要求“不得美化修饰”。这里只换底、裁剪、压缩，五官和肤色保持原样。</p>
        </div>
        <div>
          <h3>规格有出处</h3>
          <p>每条规格附资料链接；没有对照官方公告核实过的，明确标注“参考规格”。</p>
        </div>
        <div>
          <h3>照片 24 小时删除</h3>
          <p>只在本站服务器处理，不调用第三方接口，不用于训练；可随时手动删除。</p>
        </div>
        <div>
          <h3>被驳回免费重做</h3>
          <p>付费照片被报名系统退回，7 天内可免费重新制作一次。</p>
        </div>
      </section>
    </div>
  );
}
