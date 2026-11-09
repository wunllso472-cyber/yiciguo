// 运营看板：漏斗和付费人数。令牌只存在本浏览器 sessionStorage。
import { useEffect, useState } from "react";
import { PageTitle } from "../components/ui";

interface Stats {
  funnel: { name: string; users: number }[];
  daily: Record<string, Record<string, number>>;
  paying_users_consumed: number;
  paying_users_purchased: number;
  users_total: number;
  unlock_types: Record<string, number>;
  top_specs: [string, number][];
  pending_consumes: number;
  feedback: { spec_id: string; content: string; url: string | null; created_at: string }[];
}

const NAMES: Record<string, string> = {
  visit: "访问", spec_view: "看规格", upload: "上传", ready: "预审完成", pay_click: "点支付",
  purchase_create: "创建购买", paid_detected: "确认到账", unlock: "解锁", download: "下载",
};

function readToken(): string {
  try {
    return sessionStorage.getItem("ycg_admin") ?? "";
  } catch {
    return "";
  }
}

export default function AdminPage() {
  const [token, setToken] = useState(readToken);
  const [stats, setStats] = useState<Stats | null>(null);
  const [error, setError] = useState("");

  useEffect(() => {
    if (!token) return;
    fetch("/api/admin/stats", { headers: { Authorization: `Bearer ${token}` } })
      .then(async (r) => {
        if (!r.ok) throw new Error((await r.json()).detail ?? "加载失败");
        return r.json();
      })
      .then((d) => {
        setStats(d);
        try {
          sessionStorage.setItem("ycg_admin", token);
        } catch {
          /* 忽略 */
        }
      })
      .catch((e) => setError((e as Error).message));
  }, [token]);

  if (!stats) {
    return (
      <div className="page">
        <PageTitle title="运营看板" />
        <h1>运营看板</h1>
        <form className="inline-form" onSubmit={(e) => { e.preventDefault(); setToken(new FormData(e.currentTarget).get("t") as string); }}>
          <input name="t" type="password" placeholder="管理员令牌" aria-label="管理员令牌" />
          <button className="btn btn-primary">进入</button>
        </form>
        {error && <p className="form-error">{error}</p>}
      </div>
    );
  }
  const max = Math.max(1, ...stats.funnel.map((f) => f.users));
  return (
    <div className="page admin">
      <PageTitle title="运营看板" />
      <h1>运营看板</h1>
      <section className="balance-row">
        <div><span className="num big">{stats.paying_users_consumed}</span><span>付费解锁用户</span></div>
        <div><span className="num big">{stats.paying_users_purchased}</span><span>确认购买用户</span></div>
        <div><span className="num big">{stats.users_total}</span><span>总用户</span></div>
        <div><span className="num big">{stats.pending_consumes}</span><span>待确认核销</span></div>
      </section>
      <h2>近 14 天漏斗（去重用户）</h2>
      <ul className="funnel">
        {stats.funnel.map((f) => (
          <li key={f.name}>
            <span>{NAMES[f.name] ?? f.name}</span>
            <span className="bar"><span style={{ width: `${(f.users / max) * 100}%` }} /></span>
            <span className="num">{f.users}</span>
          </li>
        ))}
      </ul>
      <h2>热门规格</h2>
      <ul className="plain">
        {stats.top_specs.map(([k, n]) => <li key={k}><span>{k}</span><span className="num">{n}</span></li>)}
      </ul>
      <h2>规格纠错</h2>
      <ul className="plain">
        {stats.feedback.map((f, i) => (
          <li key={i}><span>[{f.spec_id}] {f.content} {f.url && <a href={f.url} target="_blank" rel="noreferrer">链接</a>}</span><span className="fine">{f.created_at.slice(0, 16)}</span></li>
        ))}
        {stats.feedback.length === 0 && <li className="fine">暂无</li>}
      </ul>
    </div>
  );
}
