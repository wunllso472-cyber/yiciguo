import { useEffect, useRef, type ReactNode } from "react";
import { Link } from "react-router-dom";
import { STATUS_TEXT, type Spec, type Status } from "../api";

export function StatusMark({ status }: { status: Status }) {
  const sym = { pass: "✓", warn: "!", fail: "×", info: "i" }[status];
  const text = { pass: "通过", warn: "注意", fail: "不通过", info: "提示" }[status];
  return (
    <span className={`mark mark-${status}`} aria-label={text} title={text}>
      {sym}
    </span>
  );
}

export function SpecBadge({ spec }: { spec: Pick<Spec, "status"> }) {
  return <span className={`badge badge-${spec.status}`}>{STATUS_TEXT[spec.status]}</span>;
}

export function Sheet({ open, onClose, title, children, wide = false }: {
  open: boolean;
  onClose: () => void;
  title: string;
  children: ReactNode;
  wide?: boolean;
}) {
  const ref = useRef<HTMLDivElement>(null);
  useEffect(() => {
    if (!open) return;
    const prev = document.activeElement as HTMLElement | null;
    ref.current?.focus();
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && onClose();
    window.addEventListener("keydown", onKey);
    document.body.style.overflow = "hidden";
    return () => {
      window.removeEventListener("keydown", onKey);
      document.body.style.overflow = "";
      prev?.focus?.();
    };
  }, [open, onClose]);
  if (!open) return null;
  return (
    <div className="sheet-backdrop" onClick={onClose}>
      <div
        className={`sheet ${wide ? "sheet-wide" : ""}`}
        role="dialog"
        aria-modal="true"
        aria-label={title}
        tabIndex={-1}
        ref={ref}
        onClick={(e) => e.stopPropagation()}
      >
        <div className="sheet-head">
          <h2>{title}</h2>
          <button className="icon-btn" onClick={onClose} aria-label="关闭">×</button>
        </div>
        <div className="sheet-body">{children}</div>
      </div>
    </div>
  );
}

export function Spinner({ label }: { label?: string }) {
  return (
    <span className="spinner-wrap" role="status">
      <span className="spinner" aria-hidden="true" />
      {label && <span>{label}</span>}
    </span>
  );
}

export function SpecRow({ spec }: { spec: Spec }) {
  return (
    <Link to={`/spec/${encodeURIComponent(spec.key)}`} className="spec-row">
      <span className="spec-row-main">
        <span className="spec-row-name">{spec.name}</span>
        <span className="spec-row-meta">
          <span className="num">{spec.size_mode === "min" ? `≥${spec.min_width}×${spec.min_height}` : `${spec.width}×${spec.height}`}</span>
          <span>{spec.kb_text === "不限" ? "KB 不限" : spec.kb_text}</span>
          <span>{spec.bg_names.join("/")}</span>
        </span>
      </span>
      <span className="spec-row-side">
        <SpecBadge spec={spec} />
      </span>
    </Link>
  );
}

export function PageTitle({ title }: { title: string }) {
  useEffect(() => {
    document.title = title ? `${title} - 一次过` : "一次过 · 报名照片过审助手";
  }, [title]);
  return null;
}
