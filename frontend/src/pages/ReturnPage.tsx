// 支付宝托管购买页返回的页面。可能在支付宝 App 里打开（没有原浏览器的登录状态），凭签名链接查询结果。
import { useEffect, useState } from "react";
import { Link, useParams, useSearchParams } from "react-router-dom";
import { api, track, type PurchaseCheck } from "../api";
import { PageTitle, Spinner } from "../components/ui";
import { isAlipay, isWeChat } from "../env";
import { useApp } from "../state";

export default function ReturnPage() {
  const { req = "" } = useParams();
  const [search] = useSearchParams();
  const token = search.get("t") ?? "";
  const { refresh } = useApp();
  const [data, setData] = useState<PurchaseCheck | null>(null);
  const [error, setError] = useState("");
  const [tries, setTries] = useState(0);

  useEffect(() => {
    track("pay_return_view");
  }, []);

  useEffect(() => {
    let alive = true;
    const run = async () => {
      try {
        const res = await api.get<PurchaseCheck>(`/api/pay/return/${req}?t=${encodeURIComponent(token)}`);
        if (!alive) return;
        setData(res);
        void refresh();
        const settled = res.pay.state === "paid" && (!res.purchase.photo_id || res.photo?.unlocked);
        if (!settled && tries < 8) window.setTimeout(() => alive && setTries((t) => t + 1), 2000);
      } catch (e) {
        if (alive) setError((e as Error).message);
      }
    };
    void run();
    return () => {
      alive = false;
    };
  }, [req, token, tries, refresh]);

  if (error) {
    return (
      <div className="page">
        <PageTitle title="支付结果" />
        <p className="form-error">{error}</p>
        <Link to="/me" className="btn btn-ghost">去“我的照片”查看</Link>
      </div>
    );
  }
  if (!data) return <div className="page loading-row"><Spinner label="正在确认付款结果…" /></div>;

  const paid = data.pay.state === "paid";
  const photo = data.photo;
  return (
    <div className="page return-page">
      <PageTitle title="支付结果" />
      {paid ? (
        <>
          <p className="paid-mark" aria-hidden="true">✓</p>
          <h1>付款成功</h1>
          {photo?.unlocked && photo.downloads ? (
            <>
              <p className="lede">照片已解锁。</p>
              <img src={photo.downloads.photo} alt="已解锁的报名照" className="return-photo" />
              <div className="btn-stack">
                <a className="btn btn-primary btn-block" href={`${photo.downloads.photo}&dl=1`} download={photo.downloads.filename}>下载照片</a>
                <Link className="btn btn-ghost btn-block" to={`/photo/${photo.id}`}>查看其他规格和打印排版</Link>
              </div>
              {(isWeChat || isAlipay) && <p className="notice">如果下载没反应，长按上面的图片保存到相册。</p>}
            </>
          ) : data.unlock?.state === "confirming" || (data.purchase.photo_id && !photo?.unlocked) ? (
            <div className="waiting"><Spinner /><span>正在确认扣次，请稍候…</span></div>
          ) : (
            <>
              <p className="lede">次数已到账{data.pay.remaining != null ? `，当前剩余 ${data.pay.remaining} 次` : ""}。</p>
              <Link className="btn btn-primary btn-block" to="/me">去“我的照片”</Link>
            </>
          )}
        </>
      ) : (
        <>
          <h1>还没查到付款</h1>
          <p className="lede">如果你已经付款，通常几秒内到账，页面会自动刷新；没有付款可以回到原页面重新发起。不会重复扣款。</p>
          {tries >= 8 && (
            <button className="btn btn-primary btn-block" onClick={() => setTries(0)}>刷新结果</button>
          )}
          {data.purchase.photo_id && (
            <Link className="btn btn-ghost btn-block" to={`/photo/${data.purchase.photo_id}`}>回到照片</Link>
          )}
        </>
      )}
      {data.pickup_code && (
        <p className="fine center">
          换设备或回到原来的浏览器，在“我的照片”输入取件码 <strong className="num code">{data.pickup_code}</strong> 即可找回。
        </p>
      )}
    </div>
  );
}
