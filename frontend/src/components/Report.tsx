import type { Report as ReportT, ValidationItem } from "../api";
import { StatusMark } from "./ui";

const STAMP = { pass: "预审通过", warn: "基本可用", fail: "建议重拍" };

export function ReportPanel({ report }: { report: ReportT }) {
  const ordered = [...report.items].sort((a, b) => rank(a.status) - rank(b.status));
  return (
    <section className="panel report" aria-labelledby="report-title">
      <div className="report-head">
        <div>
          <h3 id="report-title">AI 预审报告</h3>
          <p className="report-summary">{report.summary}</p>
        </div>
        <span className={`stamp stamp-${report.overall}`}>{STAMP[report.overall]}</span>
      </div>
      <ul className="checklist">
        {ordered.map((item) => (
          <li key={item.id} className={`check-item check-${item.status}`}>
            <StatusMark status={item.status} />
            <div className="check-body">
              <div className="check-line">
                <span className="check-label">{item.label}</span>
                <span className="check-value">{item.value}</span>
              </div>
              {item.tip && item.status !== "pass" && <p className="check-tip">{item.tip}</p>}
            </div>
          </li>
        ))}
      </ul>
      <p className="fine">预审基于本地算法，仅供参考，最终以报名系统审核为准。</p>
    </section>
  );
}

export function ValidationPanel({ items }: { items: ValidationItem[] }) {
  return (
    <section className="panel" aria-labelledby="val-title">
      <h3 id="val-title">成品文件实测</h3>
      <p className="fine">对生成的 JPG 文件逐项复核，和报名系统检查的是同样的东西。</p>
      <ul className="checklist checklist-tight">
        {items.map((v) => (
          <li key={v.id} className={`check-item check-${v.status}`}>
            <StatusMark status={v.status} />
            <div className="check-body">
              <div className="check-line">
                <span className="check-label">{v.label}</span>
                <span className="check-value">{v.detail}</span>
              </div>
            </div>
          </li>
        ))}
      </ul>
    </section>
  );
}

function rank(s: string) {
  return { fail: 0, warn: 1, info: 2, pass: 3 }[s as "fail"] ?? 4;
}
