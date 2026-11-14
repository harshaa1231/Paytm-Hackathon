// The demo: a merchant-app concept on a phone, showing WHERE PakkaKhata lives (the Business Khata tab) and HOW a
// shopkeeper uses it. No technical panels here; those are behind "For judges".
import { useCallback, useEffect, useRef, useState } from "react";
import {
  BarChart3, BatteryFull, Bell, BookOpen, ChevronRight, CircleHelp, Home, Landmark, Languages, Play, QrCode,
  ReceiptText, RotateCcw, Signal, Sparkles, Store, Undo2, User, Volume2, Wifi,
} from "lucide-react";
import { CardView } from "../components/Cards";
import { api, cx, inr, type Card, type DemoConfig, type KhataCustomer, type ShopState, type Today } from "../lib";

type Tab = "home" | "payments" | "khata" | "profile";
type Toast = { kind: "ok" | "info" | "warn" | "err"; text: string; undo?: string } | null;
type Notif = { title: string; body: string; cta: boolean } | null;

const fmt = (s: string | undefined, kw: Record<string, string>) => (s ?? "").replace(/\{(\w+)\}/g, (_, k) => kw[k] ?? `{${k}}`);
const titleCase = (s: string) => s.toLowerCase().replace(/\b\w/g, (c) => c.toUpperCase());
const initials = (s: string) => s.split(/\s+/).filter(Boolean).slice(0, 2).map((w) => w[0]).join("").toUpperCase() || "?";
const time = (ts: string) => ts.slice(11, 16);
const AV = ["bg-sky-100 text-sky-800", "bg-amber-100 text-amber-800", "bg-emerald-100 text-emerald-800", "bg-rose-100 text-rose-800", "bg-violet-100 text-violet-800"];
const avatarTone = (s: string) => AV[[...s].reduce((a, c) => a + c.charCodeAt(0), 0) % AV.length];

