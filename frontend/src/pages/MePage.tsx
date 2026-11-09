import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { api, type Balance, type Me } from "../api";
import { PageTitle, Spinner } from "../components/ui";
import { useApp } from "../state";

interface Item {
  id: string;
  status: string;
  unlocked: boolean;
  unlock_type: string | null;
  spec: { key: string; short: string; name: string };
  bg_name: string;
  created_at: string;
  expires_at: string;
  thumb_url?: string;
}

const STATUS: Record<string, string> = {
  queued: "处理中",
  processing: "处理中",
  ready: "待解锁",
  rejected: "需要重拍",
  failed: "处理失败",
};

export default function MePage() {
  const { me, setMe, toast } = useApp();
  const [items, setItems] = useState<Item[] | null>(null);
  const [balance, setBalance] = useState<Balance | null>(null);
  const [code, setCode] = useState("");

  const load = () => {
    void api.get<{ items: Item[] }>("/api/photos").then((d) => setItems(d.items)).catch(() => setItems([]));
    void api.get<Balance>("/api/pay/balance").then(setBalance).catch(() => undefined);
  };
  useEffect(() => {
    load();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [me?.id]);

  const restore = async () => {
    try {
      const m = await api.post<Me>("/api/me/restore", { code });
      setMe(m);
      setCode("");
      toast("已找回");
    } catch (e) {
      toast((e as Error).message);
    }
  };

  const copy = async () => {
    try {
      await navigator.clipboard.writeText(me?.pickup_code ?? "");
      toast("取件码已复制");
    } catch {
      toast(`取件码：${me?.pickup_code}`);
    }
  };

  return (
    <div className="page me-page">
      <PageTitle title="我的照片" />
      <h1>我的照片</h1>

      <section className="panel pickup">
        <div>
          <p className="fine">取件码（换手机、换浏览器时用它找回照片和次数）</p>
          <p className="code num">{me?.pickup_code ?? "········"}</p>
        </div>
        <button className="btn btn-ghost" onClick={copy}>复制</button>
      </section>

      <section className="balance-row">
        <div><span className="num big">{balance?.remaining ?? "–"}</span><span>剩余次数</span></div>
        <div><span className="num big">{balance?.free_credits ?? me?.free_credits ?? 0}</span><span>免费次数</span></div>
        {balance?.monthly?.decision === "ALLOW" && (
          <div><span className="big">月卡</span><span>有效至 {balance.monthly.valid_until?.slice(0, 10)}</span></div>
        )}
      </section>

      <section>
        <h2>最近 {me?.ttl_hours ?? 24} 小时</h2>
        {items === null ? (
          <div className="loading-row"><Spinner /></div>
        ) : items.length === 0 ? (
          <div className="empty">
            <p>还没有照片。照片超过 {me?.ttl_hours ?? 24} 小时会自动删除。</p>
            <Link to="/" className="btn btn-primary">开始制作</Link>
          </div>
        ) : (
          <ul className="photo-list">
            {items.map((p) => (
              <li key={p.id}>
                <Link to={`/photo/${p.id}`} className="photo-item">
                  {p.thumb_url ? <img src={p.thumb_url} alt="" loading="lazy" /> : <span className="thumb-empty" />}
                  <span className="photo-item-main">
                    <strong>{p.spec.short}</strong>
                    <span className="fine">{p.bg_name}底　{new Date(p.created_at).toLocaleString("zh-CN", { month: "numeric", day: "numeric", hour: "2-digit", minute: "2-digit" })}</span>
                  </span>
                  <span className={`pill ${p.unlocked ? "pill-ok" : ""}`}>{p.unlocked ? "已解锁" : STATUS[p.status] ?? p.status}</span>
                </Link>
              </li>
            ))}
          </ul>
        )}
      </section>

      <section className="panel">
        <h3>在这台设备上找回</h3>
        <p className="fine">输入在其他设备上看到的 8 位取件码。</p>
        <div className="inline-form">
          <input value={code} onChange={(e) => setCode(e.target.value.toUpperCase())} maxLength={12} placeholder="例如 7KQ2M9XA"
            aria-label="取件码" autoCapitalize="characters" />
          <button className="btn btn-primary" disabled={code.replace(/\W/g, "").length !== 8} onClick={restore}>找回</button>
        </div>
      </section>
    </div>
  );
}
