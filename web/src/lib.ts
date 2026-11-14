// API client, types and formatting. The phone screen reads the SAME endpoint Paytm's app would:
// GET /v1/merchants/{mid}/cards. Demo-only routes (/v1/demo/*) power the judge pages.

export type Action = { id: string; label: string; kind: "primary" | "secondary"; customer_id?: string; amount_paise?: number; extra?: string };
export type Card = {
  card_id: string; type: "who_paid" | "who_to_trust" | "coming_back"; title: string; body: string; amount_paise: number;
  actions: Action[]; note?: string; subtitle?: string; customer_id?: string; open_paise?: number; info?: boolean;
  alternatives?: { customer_id: string; label: string }[];
  range?: { total_paise: number; low_paise: number; high_paise: number; n_open: number };
};
export type Shop = { id: string; name: string; shop_type: string };
export type DemoConfig = {
  shops: Shop[]; demo_mode: string; warnings: string[]; shop_keys: Record<string, string>; open_admin: boolean; footer: string;
  demo_now: string; langs: Record<string, { name: string; reviewed: number; total: number }>;
};
export type ShopState = {
  shop_id: string; name: string; shop_type: string; owed_total_paise: number; open_customers: number;
  queue_left: number; next_label: string | null; undo: { txn_id: string; title: string } | null;
};

export type TodayPayment = {
  txn_id: string; payer_name: string; payer_vpa: string; amount_paise: number; app: string; ts: string;
  status: "needs_tap" | "udhaar_cleared" | "purchase" | "failed"; applied_paise: number; card_title: string | null;
};
export type Today = { date: string; total_paise: number; count: number; payments: TodayPayment[] };
export type KhataCustomer = { customer_id: string; name: string; owed_paise: number; since_days: number };

export class ApiError extends Error {
  constructor(public status: number, message: string) { super(message); }
}

async function req<T>(path: string, init: RequestInit = {}, key?: string): Promise<T> {
  const headers: Record<string, string> = { "Content-Type": "application/json", ...(init.headers as Record<string, string>) };
  if (key) headers["X-Shop-Key"] = key;
  const admin = localStorage.getItem("pk_admin_key");
  if (admin && path.startsWith("/v1/demo/re")) headers["X-Admin-Key"] = admin;
  const r = await fetch(path, { ...init, headers });
  const text = await r.text();
  const data = text ? JSON.parse(text) : {};
  if (!r.ok) throw new ApiError(r.status, typeof data.detail === "string" ? data.detail : `HTTP ${r.status}`);
  return data as T;
}

export const api = {
  config: () => req<DemoConfig>("/v1/demo/config"),
  i18n: (lang: string) => req<Record<string, string>>(`/v1/demo/i18n?lang=${lang}`),
  state: (mid: string) => req<ShopState>(`/v1/demo/${mid}/state`),
  cards: (mid: string, lang: string, key: string) => req<{ cards: Card[]; bytes: number }>(`/v1/merchants/${mid}/cards?lang=${lang}`, {}, key),
  decide: (mid: string, key: string, body: Record<string, unknown>) =>
    req<any>(`/v1/merchants/${mid}/decisions`, { method: "POST", body: JSON.stringify(body) }, key),
  simulate: (mid: string, lang: string) => req<any>(`/v1/demo/${mid}/simulate?lang=${lang}`, { method: "POST" }),
  undo: (mid: string, txn_id: string) => req<{ restored: number }>(`/v1/demo/${mid}/undo`, { method: "POST", body: JSON.stringify({ txn_id }) }),
  reset: () => req<any>("/v1/demo/reset", { method: "POST" }),
  retrain: () => req<any>("/v1/demo/retrain", { method: "POST" }),
  payments: (mid: string) => req<{ payments: any[] }>(`/v1/demo/${mid}/payments`),
  today: (mid: string) => req<Today>(`/v1/demo/${mid}/today`),
  khata: (mid: string) => req<{ customers: KhataCustomer[]; total_paise: number }>(`/v1/demo/${mid}/khata`),
  trace: (mid: string, txn: string) => req<any>(`/v1/demo/${mid}/trace/${encodeURIComponent(txn)}`),
  internals: (mid: string) => req<any>(`/v1/demo/${mid}/internals`),
  events: (mid: string) => req<{ events: any[] }>(`/v1/demo/${mid}/events?limit=80`),
  reports: () => req<any>("/v1/demo/reports"),
};

// ₹ with Indian lakh grouping, from integer paise (mirrors core/money.py; never relies on locale)
export function inr(paise: number): string {
  const neg = paise < 0;
  const p = Math.abs(Math.round(paise));
  const rupees = Math.floor(p / 100);
  const rem = p % 100;
  const s = String(rupees);
  let out = s;
  if (s.length > 3) {
    let head = s.slice(0, -3);
    const tail = s.slice(-3);
    const parts: string[] = [];
    while (head.length > 2) { parts.unshift(head.slice(-2)); head = head.slice(0, -2); }
    if (head) parts.unshift(head);
    out = parts.join(",") + "," + tail;
  }
  return `${neg ? "-" : ""}₹${out}${rem ? "." + String(rem).padStart(2, "0") : ""}`;
}

export const pct = (x: number | null | undefined, d = 0) => (x == null ? "—" : `${(x * 100).toFixed(d)}%`);
export const signedPct = (x: number, d = 1) => `${x >= 0 ? "+" : ""}${(x * 100).toFixed(d)}%`;

export function cx(...c: (string | false | null | undefined)[]) {
  return c.filter(Boolean).join(" ");
}

export const STAGE_LABEL: Record<string, string> = {
  vpa_memory: "VPA memory", fuzzy_confident: "RapidFuzz name match", llm: "LLM (ambiguous)", ambiguous: "Ambiguous",
  no_match: "No match → purchase", no_open_udhaar: "No udhaar → purchase", blank_name_pick: "Ask the shopkeeper",
};
