// 后端接口与类型。所有请求同源，靠 HttpOnly Cookie 识别匿名用户。

export class ApiError extends Error {
  status: number;
  constructor(status: number, message: string) {
    super(message);
    this.status = status;
  }
}

async function request<T>(method: string, url: string, body?: unknown, form?: FormData): Promise<T> {
  let res: Response;
  try {
    res = await fetch(url, {
      method,
      credentials: "same-origin",
      headers: body !== undefined ? { "Content-Type": "application/json" } : undefined,
      body: form ?? (body !== undefined ? JSON.stringify(body) : undefined),
    });
  } catch {
    throw new ApiError(0, "网络连接失败，请检查网络后重试");
  }
  const text = await res.text();
  let data: any = null;
  try {
    data = text ? JSON.parse(text) : null;
  } catch {
    data = null;
  }
  if (!res.ok) {
    const detail = data && typeof data.detail === "string" ? data.detail : `请求失败（${res.status}）`;
    throw new ApiError(res.status, detail);
  }
  return data as T;
}

export const api = {
  get: <T>(url: string) => request<T>("GET", url),
  post: <T>(url: string, body: unknown = {}) => request<T>("POST", url, body),
  del: <T>(url: string) => request<T>("DELETE", url),
  upload: <T>(url: string, form: FormData) => request<T>("POST", url, undefined, form),
};

export function track(name: string, props?: Record<string, string | number>) {
  try {
    const payload = JSON.stringify({ name, props });
    if (navigator.sendBeacon) {
      navigator.sendBeacon("/api/events", new Blob([payload], { type: "application/json" }));
    } else {
      void fetch("/api/events", { method: "POST", body: payload, headers: { "Content-Type": "application/json" } });
    }
  } catch {
    /* 埋点失败忽略 */
  }
}

// ---------------------------------------------------------------- 类型

export interface Me {
  id: string;
  pickup_code: string;
  invite_code: string;
  consent: boolean;
  consent_version: string;
  free_credits: number;
  pay_enabled: boolean;
  pay_mode: "mock" | "nowpay" | "off";
  showcase_url: string;
  ttl_hours: number;
  redo_days: number;
}

export interface SpecSource {
  title: string;
  url: string;
  official: boolean;
}

export interface Spec {
  id: string;
  key: string;
  name: string;
  short: string;
  category: string;
  region: string;
  width: number;
  height: number;
  size_mode: "exact" | "min";
  min_width: number | null;
  min_height: number | null;
  mm: number[] | null;
  physical_mm: number[];
  dpi: number;
  kb_min: number | null;
  kb_max: number | null;
  format: string;
  backgrounds: string[];
  bg_names: string[];
  size_text: string;
  kb_text: string;
  status: "verified" | "reference" | "standard";
  verified_at: string | null;
  window: string;
  hot: boolean;
  custom: boolean;
  alert: string;
  has_official_tool?: boolean;
  verify_note?: string;
  // 仅完整规格
  rules?: string[];
  notes?: string;
  sources?: SpecSource[];
  official_tool?: { required: boolean; note: string } | null;
  head_ratio?: number[];
  checks?: Record<string, boolean>;
}

export interface SpecList {
  items: Spec[];
  categories: string[];
  bg_colors: Record<string, { name: string; rgb: number[] }>;
  total: number;
}

export type Status = "pass" | "warn" | "fail" | "info";

export interface ReportItem {
  id: string;
  label: string;
  status: Status;
  value: string;
  tip: string;
}

export interface Report {
  overall: "pass" | "warn" | "fail";
  summary: string;
  items: ReportItem[];
  counts: { pass: number; warn: number; fail: number };
}

export interface ValidationItem {
  id: string;
  label: string;
  status: Status;
  detail: string;
}

export interface PhotoView {
  id: string;
  status: "queued" | "processing" | "ready" | "rejected" | "failed";
  stage: string;
  stage_text: string;
  error: string | null;
  created_at: string;
  expires_at: string;
  unlocked: boolean;
  unlock_type: string | null;
  redo_of: string | null;
  can_redo: boolean;
  spec: Spec;
  bg: string;
  bg_name: string;
  backgrounds: { key: string; name: string }[];
  report?: Report;
  validation?: ValidationItem[];
  output?: { width: number; height: number; kb: number; quality: number; head_ratio: number; top_margin: number };
  preview_url?: string;
  downloads?: { photo: string; layout: string; filename: string };
  free_credits?: number;
}

export interface Option {
  sku_id: string;
  name: string;
  price: string;
  quota: number | null;
  period: string | null;
}

export interface ProductOffer {
  status: string;
  billing_mode: string | null;
  product_name: string | null;
  options: Option[];
  purchasable: boolean;
}

export interface Offers {
  enabled: boolean;
  mode: string;
  count: ProductOffer | null;
  monthly: ProductOffer | null;
}

export interface Purchase {
  out_request_no: string;
  product: "count" | "monthly";
  sku_id: string | null;
  photo_id: string | null;
  status: string;
  purchase_url: string | null;
  qr_code: string | null;
  expire_time: string | null;
  expired: boolean;
}

export interface UnlockResult {
  state: "unlocked" | "need_purchase" | "confirming" | "error";
  message?: string;
  remaining?: number;
}

export interface PurchaseCheck {
  purchase: Purchase;
  pay: { state: "paid" | "waiting" | "unknown"; remaining?: number | null; valid_until?: string };
  unlock?: UnlockResult;
  photo?: PhotoView;
  pickup_code?: string;
}

export interface Balance {
  remaining: number | null;
  free_credits: number;
  monthly: { decision: string; valid_until?: string } | null;
}

export const BG_HEX: Record<string, string> = {
  white: "#FFFFFF",
  blue: "#438EDB",
  red: "#FF0000",
  lightgray: "#EBEBEB",
};

export function bgHex(bg: string): string {
  if (BG_HEX[bg]) return BG_HEX[bg];
  return /^#?[0-9a-f]{6}$/i.test(bg) ? `#${bg.replace("#", "")}` : "#FFFFFF";
}

export const STATUS_TEXT: Record<Spec["status"], string> = {
  verified: "已核实官方公告",
  reference: "参考规格，待核实",
  standard: "通用尺寸",
};
