// 支付流程：选档位 → 获取购买入口 → 手机跳转支付宝 / 电脑扫码 / 微信内引导 → 服务端确认到账 → 自动解锁。
// 前端从不自行判定“支付成功”，一律以服务端查询结果为准。
import QRCode from "qrcode";
import { useCallback, useEffect, useRef, useState } from "react";
import { api, track, type Offers, type Option, type Purchase, type PurchaseCheck } from "../api";
import { payEntry } from "../env";
import { useApp } from "../state";
import { Sheet, Spinner } from "./ui";

type Step = "choose" | "creating" | "qr" | "redirected" | "wechat" | "confirming" | "paid" | "timeout" | "expired" | "error";

interface Props {
  open: boolean;
  onClose: () => void;
  offers: Offers | null;
  photoId?: string;
  onPaid: (res: PurchaseCheck) => void;
}

const POLL_MS = 2500;
const POLL_MAX_MS = 5 * 60 * 1000;

function optionText(o: Option): string {
  if (o.quota) return `${o.quota} 次`;
  if (o.period === "MONTH") return "备考季月卡（一个月）";
  return o.name;
}

export default function PaySheet({ open, onClose, offers, photoId, onPaid }: Props) {
  const { toast } = useApp();
  const countOpts = offers?.count?.purchasable ? offers.count.options : [];
  const monthlyOpts = offers?.monthly?.purchasable ? offers.monthly.options : [];
  const [choice, setChoice] = useState<{ product: "count" | "monthly"; sku: string } | null>(null);
  const [step, setStep] = useState<Step>("choose");
  const [purchase, setPurchase] = useState<Purchase | null>(null);
  const [qr, setQr] = useState("");
  const [error, setError] = useState("");
  const [noApp, setNoApp] = useState(false);
  const startedAt = useRef(0);

  useEffect(() => {
    if (open) {
      setStep("choose");
      setPurchase(null);
      setQr("");
      setNoApp(false);
      if (!choice && countOpts[0]) setChoice({ product: "count", sku: countOpts[0].sku_id });
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open]);

  const check = useCallback(
    async (manual = false) => {
      if (!purchase) return;
      try {
        const res = await api.get<PurchaseCheck>(`/api/pay/purchase/${purchase.out_request_no}`);
        if (res.pay.state === "paid") {
          if (!photoId || res.unlock?.state === "unlocked" || res.photo?.unlocked) {
            setStep("paid");
            onPaid(res);
          } else if (res.unlock?.state === "confirming") {
            setStep("confirming");
          } else {
            setStep("paid");
            onPaid(res);
          }
          return;
        }
        if (res.purchase.expired) {
          setStep("expired");
          return;
        }
        if (manual) toast("还没查到付款。若已付款，通常几秒内到账，请稍后再点刷新；不会重复扣款");
      } catch (e) {
        if (manual) toast((e as Error).message);
      }
    },
    [purchase, photoId, onPaid, toast],
  );

  // 轮询：页面可见时每 2.5 秒查一次；从支付宝切回来立即查
  useEffect(() => {
    if (!purchase || !["qr", "redirected", "wechat", "confirming"].includes(step)) return;
    const timer = window.setInterval(() => {
      if (Date.now() - startedAt.current > POLL_MAX_MS) {
        setStep("timeout");
        return;
      }
      if (document.visibilityState === "visible") void check();
    }, POLL_MS);
    const onVisible = () => document.visibilityState === "visible" && void check();
    document.addEventListener("visibilitychange", onVisible);
    return () => {
      window.clearInterval(timer);
      document.removeEventListener("visibilitychange", onVisible);
    };
  }, [purchase, step, check]);

  const showQr = async (p: Purchase, target: Step) => {
    const text = p.qr_code || p.purchase_url || "";
    setQr(await QRCode.toDataURL(text, { margin: 1, width: 240, errorCorrectionLevel: "M" }));
    setStep(target);
    track("pay_qr_shown");
  };

  const start = async () => {
    if (!choice) return;
    setStep("creating");
    setError("");
    track("pay_click", { product: choice.product, sku: choice.sku });
    try {
      const p = await api.post<Purchase>("/api/pay/purchase", {
        product: choice.product,
        sku_id: choice.sku,
        photo_id: photoId ?? null,
      });
      setPurchase(p);
      startedAt.current = Date.now();
      const entry = payEntry();
      if (entry === "wechat") {
        await showQr(p, "wechat");
      } else if (entry === "redirect" && p.purchase_url) {
        setStep("redirected");
        window.location.href = p.purchase_url; // 不拼接、不解析，直接使用接口返回的入口
        window.setTimeout(() => document.visibilityState === "visible" && setNoApp(true), 2500);
      } else {
        await showQr(p, "qr");
      }
    } catch (e) {
      setError((e as Error).message);
      setStep("error");
    }
  };

  const price = (() => {
    const pool = choice?.product === "monthly" ? monthlyOpts : countOpts;
    return pool.find((o) => o.sku_id === choice?.sku)?.price;
  })();

  return (
    <Sheet open={open} onClose={onClose} title={step === "paid" ? "支付完成" : "解锁无水印照片"}>
      {step === "choose" || step === "creating" || step === "error" ? (
        <div className="pay">
          {countOpts.length === 0 && monthlyOpts.length === 0 ? (
            <p className="empty">支付暂时不可用，请稍后再试。</p>
          ) : (
            <>
              <div className="options" role="radiogroup" aria-label="选择次数">
                {countOpts.map((o, i) => (
                  <label key={o.sku_id} className={`option ${choice?.sku === o.sku_id ? "option-on" : ""}`}>
                    <input
                      type="radio"
                      name="sku"
                      checked={choice?.sku === o.sku_id}
                      onChange={() => setChoice({ product: "count", sku: o.sku_id })}
                    />
                    <span className="option-name">{optionText(o)}</span>
                    <span className="option-desc">{i === 0 ? "解锁这张照片的全部规格" : `每次解锁一张照片，可留着以后用`}</span>
                    <span className="option-price num">¥{o.price}</span>
                  </label>
                ))}
                {monthlyOpts.map((o) => (
                  <label key={o.sku_id} className={`option ${choice?.sku === o.sku_id ? "option-on" : ""}`}>
                    <input
                      type="radio"
                      name="sku"
                      checked={choice?.sku === o.sku_id}
                      onChange={() => setChoice({ product: "monthly", sku: o.sku_id })}
                    />
                    <span className="option-name">{optionText(o)}</span>
                    <span className="option-desc">一个月内不限次导出，不自动续费</span>
                    <span className="option-price num">¥{o.price}</span>
                  </label>
                ))}
              </div>
              {step === "error" && <p className="form-error">{error}</p>}
              <button className="btn btn-primary btn-block" onClick={start} disabled={step === "creating" || !choice}>
                {step === "creating" ? <Spinner label="正在打开支付…" /> : `用支付宝支付 ¥${price ?? ""}`}
              </button>
              <p className="fine">
                付款后自动解锁，交付与付款都以服务器确认为准。被驳回可免费重做 1 次；遇到问题请在“常见问题”里联系我们处理。
              </p>
            </>
          )}
        </div>
      ) : null}

      {(step === "qr" || step === "wechat") && (
        <div className="pay pay-qr">
          {step === "wechat" && (
            <div className="notice">
              微信里不能直接打开支付宝。点右上角“···”选择<strong>在浏览器打开</strong>后再支付；或者截图下面的二维码，用支付宝“扫一扫”识别。
            </div>
          )}
          {qr && <img src={qr} alt="支付宝付款二维码" className="qr" width={240} height={240} />}
          <p className="qr-caption">打开支付宝，扫一扫付款</p>
          {purchase?.expire_time && <p className="fine center">二维码 {purchase.expire_time} 前有效</p>}
          {purchase?.purchase_url?.startsWith("http") && (
            <p className="fine center">
              <a href={purchase.purchase_url} target="_blank" rel="noreferrer">在新窗口打开收银台</a>
            </p>
          )}
          <button className="btn btn-ghost btn-block" onClick={() => void check(true)}>我已支付，刷新结果</button>
        </div>
      )}

      {step === "redirected" && (
        <div className="pay">
          <div className="waiting">
            <Spinner />
            <div>
              <strong>正在等待支付宝付款结果</strong>
              <p className="fine">付完款回到这里会自动刷新。</p>
            </div>
          </div>
          {noApp && <p className="notice">没有自动打开支付宝？可以改用二维码付款。</p>}
          <div className="btn-stack">
            <button className="btn btn-primary btn-block" onClick={() => void check(true)}>我已支付，刷新结果</button>
            <button className="btn btn-ghost btn-block" onClick={() => purchase?.purchase_url && (window.location.href = purchase.purchase_url)}>
              重新打开支付宝
            </button>
            <button className="btn btn-text" onClick={() => purchase && void showQr(purchase, "qr")}>改用二维码</button>
          </div>
        </div>
      )}

      {step === "confirming" && (
        <div className="pay">
          <div className="waiting">
            <Spinner />
            <div>
              <strong>已收到付款，正在确认扣次</strong>
              <p className="fine">一般几秒内完成，不会重复扣次数。</p>
            </div>
          </div>
        </div>
      )}

      {step === "paid" && (
        <div className="pay center">
          <p className="paid-mark" aria-hidden="true">✓</p>
          <p><strong>付款成功，照片已解锁</strong></p>
          <button className="btn btn-primary btn-block" onClick={onClose}>去下载</button>
        </div>
      )}

      {(step === "timeout" || step === "expired") && (
        <div className="pay">
          <p className="notice">
            {step === "expired"
              ? "这个支付入口已过期（30 分钟有效）。如果你已经付款，点“刷新结果”；没有付款可以重新发起。"
              : "暂时没查到付款结果。如果已经付款，通常很快到账，请点“刷新结果”；没有付款可以重新发起。不会重复扣款。"}
          </p>
          <div className="btn-stack">
            <button className="btn btn-primary btn-block" onClick={() => void check(true)}>刷新结果</button>
            <button className="btn btn-ghost btn-block" onClick={() => setStep("choose")}>重新发起支付</button>
          </div>
        </div>
      )}
    </Sheet>
  );
}