export default function AppDemo({ cfg, shop, setShop, lang, setLang }:
  { cfg: DemoConfig; shop: string; setShop: (s: string) => void; lang: string; setLang: (l: string) => void }) {
  const [tab, setTab] = useState<Tab>("home");
  const [khataTab, setKhataTab] = useState<"pakka" | "customers">("pakka");
  const [cards, setCards] = useState<Card[]>([]);
  const [st, setSt] = useState<ShopState | null>(null);
  const [today, setToday] = useState<Today | null>(null);
  const [khata, setKhata] = useState<KhataCustomer[]>([]);
  const [L, setL] = useState<Record<string, string>>({});
  const [busy, setBusy] = useState(false);
  const [toast, setToast] = useState<Toast>(null);
  const [notif, setNotif] = useState<Notif>(null);
  const scroller = useRef<HTMLDivElement>(null);
  const key = cfg.shop_keys[shop];
  const shopName = cfg.shops.find((s) => s.id === shop)?.name ?? "";

  const refresh = useCallback(async () => {
    const [c, s, t, k] = await Promise.all([api.cards(shop, lang, key), api.state(shop), api.today(shop), api.khata(shop)]);
    setCards(c.cards); setSt(s); setToday(t); setKhata(k.customers);
  }, [shop, lang, key]);

  useEffect(() => { refresh().catch((e) => setToast({ kind: "err", text: e.message })); }, [refresh]);
  useEffect(() => { api.i18n(lang).then(setL).catch(() => {}); }, [lang]);
  useEffect(() => { if (!toast || toast.undo) return; const t = setTimeout(() => setToast(null), 4500); return () => clearTimeout(t); }, [toast]);
  useEffect(() => { if (!notif) return; const t = setTimeout(() => setNotif(null), 7000); return () => clearTimeout(t); }, [notif]);
  useEffect(() => { scroller.current?.scrollTo({ top: 0 }); }, [tab, khataTab]);

  const run = async (fn: () => Promise<void>) => {
    setBusy(true);
    try { await fn(); } catch (e: any) { setToast({ kind: "err", text: e.message || String(e) }); } finally { setBusy(false); }
  };

  const go = (t: Tab, sub?: "pakka" | "customers") => { setTab(t); if (sub) setKhataTab(sub); setNotif(null); };

  // ---------------------------------------------------------------- demo driver (outside the app)
  const nextPayment = () => run(async () => {
    const r = await api.simulate(shop, lang);
    const p = r.payment;
    const who = p.payer_name ? titleCase(p.payer_name) : "a customer";
    if (r.status === "card_pending") {
      setNotif({ title: `${inr(p.amount_paise)} received from ${who}`, body: `${r.card.title}. Tap to confirm in Business Khata.`, cta: true });
    } else if (r.status === "purchase_no_card") {
      setNotif({ title: `${inr(p.amount_paise)} received from ${who}`, body: `On ${p.app}. Counted as a sale.`, cta: false });
    } else if (r.status === "duplicate") {
      setToast({ kind: "warn", text: "The same payment arrived twice. Counted once." });
    } else if (r.status === "ignored") {
      setToast({ kind: "warn", text: `A ${inr(p.amount_paise)} payment failed. Nothing recorded.` });
    }
    await refresh();
  });
  const reset = () => run(async () => { await api.reset(); setNotif(null); setToast(null); setTab("home"); await refresh(); });

  // ---------------------------------------------------------------- shopkeeper actions (inside the app)
  const onAction = (card: Card, body: Record<string, unknown>) => run(async () => {
    const r = await api.decide(shop, key, { card_id: card.card_id, ...body });
    if (card.type === "who_paid") {
      const res = r.result || {};
      if (r.status === "done" && (res.action === "clear_full" || res.action === "clear_part")) {
        const name = res.customer_id === card.customer_id ? card.title.split(" paid ")[0] : "Customer";
        let text = fmt(L.toast_cleared, { amount: inr(res.applied_paise), name, left: inr(res.left_owed_paise) });
        if (res.extra === "advance" && res.leftover_paise) text += ` ${inr(res.leftover_paise)} kept as advance.`;
        setToast({ kind: "ok", text, undo: card.card_id.slice(4) });
      } else if (r.status === "done") {
        setToast({ kind: "ok", text: res.action === "purchase" ? "Counted as a sale." : "Got it: not this customer. Remembered for next time." });
      } else if (r.status === "rejected") setToast({ kind: "err", text: res.error });
    } else if (r.status === "done") {
      setToast({ kind: "ok", text: r.action === "offer_yes" ? fmt(L.toast_offer, { amount: inr(r.amount_paise), name: r.name })
        : `Okay, not now for ${r.name}. We won't suggest them again for 30 days.` });
    }
    await refresh();
  });
  const undo = (txn: string) => run(async () => {
    const r = await api.undo(shop, txn);
    setToast({ kind: "info", text: `Undone: ${inr(r.restored)} is owed again.` });
    await refresh();
  });

  const pending = cards.filter((c) => c.type === "who_paid");
  const trust = cards.filter((c) => c.type === "who_to_trust");
  const coming = cards.filter((c) => c.type === "coming_back");
  const pakkaBadge = pending.length + trust.filter((c) => !c.info).length;

  // ---------------------------------------------------------------- screens
  const Header = ({ title, sub }: { title: string; sub?: string }) => (
    <div className="bg-navy text-white px-4 pt-3 pb-4">
      <div className="text-[18px] font-semibold">{title}</div>
      {sub && <div className="text-[12px] text-white/70">{sub}</div>}
    </div>
  );

  const PaymentRow = ({ p }: { p: Today["payments"][number] }) => {
    const name = p.payer_name ? titleCase(p.payer_name) : "UPI customer";
    const chip = {
      needs_tap: <span className="chip bg-amber-100 text-amber-800">Confirm udhaar?</span>,
      udhaar_cleared: <span className="chip bg-money-soft text-money">Udhaar cleared</span>,
      purchase: <span className="chip bg-slate-100 text-ink-2">Sale</span>,
      failed: <span className="chip bg-red-50 text-red-700">Failed</span>,
    }[p.status];
    return (
      <button className="w-full flex items-center gap-3 py-3 text-left" onClick={() => p.status === "needs_tap" && go("khata", "pakka")}>
        <span className={cx("w-10 h-10 rounded-full grid place-items-center text-[13px] font-semibold shrink-0", avatarTone(name))}>{initials(name)}</span>
        <span className="flex-1 min-w-0">
          <span className="block text-[14px] font-medium truncate">{name}</span>
          <span className="block text-[11.5px] text-ink-3">{time(p.ts)} · {p.app} · {p.payer_vpa || "no UPI ID"}</span>
        </span>
        <span className="text-right shrink-0">
          <span className={cx("block text-[15px] font-semibold num", p.status === "failed" ? "text-ink-3 line-through" : "text-money")}>+{inr(p.amount_paise)}</span>
          {chip}
        </span>
      </button>
    );
  };

  const home = (
    <>
      <div className="bg-navy text-white px-4 pt-3 pb-16">
        <div className="flex items-center gap-3">
          <span className="w-10 h-10 rounded-full bg-white/15 grid place-items-center font-semibold">{initials(shopName)}</span>
          <div className="flex-1 leading-tight"><div className="text-[12px] text-white/70">Good morning</div><div className="font-semibold text-[16px]">{shopName}</div></div>
          <button className="relative" onClick={() => go("khata", "pakka")} aria-label="Notifications">
            <Bell size={21} />{pakkaBadge > 0 && <span className="absolute -top-1 -right-1 w-4 h-4 rounded-full bg-[#ff5a5f] text-[10px] grid place-items-center font-bold">{pakkaBadge}</span>}
          </button>
        </div>
      </div>
      <div className="px-3 -mt-12 space-y-3">
        <div className="bg-white rounded-2xl shadow-card p-4">
          <div className="flex items-center justify-between">
            <div><div className="text-[12px] text-ink-3">Today's collection</div>
              <div className="text-[28px] font-bold tracking-tight num">{today ? inr(today.total_paise) : "…"}</div>
              <div className="text-[12px] text-ink-3">{today?.count ?? 0} payment{today?.count === 1 ? "" : "s"} into your QR</div></div>
            <button onClick={() => go("payments")} className="text-[12.5px] font-semibold text-sky flex items-center">View all <ChevronRight size={15} /></button>
          </div>
        </div>
        <div className="bg-white rounded-2xl shadow-card p-3 grid grid-cols-4 gap-y-3">
          {[
            { icon: QrCode, label: "Receive" }, { icon: Volume2, label: "Soundbox" }, { icon: Landmark, label: "Settlements" },
            { icon: BookOpen, label: "Business Khata", onClick: () => go("khata", "pakka"), badge: "NEW" },
            { icon: ReceiptText, label: "Payments", onClick: () => go("payments") }, { icon: BarChart3, label: "Reports" },
            { icon: Store, label: "My shop" }, { icon: CircleHelp, label: "Help" },
          ].map(({ icon: Icon, label, onClick, badge }) => (
            <button key={label} onClick={onClick ?? (() => setToast({ kind: "info", text: `${label} isn't part of this concept.` }))}
              className={cx("relative flex flex-col items-center gap-1.5 text-[11px] font-medium", onClick ? "text-ink" : "text-ink-3")}>
              <span className={cx("w-11 h-11 rounded-2xl grid place-items-center", onClick ? "bg-sky-soft text-navy" : "bg-slate-50")}><Icon size={20} /></span>
              <span className="leading-tight text-center">{label}</span>
              {badge && <span className="absolute -top-1 right-1 rounded-full bg-[#ff5a5f] text-white text-[9px] font-bold px-1.5">{badge}</span>}
            </button>
          ))}
        </div>
        <button onClick={() => go("khata", "pakka")} className="w-full text-left rounded-2xl p-4 bg-gradient-to-br from-[#0b2a5b] to-[#1f5fae] text-white shadow-card">
          <div className="flex items-center gap-2 text-[12px] font-semibold text-sky-200"><Sparkles size={14} /> NEW IN BUSINESS KHATA</div>
          <div className="text-[16px] font-semibold mt-1 leading-snug">PakkaKhata: know who paid your udhaar, and who you can trust</div>
          <div className="text-[12.5px] text-white/75 mt-1">{pakkaBadge > 0 ? `${pakkaBadge} thing${pakkaBadge > 1 ? "s" : ""} for you today` : "All caught up today"} <ChevronRight size={13} className="inline" /></div>
        </button>
        <div className="bg-white rounded-2xl shadow-card px-4 py-2">
          <div className="flex items-center justify-between pt-2"><span className="text-[14px] font-semibold">Recent payments</span>
            <button onClick={() => go("payments")} className="text-[12.5px] font-semibold text-sky">See all</button></div>
          {today && today.payments.length > 0 ? <div className="divide-y divide-slate-100">{today.payments.slice(0, 3).map((p) => <PaymentRow key={p.txn_id + p.status} p={p} />)}</div>
            : <div className="py-6 text-center text-[13px] text-ink-3">No payments yet today.</div>}
        </div>
      </div>
    </>
  );

  const payments = (
    <>
      <Header title="Payments" sub={today ? `Today · ${inr(today.total_paise)} from ${today.count} payment${today.count === 1 ? "" : "s"}` : ""} />
      <div className="px-3 pt-3">
        <div className="bg-white rounded-2xl shadow-card px-4">
          {today && today.payments.length > 0 ? <div className="divide-y divide-slate-100">{today.payments.map((p) => <PaymentRow key={p.txn_id + p.status} p={p} />)}</div>
            : <div className="py-10 text-center text-[13px] text-ink-3">No payments yet today.</div>}
        </div>
        <p className="text-[11.5px] text-ink-3 px-2 pt-2">Payments that look like udhaar repayments wait for your tap in Business Khata. Nothing changes until you confirm.</p>
      </div>
    </>
  );

  const Section = ({ title, count, children }: { title: string; count?: number; children: React.ReactNode }) => (
    <div className="space-y-2.5">
      <div className="flex items-center gap-2 px-1 pt-1"><span className="text-[13px] font-semibold text-ink-2">{title}</span>
        {!!count && <span className="chip bg-[#ff5a5f] text-white text-[10px] px-2 py-0">{count}</span>}</div>
      {children}
    </div>
  );

  const khataScreen = (
    <>
      <div className="bg-navy text-white px-4 pt-3 pb-4">
        <div className="flex items-center gap-2"><BookOpen size={19} /><span className="text-[18px] font-semibold">{L.app_bar ?? "Business Khata"}</span></div>
        <div className="mt-3 grid grid-cols-2 gap-2">
          <div className="rounded-xl bg-white/10 px-3 py-2"><div className="text-[11px] text-white/70">{L.owed_total ?? "You'll get"}</div>
            <div className="text-[19px] font-bold num text-emerald-300">{st ? inr(st.owed_total_paise) : "…"}</div></div>
          <div className="rounded-xl bg-white/10 px-3 py-2"><div className="text-[11px] text-white/70">Customers with udhaar</div>
            <div className="text-[19px] font-bold num">{st?.open_customers ?? 0}</div></div>
        </div>
        <div className="mt-3 grid grid-cols-2 bg-white/10 rounded-xl p-1 text-[13px] font-semibold">
          <button onClick={() => setKhataTab("pakka")} className={cx("py-1.5 rounded-lg flex items-center justify-center gap-1.5", khataTab === "pakka" ? "bg-white text-navy" : "text-white/80")}>
            PakkaKhata <Sparkles size={13} />{pakkaBadge > 0 && <span className="rounded-full bg-[#ff5a5f] text-white text-[10px] px-1.5">{pakkaBadge}</span>}</button>
          <button onClick={() => setKhataTab("customers")} className={cx("py-1.5 rounded-lg", khataTab === "customers" ? "bg-white text-navy" : "text-white/80")}>{L.tab_customers ?? "Customers"}</button>
        </div>
      </div>
      {khataTab === "pakka" ? (
        <div className="px-3 pt-3 space-y-4">
          <Section title="Payments to confirm" count={pending.length}>
            {pending.length ? pending.map((c) => <CardView key={c.card_id} card={c} onAction={onAction} busy={busy} labels={L} />)
              : <div className="rounded-2xl bg-white border border-dashed border-slate-300 px-4 py-5 text-center text-[13px] text-ink-3">{L.done_title ?? "All caught up"}: no payments to confirm.</div>}
          </Section>
          {trust.length > 0 && <Section title="Who you can trust">{trust.map((c) => <CardView key={c.card_id} card={c} onAction={onAction} busy={busy} labels={L} />)}</Section>}
          {coming.length > 0 && <Section title="Coming back this week">{coming.map((c) => <CardView key={c.card_id} card={c} onAction={onAction} busy={busy} labels={L} />)}</Section>}
          <p className="text-[11px] text-ink-3 text-center pb-2">PakkaKhata only suggests. Nothing changes until you tap.</p>
        </div>
      ) : (
        <div className="px-3 pt-3">
          <div className="bg-white rounded-2xl shadow-card px-4 divide-y divide-slate-100">
            {khata.map((k) => (
              <div key={k.customer_id} className="flex items-center gap-3 py-3">
                <span className={cx("w-10 h-10 rounded-full grid place-items-center text-[13px] font-semibold shrink-0", avatarTone(k.name))}>{initials(k.name)}</span>
                <span className="flex-1 min-w-0"><span className="block text-[14px] font-medium truncate">{k.name}</span>
                  <span className="block text-[11.5px] text-ink-3">{k.since_days === 0 ? "Since today" : `Since ${k.since_days} day${k.since_days > 1 ? "s" : ""}`}</span></span>
                <span className="text-right"><span className="block text-[15px] font-semibold num text-[#c2410c]">{inr(k.owed_paise)}</span>
                  <span className="block text-[10.5px] text-ink-3">you'll get</span></span>
              </div>
            ))}
            {khata.length === 0 && <div className="py-10 text-center text-[13px] text-ink-3">No udhaar open.</div>}
          </div>
        </div>
      )}
    </>
  );

  const profile = (
    <>
      <Header title="Profile" sub={shopName} />
      <div className="px-3 pt-3 space-y-3">
        <div className="bg-white rounded-2xl shadow-card p-4">
          <div className="flex items-center gap-2 text-[13px] font-semibold mb-2"><Store size={16} /> Business</div>
          <div className="grid gap-2">
            {cfg.shops.map((s) => (
              <button key={s.id} onClick={() => { setShop(s.id); setTab("home"); setNotif(null); }}
                className={cx("rounded-xl border px-3 py-2.5 text-left", shop === s.id ? "border-navy bg-sky-soft" : "border-slate-200")}>
                <div className="text-[14px] font-medium">{s.name}</div><div className="text-[11.5px] text-ink-3 capitalize">{s.shop_type}</div>
              </button>
            ))}
          </div>
        </div>
        <div className="bg-white rounded-2xl shadow-card p-4">
          <div className="flex items-center gap-2 text-[13px] font-semibold mb-2"><Languages size={16} /> {L.lang_label ?? "Language"}</div>
          <div className="grid grid-cols-3 gap-2">
            {Object.entries(cfg.langs).map(([k, v]) => (
              <button key={k} onClick={() => setLang(k)} className={cx("rounded-xl border py-2 text-[14px]", lang === k ? "border-navy bg-sky-soft font-semibold" : "border-slate-200")}>{v.name}</button>
            ))}
          </div>
          {lang !== "en" && <p className="text-[11.5px] text-ink-3 mt-2">{cfg.langs[lang].reviewed}/{cfg.langs[lang].total} phrases checked by a native speaker so far. The rest show in English.</p>}
        </div>
      </div>
    </>
  );

  // ---------------------------------------------------------------- phone
  const screen = (
    <div className="relative flex flex-col h-full bg-[#f2f4f8]">
      <div className="bg-navy text-white flex items-center justify-between px-6 pt-3 pb-1 text-[12px] font-semibold num">
        <span>9:30</span><span className="flex items-center gap-1"><Signal size={13} /><Wifi size={13} /><BatteryFull size={15} /></span>
      </div>
      <div ref={scroller} className="phone-scroll flex-1 overflow-y-auto pb-6">
        {tab === "home" && home}
        {tab === "payments" && payments}
        {tab === "khata" && khataScreen}
        {tab === "profile" && profile}
      </div>
      <nav className="grid grid-cols-4 bg-white border-t border-slate-200 pb-3 pt-1.5">
        {([["home", Home, "Home"], ["payments", ReceiptText, "Payments"], ["khata", BookOpen, "Khata"], ["profile", User, "Profile"]] as const).map(([id, Icon, label]) => (
          <button key={id} onClick={() => go(id)} className={cx("relative flex flex-col items-center gap-0.5 text-[11px] font-medium", tab === id ? "text-navy" : "text-ink-3")}>
            <Icon size={21} strokeWidth={tab === id ? 2.4 : 1.8} />{label}
            {id === "khata" && pakkaBadge > 0 && <span className="absolute top-0 right-[30%] w-2.5 h-2.5 rounded-full bg-[#ff5a5f] ring-2 ring-white" />}
          </button>
        ))}
      </nav>

      {notif && (
        <button onClick={() => notif.cta && go("khata", "pakka")} className="absolute top-9 left-2.5 right-2.5 z-20 anim-in text-left">
          <div className="rounded-2xl bg-white/95 backdrop-blur shadow-xl border border-slate-200 p-3 flex gap-3">
            <span className="w-9 h-9 rounded-xl bg-navy grid place-items-center shrink-0"><BookOpen size={17} className="text-white" /></span>
            <span className="min-w-0"><span className="flex items-center gap-2 text-[11px] text-ink-3"><b className="text-ink-2">Business</b> now</span>
              <span className="block text-[13.5px] font-semibold leading-snug">{notif.title}</span>
              <span className="block text-[12.5px] text-ink-2 leading-snug">{notif.body}</span></span>
          </div>
        </button>
      )}
      {toast && (
        <div className="absolute left-3 right-3 bottom-[76px] z-20 anim-in" role="status" aria-live="polite">
          <div className={cx("rounded-xl px-4 py-3 text-[13.5px] shadow-lg flex items-start gap-3 text-white",
            { ok: "bg-[#0e3b2a]", info: "bg-navy", warn: "bg-[#5b3a06]", err: "bg-[#7f1d1d]" }[toast.kind])}>
            <span className="flex-1 leading-snug">{toast.text}</span>
            {toast.undo && <button className="font-semibold text-emerald-300 flex items-center gap-1 shrink-0" onClick={() => undo(toast.undo!)}><Undo2 size={14} />{L.btn_undo ?? "Undo"}</button>}
            <button className="text-white/60 shrink-0" onClick={() => setToast(null)} aria-label="Dismiss">✕</button>
          </div>
        </div>
      )}
    </div>
  );

  return (
    <div className="min-h-[calc(100vh-64px)] grid lg:grid-cols-[minmax(0,1fr)_auto_minmax(0,1fr)] items-center gap-8 px-4 py-6">
      <aside className="hidden lg:block max-w-[340px] justify-self-end">
        <div className="h-eyebrow mb-2">Concept · inside the merchant app</div>
        <h1 className="text-[30px] font-bold tracking-tight leading-tight">Udhaar that keeps itself up to date.</h1>
        <p className="text-ink-2 mt-3 text-[15px] leading-relaxed">PakkaKhata lives in the <b>Business Khata</b> tab. It reads the UPI payments already coming into the shop's QR and asks the shopkeeper one simple question at a time.</p>
        <ol className="mt-6 space-y-3 text-[14px]">
          {[
            ["A customer pays the QR", "A notification asks: is this udhaar?"],
            ["One tap clears it", "Nothing changes without the shopkeeper's tap."],
            ["Who you can trust", "Regular customers who agreed to share their payment record."],
            ["What's coming back", "A realistic range, not a guess."],
          ].map(([a, b], i) => (
            <li key={a} className="flex gap-3"><span className="w-7 h-7 rounded-full bg-navy text-white grid place-items-center text-[13px] font-semibold shrink-0">{i + 1}</span>
              <span><b className="block">{a}</b><span className="text-ink-3 text-[13px]">{b}</span></span></li>
          ))}
        </ol>
      </aside>

      <div className="justify-self-center w-full sm:w-auto">
        <div className="hidden sm:block w-[390px] h-[820px] rounded-[52px] bg-[#0b1220] p-3 shadow-phone">
          <div className="relative w-full h-full rounded-[42px] overflow-hidden">
            <div className="absolute top-2 left-1/2 -translate-x-1/2 w-24 h-6 rounded-full bg-[#0b1220] z-30" />
            {screen}
          </div>
        </div>
        <div className="sm:hidden h-[calc(100vh-150px)] rounded-3xl overflow-hidden border border-slate-200 shadow-card">{screen}</div>
        <div className="text-[11px] text-ink-3 text-center mt-3">Concept screen, not the real app · synthetic data</div>
      </div>

      {/* demo driver: small, outside the phone */}
      <div className="justify-self-start self-end lg:self-center w-full lg:w-auto">
        <div className="flex lg:flex-col gap-2 items-stretch justify-center">
          <button disabled={busy || !st?.queue_left || shop !== "S001"} onClick={nextPayment}
            className="btn btn-lg btn-money shadow-card" title={st?.next_label ?? ""}>
            <Play size={16} fill="currentColor" /> {st?.queue_left ? `Next payment (${st.queue_left})` : "No more payments"}
          </button>
          <button disabled={busy} onClick={reset} className="btn btn-lg btn-ghost bg-white border border-slate-200 shadow-card"><RotateCcw size={16} /> Reset</button>
        </div>
        {shop !== "S001" && <p className="text-[11.5px] text-ink-3 mt-2 text-center lg:text-left max-w-[220px]">Demo payments run on Suresh Kirana.</p>}
      </div>
    </div>
  );
}
