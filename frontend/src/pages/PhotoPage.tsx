import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import {
  api,
  ApiError,
  bgHex,
  track,
  type Balance,
  type Offers,
  type PhotoView,
  type PurchaseCheck,
  type SpecList,
  type UnlockResult,
} from "../api";
import PaySheet from "../components/PaySheet";
import { ReportPanel, ValidationPanel } from "../components/Report";
import SpecDrawing from "../components/SpecDrawing";
import { PageTitle, Spinner } from "../components/ui";
import { isAlipay, isWeChat } from "../env";
import { useApp } from "../state";

const STAGES = ["loading", "detect", "matting", "render"];
const STAGE_TEXT: Record<string, string> = {
  loading: "读取照片",
  detect: "检测人脸与姿态",
  matting: "AI 抠图",
  render: "按规格生成并校验",
};

export default function PhotoPage() {
  const { id = "" } = useParams();
  const nav = useNavigate();
  const { me, toast, refresh } = useApp();
  const [photo, setPhoto] = useState<PhotoView | null>(null);
  const [error, setError] = useState<{ status: number; message: string } | null>(null);
  const [specs, setSpecs] = useState<SpecList | null>(null);
  const [offers, setOffers] = useState<Offers | null>(null);
  const [balance, setBalance] = useState<Balance | null>(null);
  const [payOpen, setPayOpen] = useState(false);
  const [busy, setBusy] = useState<"" | "select" | "unlock" | "confirm">("");
  const [forceUnlock, setForceUnlock] = useState(false);
  const pollRef = useRef<number>();

  const load = useCallback(async () => {
    try {
      const p = await api.get<PhotoView>(`/api/photos/${id}`);
      setPhoto(p);
      return p;
    } catch (e) {
      const err = e as ApiError;
      setError({ status: err.status, message: err.message });
      return null;
    }
  }, [id]);

  // 处理中：轮询进度
  useEffect(() => {
    let alive = true;
    const tick = async () => {
      const p = await load();
      if (alive && p && (p.status === "queued" || p.status === "processing")) {
        pollRef.current = window.setTimeout(tick, 700);
      }
    };
    void tick();
    return () => {
      alive = false;
      window.clearTimeout(pollRef.current);
    };
  }, [load]);

  const ready = photo?.status === "ready";
  useEffect(() => {
    if (!ready) return;
    if (!specs) void api.get<SpecList>("/api/specs").then(setSpecs).catch(() => undefined);
    if (!photo?.unlocked) {
      if (!offers) void api.get<Offers>("/api/pay/offers").then(setOffers).catch(() => undefined);
      void api.get<Balance>("/api/pay/balance").then(setBalance).catch(() => undefined);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [ready, photo?.unlocked]);

  const select = async (specKey: string, bg?: string) => {
    if (!photo) return;
    if (specKey === "__custom") {
      nav(`/custom?photo=${photo.id}`);
      return;
    }
    setBusy("select");
    try {
      setPhoto(await api.post<PhotoView>(`/api/photos/${photo.id}/select`, { spec_key: specKey, bg: bg ?? photo.bg }));
    } catch (e) {
      toast((e as Error).message);
    } finally {
      setBusy("");
    }
  };

  const waitConfirm = async () => {
    setBusy("confirm");
    for (let i = 0; i < 30; i++) {
      await new Promise((r) => setTimeout(r, 2000));
      const res = await api.post<{ result: UnlockResult; photo: PhotoView }>(`/api/photos/${id}/unlock`, {}).catch(() => null);
      if (res?.photo.unlocked) {
        setPhoto(res.photo);
        setBusy("");
        toast("已解锁，可以下载了");
        return;
      }
    }
    setBusy("");
    toast("扣次结果还在确认中，请稍后刷新页面，不会重复扣次");
  };

  const unlock = async (method: "auto" | "free" = "auto") => {
    if (!photo) return;
    setBusy("unlock");
    try {
      const res = await api.post<{ result: UnlockResult; photo: PhotoView; offers?: Offers }>(`/api/photos/${photo.id}/unlock`, { method });
      setPhoto(res.photo);
      if (res.result.state === "unlocked") {
        toast("已解锁，可以下载了");
        void refresh();
      } else if (res.result.state === "need_purchase") {
        if (res.offers) setOffers(res.offers);
        setPayOpen(true);
      } else if (res.result.state === "confirming") {
        setBusy("");
        await waitConfirm();
        return;
      } else {
        toast(res.result.message ?? "解锁失败，请稍后重试");
      }
    } catch (e) {
      toast((e as Error).message);
    } finally {
      setBusy((b) => (b === "unlock" ? "" : b));
    }
  };

  const onPaid = (res: PurchaseCheck) => {
    if (res.photo) setPhoto(res.photo);
    else void load();
    void refresh();
  };

  const remove = async () => {
    if (!photo || !window.confirm("确定立即删除这张照片和所有生成的文件吗？删除后无法恢复。")) return;
    try {
      await api.del(`/api/photos/${photo.id}`);
      toast("已删除");
      nav("/me");
    } catch (e) {
      toast((e as Error).message);
    }
  };

  const grouped = useMemo(() => {
    const map = new Map<string, { key: string; short: string }[]>();
    specs?.items.forEach((s) => {
      if (!map.has(s.category)) map.set(s.category, []);
      map.get(s.category)!.push({ key: s.key, short: s.short });
    });
    return map;
  }, [specs]);

  if (error) {
    return (
      <div className="page">
        <PageTitle title="照片" />
        <div className="empty">
          <p>{error.status === 410 ? "这张照片已过期或已删除。为了保护隐私，照片最多保留 24 小时。" : error.message}</p>
          <Link className="btn btn-primary" to="/">重新制作</Link>
        </div>
      </div>
    );
  }
  if (!photo) return <div className="page loading-row"><Spinner label="加载中…" /></div>;

  if (photo.status === "queued" || photo.status === "processing") {
    const current = STAGES.indexOf(photo.stage);
    return (
      <div className="page processing">
        <PageTitle title="处理中" />
        <h1>正在处理你的照片</h1>
        <p className="lede">通常 3–5 秒。全程在本站服务器完成。</p>
        <ol className="stages">
          {STAGES.map((s, i) => (
            <li key={s} className={i < current ? "stage-done" : i === current ? "stage-now" : ""}>
              <span className="stage-dot" aria-hidden="true">{i < current ? "✓" : ""}</span>
              {STAGE_TEXT[s]}
              {i === current && <Spinner />}
            </li>
          ))}
        </ol>
      </div>
    );
  }

  if (photo.status !== "ready") {
    return (
      <div className="page">
        <PageTitle title="需要重拍" />
        <h1>这张照片没法用</h1>
        {photo.report ? <ReportPanel report={photo.report} /> : <p className="notice">{photo.error ?? "处理失败"}</p>}
        <Link className="btn btn-primary btn-block" to={`/spec/${encodeURIComponent(photo.spec.key)}${photo.redo_of ? `?redo=${photo.redo_of}` : ""}`}>
          换一张照片
        </Link>
      </div>
    );
  }

  const failValidation = photo.validation?.some((v) => v.status === "fail");
  const reportFail = photo.report?.overall === "fail";
  const price = offers?.count?.options[0]?.price;
  const expires = new Date(photo.expires_at);
  const inWebview = isWeChat || isAlipay;

  return (
    <div className="page photo-page">
      <PageTitle title={photo.spec.short} />
      <div className="photo-grid">
        <div className="photo-left">
          <p className="crumb"><Link to={`/spec/${encodeURIComponent(photo.spec.key)}`}>{photo.spec.name}</Link></p>
          <div className={`photo-figure ${busy === "select" ? "is-busy" : ""}`}>
            <SpecDrawing
              width={photo.output?.width ?? photo.spec.width}
              height={photo.output?.height ?? photo.spec.height}
              mm={photo.spec.mm}
              kbText={`${photo.output?.kb ?? "?"}KB`}
              dpi={photo.spec.dpi}
              bg={bgHex(photo.bg)}
              bgLabel={`${photo.bg_name}底`}
              image={photo.unlocked && photo.downloads ? photo.downloads.photo : photo.preview_url}
              headRatio={photo.output?.head_ratio}
              topMargin={photo.output?.top_margin}
              frameHeight={260}
            />
            {!photo.unlocked && <p className="fine center">预览带水印，解锁后下载无水印原图</p>}
          </div>

          <div className="controls">
            {photo.backgrounds.length > 1 && (
              <div className="bg-pick" role="radiogroup" aria-label="底色">
                {photo.backgrounds.map((b) => (
                  <button key={b.key} role="radio" aria-checked={photo.bg === b.key} disabled={busy === "select"}
                    className={`swatch ${photo.bg === b.key ? "swatch-on" : ""}`} onClick={() => void select(photo.spec.key, b.key)}>
                    <span className="swatch-color" style={{ background: bgHex(b.key) }} />
                    {b.name}
                  </button>
                ))}
              </div>
            )}
            <label className="select-row">
              <span>换规格</span>
              <select value={photo.spec.key} onChange={(e) => void select(e.target.value)} disabled={busy === "select"}>
                {photo.spec.custom && <option value={photo.spec.key}>{photo.spec.short}</option>}
                {[...grouped.entries()].map(([cat, list]) => (
                  <optgroup key={cat} label={cat}>
                    {list.map((s) => <option key={s.key} value={s.key}>{s.short}</option>)}
                  </optgroup>
                ))}
                <option value="__custom">自定义规格…</option>
              </select>
            </label>
          </div>
        </div>

        <div className="photo-right">
          {photo.unlocked && photo.downloads ? (
            <section className="panel deliver" aria-labelledby="dl-title">
              <h2 id="dl-title">照片已解锁</h2>
              <p className="file-meta num">
                {photo.output?.width}×{photo.output?.height} px　{photo.output?.kb}KB　JPG　{photo.spec.dpi} dpi
              </p>
              <div className="btn-stack">
                <a className="btn btn-primary btn-block" href={`${photo.downloads.photo}&dl=1`} download={photo.downloads.filename}
                  onClick={() => track("download_click", { spec: photo.spec.key })}>下载照片</a>
                <a className="btn btn-ghost btn-block" href={`${photo.downloads.layout}&dl=1`}
                  onClick={() => track("layout_click", { spec: photo.spec.key })}>下载 6 寸打印排版</a>
                <a className="btn btn-text" href={photo.downloads.photo} target="_blank" rel="noreferrer">查看原图</a>
              </div>
              {inWebview && <p className="notice">在微信或支付宝里下载不了的话，点“查看原图”，再长按图片保存。</p>}
              <p className="fine">在照片下方换规格或底色，可以继续下载，不再收费。文件名里写明了像素和大小，方便上传时核对。</p>
              {photo.spec.has_official_tool && (
                <div className="callout">
                  <h3>还差一步：用官方工具处理</h3>
                  <p>这场考试要求照片先经过报名系统提供的“照片处理工具”处理再上传。用刚下载的照片作为源照片即可。</p>
                </div>
              )}
              <div className="after">
                {photo.can_redo && (
                  <Link className="after-link" to={`/spec/${encodeURIComponent(photo.spec.key)}?redo=${photo.id}`}
                    onClick={() => track("redo_click")}>
                    被报名系统退回了？免费重做一次
                  </Link>
                )}
                {me && (
                  <button className="after-link" onClick={() => void share(me.invite_code, toast)}>
                    分享给研友：对方用你的链接做完第一张照片，你们各得 1 次免费导出
                  </button>
                )}
                {me?.showcase_url && (
                  <a className="after-link" href={me.showcase_url} target="_blank" rel="noreferrer" onClick={() => track("showcase_click")}>
                    觉得有用？去 AI付 官网给我们点个赞
                  </a>
                )}
              </div>
            </section>
          ) : (
            <section className="panel unlock" aria-labelledby="unlock-title">
              <h2 id="unlock-title">下载无水印照片</h2>
              <ul className="includes">
                <li>这张照片的全部规格、全部底色都能下载</li>
                <li>附 6 寸相纸打印排版</li>
                <li>被报名系统退回，{me?.redo_days ?? 7} 天内免费重做 1 次</li>
              </ul>
              {failValidation ? (
                <p className="notice">成品没有通过规格校验（见下方），这次不能解锁，也不会扣费。请换一张照片或调整规格。</p>
              ) : reportFail && !forceUnlock ? (
                <div className="notice">
                  预审有不通过的项目，被退回的可能性较大，建议按提示重拍后再下载。
                  <div className="btn-pair">
                    <Link className="btn btn-primary" to={`/spec/${encodeURIComponent(photo.spec.key)}`}>重新拍</Link>
                    <button className="btn btn-ghost" onClick={() => setForceUnlock(true)}>我了解，继续</button>
                  </div>
                </div>
              ) : (
                <div className="btn-stack">
                  {balance?.remaining != null && balance.remaining > 0 ? (
                    <button className="btn btn-primary btn-block" disabled={!!busy} onClick={() => void unlock("auto")}>
                      {busy ? <Spinner label="处理中…" /> : `用 1 次额度解锁（剩 ${balance.remaining} 次）`}
                    </button>
                  ) : (
                    <button className="btn btn-primary btn-block btn-price" disabled={!!busy || !me?.pay_enabled} onClick={() => void unlock("auto")}>
                      {busy ? <Spinner label={busy === "confirm" ? "正在确认…" : "处理中…"} /> : (
                        <>
                          <span>解锁下载</span>
                          {price && <span className="num price">¥{price}</span>}
                        </>
                      )}
                    </button>
                  )}
                  {(photo.free_credits ?? 0) > 0 && (
                    <button className="btn btn-ghost btn-block" disabled={!!busy} onClick={() => void unlock("free")}>
                      用免费次数解锁（剩 {photo.free_credits} 次）
                    </button>
                  )}
                  {!me?.pay_enabled && <p className="fine">支付暂未开通。</p>}
                  {me?.pay_mode === "mock" && <p className="fine">当前为本地模拟支付，不会真实扣款。</p>}
                </div>
              )}
            </section>
          )}

          {photo.report && <ReportPanel report={photo.report} />}
          {photo.validation && <ValidationPanel items={photo.validation} />}

          <p className="fine expiry">
            照片将在 {expires.toLocaleString("zh-CN", { month: "numeric", day: "numeric", hour: "2-digit", minute: "2-digit" })} 自动删除。
            <button className="btn-text danger" onClick={remove}>立即删除</button>
          </p>
        </div>
      </div>

      <PaySheet open={payOpen} onClose={() => setPayOpen(false)} offers={offers} photoId={photo.id} onPaid={onPaid} />
    </div>
  );
}

async function share(code: string, toast: (t: string) => void) {
  track("share_click");
  const url = `${window.location.origin}/?inv=${code}`;
  const text = `报名照片在这里做，先免费预审再下载：${url}`;
  try {
    if (navigator.share) {
      await navigator.share({ title: "一次过 · 报名照片", text, url });
      return;
    }
    await navigator.clipboard.writeText(text);
    toast("链接已复制，发给研友吧");
  } catch {
    window.prompt("复制下面的链接发给研友：", url);
  }
}
