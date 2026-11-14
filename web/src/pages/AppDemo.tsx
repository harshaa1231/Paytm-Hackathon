// The demo: PakkaKhata shown INSIDE a merchant app styled like Paytm's (white rounded cards on light grey, round blue
// action buttons, due-alert rows, offer banner, tile grid, floating QR pill). Concept only: no Paytm logo artwork.
// No technical panels here; those are behind "For judges".
import { useCallback, useEffect, useRef, useState } from "react";
import {
  ArrowLeft, BarChart3, BatteryFull, Bell, BookOpen, CalendarClock, ChevronRight, CircleHelp, Gift, Handshake, Landmark,
  Languages, Play, QrCode, ReceiptText, RotateCcw, Search, Signal, Sparkles, Store, Undo2, Volume2, Wifi,
} from "lucide-react";
import { CardView } from "../components/Cards";
import { api, cx, inr, type Card, type DemoConfig, type KhataCustomer, type ShopState, type Today } from "../lib";

type Screen = "home" | "payments" | "khata" | "profile";
type Toast = { kind: "ok" | "info" | "warn" | "err"; text: string; undo?: string } | null;
type Notif = { title: string; body: string; cta: boolean } | null;

const NAVY = "#002e6e";
const ICON_BLUE = "#0d4ea6";
const fmt = (s: string | undefined, kw: Record<string, string>) => (s ?? "").replace(/\{(\w+)\}/g, (_, k) => kw[k] ?? `{${k}}`);
const titleCase = (s: string) => s.toLowerCase().replace(/\b\w/g, (c) => c.toUpperCase());
const initials = (s: string) => s.split(/\s+/).filter(Boolean).slice(0, 2).map((w) => w[0]).join("").toUpperCase() || "?";
const time = (ts: string) => ts.slice(11, 16);
const AV = ["bg-sky-100 text-sky-800", "bg-amber-100 text-amber-800", "bg-emerald-100 text-emerald-800", "bg-rose-100 text-rose-800", "bg-violet-100 text-violet-800"];
const avatarTone = (s: string) => AV[[...s].reduce((a, c) => a + c.charCodeAt(0), 0) % AV.length];

export default function AppDemo({ cfg, shop, setShop, lang, setLang }:
  { cfg: DemoConfig; shop: string; setShop: (s: string) => void; lang: string; setLang: (l: string) => void }) {
  const [screen, setScreen] = useState<Screen>("home");
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
  useEffect(() => { scroller.current?.scrollTo({ top: 0 }); }, [screen, khataTab]);

  const run = async (fn: () => Promise<void>) => {
    setBusy(true);
    try { await fn(); } catch (e: any) { setToast({ kind: "err", text: e.message || String(e) }); } finally { setBusy(false); }
  };
  const go = (s: Screen, sub?: "pakka" | "customers") => { setScreen(s); if (sub) setKhataTab(sub); setNotif(null); };
  const notInConcept = (label: string) => setToast({ kind: "info", text: `${label} isn't part of this concept.` });

  // ---------------------------------------------------------------- demo driver (outside the phone)
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
  const reset = () => run(async () => { await api.reset(); setNotif(null); setToast(null); setScreen("home"); await refresh(); });

  // ---------------------------------------------------------------- shopkeeper taps (inside the phone)
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
  const trust = cards.filter((c) => c.type === "who_to_trust" && !c.info);
  const coming = cards.find((c) => c.type === "coming_back");
  const pakkaCount = pending.length + trust.length;

  // ---------------------------------------------------------------- building blocks in Paytm's visual language
  const WhiteCard = ({ children, className }: { children: React.ReactNode; className?: string }) => (
    <div className={cx("bg-white rounded-[22px]", className)}>{children}</div>
  );
  const RoundAction = ({ icon: Icon, label, onClick, badge }: { icon: any; label: string; onClick?: () => void; badge?: number }) => (
    <button onClick={onClick ?? (() => notInConcept(label.replace("\n", " ")))} className="relative flex flex-col items-center gap-2">
      <span className="w-[54px] h-[54px] rounded-full grid place-items-center" style={{ background: ICON_BLUE }}><Icon size={24} className="text-white" strokeWidth={1.8} /></span>
      <span className="text-[12.5px] leading-[15px] text-[#333] text-center whitespace-pre-line">{label}</span>
      {!!badge && <span className="absolute -top-1 right-1 min-w-[18px] h-[18px] px-1 rounded-full bg-[#fd5c63] text-white text-[10px] font-bold grid place-items-center">{badge}</span>}
    </button>
  );
  const SubHeader = ({ title, sub }: { title: string; sub?: string }) => (
    <div className="bg-white px-3 pt-2 pb-3 flex items-center gap-2 sticky top-0 z-10 border-b border-slate-100">
      <button onClick={() => go("home")} aria-label="Back" className="w-9 h-9 grid place-items-center rounded-full hover:bg-slate-100"><ArrowLeft size={21} /></button>
      <div className="leading-tight"><div className="text-[17px] font-semibold text-[#111]">{title}</div>{sub && <div className="text-[12px] text-ink-3">{sub}</div>}</div>
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

  // ---------------------------------------------------------------- HOME (mirrors the Paytm home layout)
  const first = pending[0];
  const home = (
    <div className="px-3 pt-2 space-y-3 pb-24">
      {/* top bar: avatar · wordmark · bell */}
      <div className="flex items-center gap-3 pt-1">
        <button onClick={() => go("profile")} className="w-11 h-11 rounded-full bg-[#dbe7f7] text-[#0d4ea6] font-bold grid place-items-center text-[15px]">{initials(shopName)}</button>
        <div className="leading-none">
          <span className="text-[21px] font-extrabold tracking-tight" style={{ color: NAVY }}>Paytm</span>
          <span className="text-[15px] font-semibold text-[#00a3e0] ml-1">for Business</span>
          <div className="text-[9.5px] uppercase tracking-[0.14em] text-ink-3 mt-1">concept</div>
        </div>
        <button className="ml-auto relative w-10 h-10 grid place-items-center" onClick={() => go("khata", "pakka")} aria-label="Notifications">
          <Bell size={24} strokeWidth={1.8} />
          {pakkaCount > 0 && <span className="absolute top-1.5 right-1.5 w-2.5 h-2.5 rounded-full bg-[#fd5c63] ring-2 ring-[#f3f4f6]" />}
        </button>
      </div>

      {/* search pill */}
      <div className="bg-white rounded-full h-12 flex items-center gap-3 px-5 text-[#8a8a8a] text-[15px]"><Search size={20} className="text-[#333]" /> Search customers or payments</div>

      {/* 4 round blue actions */}
      <div className="grid grid-cols-4 pt-2 pb-1">
        <RoundAction icon={QrCode} label={"Show my\nQR"} />
        <RoundAction icon={ReceiptText} label={"Payments\n& History"} onClick={() => go("payments")} />
        <RoundAction icon={BookOpen} label={"Business\nKhata"} onClick={() => go("khata", "pakka")} badge={pakkaCount} />
        <RoundAction icon={Landmark} label={"Settle to\nBank"} />
      </div>

      {/* due-alert row (like "Electricity ₹1,789 due tomorrow · Pay Bill") */}
      {first ? (
        <WhiteCard className="px-4 py-3.5 flex items-center gap-3">
          <span className="w-10 h-10 rounded-full bg-money-soft text-money grid place-items-center shrink-0"><BookOpen size={19} /></span>
          <button className="flex-1 min-w-0 text-left" onClick={() => go("khata", "pakka")}>
            <div className="text-[14px] font-semibold text-[#222] truncate">{inr(first.amount_paise)} from {first.subtitle?.replace("UPI name: ", "").split(" · ")[0] || "a customer"}</div>
            <div className="text-[13px] text-[#0d4ea6] leading-snug">{first.title.split(" paid ")[0]}'s udhaar?</div>
          </button>
          <button onClick={() => go("khata", "pakka")} className="rounded-full bg-[#e8f3fd] text-[#0d4ea6] text-[13.5px] font-semibold px-4 py-1.5 border border-[#c9e1f8] shrink-0">Confirm</button>
        </WhiteCard>
      ) : (
        <WhiteCard className="px-4 py-3.5 flex items-center gap-3">
          <span className="w-10 h-10 rounded-full bg-[#e8f3fd] text-[#0d4ea6] grid place-items-center shrink-0"><ReceiptText size={19} /></span>
          <button className="flex-1 text-left" onClick={() => go("payments")}>
            <div className="text-[14px] font-semibold text-[#222]">Today's collection {today ? inr(today.total_paise) : ""}</div>
            <div className="text-[13px] text-ink-3">{today?.count ?? 0} payment{today?.count === 1 ? "" : "s"} into your QR</div>
          </button>
          <ChevronRight size={18} className="text-ink-3" />
        </WhiteCard>
      )}

      {/* offer-style banner */}
      <button onClick={() => go("khata", "pakka")} className="w-full rounded-[22px] bg-[#cdeef8] px-4 py-4 flex items-center gap-3 text-left">
        <span className="w-12 h-12 rounded-2xl bg-white/70 grid place-items-center shrink-0"><Sparkles size={24} className="text-[#0d4ea6]" /></span>
        <span className="flex-1"><span className="block text-[17px] font-bold text-[#1a1a1a] leading-snug">New in Business Khata: PakkaKhata</span>
          <span className="block text-[13px] text-[#333]">Know who paid your udhaar, and who you can trust</span></span>
        <ChevronRight size={20} />
      </button>

      {/* tile grid (like Postpaid / SIP / App Store tiles) */}
      <div className="grid grid-cols-2 gap-3">
        <button onClick={() => go("khata", "customers")} className="row-span-2 bg-white rounded-[22px] p-4 text-left flex flex-col">
          <span className="w-10 h-10 rounded-xl grid place-items-center text-white" style={{ background: NAVY }}><BookOpen size={20} /></span>
          <span className="mt-auto pt-8 block text-[15px] font-semibold text-[#222]">Business Khata</span>
          <span className="block text-[13px] text-ink-3">Udhaar owed to you</span>
          <span className="block text-[20px] font-bold num text-[#c2410c]">{st ? inr(st.owed_total_paise) : "…"}</span>
          <span className="block text-[12px] text-ink-3">from {st?.open_customers ?? 0} customers</span>
        </button>
        <button onClick={() => go("khata", "pakka")} className="bg-white rounded-[22px] p-4 text-left flex items-center gap-3">
          <Handshake size={26} className="text-trust shrink-0" />
          <span><span className="block text-[14px] font-semibold text-[#222] leading-tight">Who you can trust</span>
            <span className="block text-[12px] text-ink-3">{trust.length ? `${trust.length} suggestion${trust.length > 1 ? "s" : ""}` : "None today"}</span></span>
        </button>
        <button onClick={() => go("khata", "pakka")} className="bg-white rounded-[22px] p-4 text-left flex items-center gap-3">
          <CalendarClock size={26} className="text-sky shrink-0" />
          <span><span className="block text-[14px] font-semibold text-[#222] leading-tight">Coming back this week</span>
            <span className="block text-[12px] text-ink-3 num">{coming?.range ? `~${inr(coming.amount_paise)} of ${inr(coming.range.total_paise)}` : "Nothing pending"}</span></span>
        </button>
      </div>

      {/* section card (like "Recharge & Bills" / "Travel & Tickets") */}
      <WhiteCard className="px-4 pt-4 pb-5">
        <div className="flex items-center justify-between"><span className="text-[19px] font-bold text-[#1a1a1a]">Today's payments</span>
          <button onClick={() => go("payments")} className="text-[14px] font-medium text-[#0d6efd] flex items-center gap-1">View All <ChevronRight size={15} /></button></div>
        {today && today.payments.length > 0 ? <div className="divide-y divide-slate-100 mt-1">{today.payments.slice(0, 3).map((p) => <PaymentRow key={p.txn_id + p.status} p={p} />)}</div>
          : <div className="py-5 text-center text-[13px] text-ink-3">No payments yet today.</div>}
      </WhiteCard>

      <WhiteCard className="px-4 pt-4 pb-5">
        <div className="text-[19px] font-bold text-[#1a1a1a] mb-4">My Business</div>
        <div className="grid grid-cols-4 gap-y-4">
          {([[Volume2, "Soundbox"], [Store, "QR Stand"], [BarChart3, "Reports"], [Gift, "Offers"], [CircleHelp, "Help"]] as const).map(([Icon, label]) => (
            <button key={label} onClick={() => notInConcept(label)} className="flex flex-col items-center gap-2 text-[12.5px] text-[#333]">
              <Icon size={26} strokeWidth={1.6} className="text-[#0d4ea6]" />{label}</button>
          ))}
        </div>
      </WhiteCard>
    </div>
  );

  // ---------------------------------------------------------------- PAYMENTS
  const payments = (
    <>
      <SubHeader title="Payments & History" sub={today ? `Today · ${inr(today.total_paise)} from ${today.count} payment${today.count === 1 ? "" : "s"}` : ""} />
      <div className="px-3 pt-3 pb-6">
        <WhiteCard className="px-4">
          {today && today.payments.length > 0 ? <div className="divide-y divide-slate-100">{today.payments.map((p) => <PaymentRow key={p.txn_id + p.status} p={p} />)}</div>
            : <div className="py-10 text-center text-[13px] text-ink-3">No payments yet today.</div>}
        </WhiteCard>
        <p className="text-[11.5px] text-ink-3 px-2 pt-2">Payments that look like udhaar wait for your tap in Business Khata. Nothing changes until you confirm.</p>
      </div>
    </>
  );

  // ---------------------------------------------------------------- BUSINESS KHATA (where PakkaKhata lives)
  const Section = ({ title, count, children }: { title: string; count?: number; children: React.ReactNode }) => (
    <div className="space-y-2.5">
      <div className="flex items-center gap-2 px-1 pt-1"><span className="text-[15px] font-bold text-[#1a1a1a]">{title}</span>
        {!!count && <span className="min-w-[20px] h-5 px-1.5 rounded-full bg-[#fd5c63] text-white text-[11px] font-bold grid place-items-center">{count}</span>}</div>
      {children}
    </div>
  );
  const khataScreen = (
    <>
      <SubHeader title={L.app_bar ?? "Business Khata"} sub={shopName} />
      <div className="px-3 pt-3">
        <WhiteCard className="p-4 grid grid-cols-2 divide-x divide-slate-100">
          <div className="pr-3"><div className="text-[12px] text-ink-3">Udhaar owed to you</div><div className="text-[22px] font-bold num text-[#c2410c]">{st ? inr(st.owed_total_paise) : "…"}</div></div>
          <div className="pl-4"><div className="text-[12px] text-ink-3">Customers with udhaar</div><div className="text-[22px] font-bold num">{st?.open_customers ?? 0}</div></div>
        </WhiteCard>
        <div className="mt-3 grid grid-cols-2 bg-white rounded-full p-1 text-[14px] font-semibold">
          <button onClick={() => setKhataTab("pakka")} className={cx("py-2 rounded-full flex items-center justify-center gap-1.5", khataTab === "pakka" ? "text-white" : "text-ink-2")}
            style={khataTab === "pakka" ? { background: NAVY } : undefined}>
            PakkaKhata <Sparkles size={13} />{pakkaCount > 0 && <span className="rounded-full bg-[#fd5c63] text-white text-[10px] px-1.5">{pakkaCount}</span>}</button>
          <button onClick={() => setKhataTab("customers")} className={cx("py-2 rounded-full", khataTab === "customers" ? "text-white" : "text-ink-2")}
            style={khataTab === "customers" ? { background: NAVY } : undefined}>{L.tab_customers ?? "Customers"}</button>
        </div>
      </div>
      {khataTab === "pakka" ? (
        <div className="px-3 pt-4 pb-6 space-y-5">
          <Section title="Payments to confirm" count={pending.length}>
            {pending.length ? pending.map((c) => <CardView key={c.card_id} card={c} onAction={onAction} busy={busy} labels={L} />)
              : <div className="rounded-[22px] bg-white px-4 py-5 text-center text-[13px] text-ink-3">{L.done_title ?? "All caught up"}: no payments to confirm.</div>}
          </Section>
          {trust.length > 0 && <Section title="Who you can trust">{trust.map((c) => <CardView key={c.card_id} card={c} onAction={onAction} busy={busy} labels={L} />)}</Section>}
          {cards.filter((c) => c.type === "who_to_trust" && c.info).map((c) => <CardView key={c.card_id} card={c} onAction={onAction} busy={busy} labels={L} />)}
          {coming && <Section title="Coming back this week"><CardView card={coming} onAction={onAction} busy={busy} labels={L} /></Section>}
          <p className="text-[11px] text-ink-3 text-center">PakkaKhata only suggests. Nothing changes until you tap.</p>
        </div>
      ) : (
        <div className="px-3 pt-3 pb-6">
          <WhiteCard className="px-4 divide-y divide-slate-100">
            {khata.map((k) => (
              <div key={k.customer_id} className="flex items-center gap-3 py-3">
                <span className={cx("w-10 h-10 rounded-full grid place-items-center text-[13px] font-semibold shrink-0", avatarTone(k.name))}>{initials(k.name)}</span>
                <span className="flex-1 min-w-0"><span className="block text-[14px] font-medium truncate">{k.name}</span>
                  <span className="block text-[11.5px] text-ink-3">{k.since_days === 0 ? "Since today" : `Since ${k.since_days} day${k.since_days > 1 ? "s" : ""}`}</span></span>
                <span className="text-right"><span className="block text-[15px] font-semibold num text-[#c2410c]">{inr(k.owed_paise)}</span>
                  <span className="block text-[10.5px] text-ink-3">udhaar owed</span></span>
              </div>
            ))}
            {khata.length === 0 && <div className="py-10 text-center text-[13px] text-ink-3">No udhaar open.</div>}
          </WhiteCard>
        </div>
      )}
    </>
  );

  // ---------------------------------------------------------------- PROFILE (shop + language)
  const profile = (
    <>
      <SubHeader title="Profile" sub={shopName} />
      <div className="px-3 pt-3 pb-6 space-y-3">
        <WhiteCard className="p-4">
          <div className="flex items-center gap-2 text-[14px] font-semibold mb-3"><Store size={17} /> Business</div>
          <div className="grid gap-2">
            {cfg.shops.map((s) => (
              <button key={s.id} onClick={() => { setShop(s.id); go("home"); }}
                className={cx("rounded-2xl border px-3 py-2.5 text-left", shop === s.id ? "border-[#0d4ea6] bg-[#e8f3fd]" : "border-slate-200")}>
                <div className="text-[14px] font-medium">{s.name}</div><div className="text-[11.5px] text-ink-3 capitalize">{s.shop_type}</div>
              </button>
            ))}
          </div>
        </WhiteCard>
        <WhiteCard className="p-4">
          <div className="flex items-center gap-2 text-[14px] font-semibold mb-3"><Languages size={17} /> {L.lang_label ?? "Language"}</div>
          <div className="grid grid-cols-3 gap-2">
            {Object.entries(cfg.langs).map(([k, v]) => (
              <button key={k} onClick={() => setLang(k)} className={cx("rounded-2xl border py-2 text-[14px]", lang === k ? "border-[#0d4ea6] bg-[#e8f3fd] font-semibold" : "border-slate-200")}>{v.name}</button>
            ))}
          </div>
          {lang !== "en" && <p className="text-[11.5px] text-ink-3 mt-2">{cfg.langs[lang].reviewed}/{cfg.langs[lang].total} phrases checked by a native speaker so far. The rest show in English.</p>}
        </WhiteCard>
      </div>
    </>
  );

  // ---------------------------------------------------------------- phone
  const phone = (
    <div className="relative flex flex-col h-full bg-[#f3f4f6]">
      <div className="flex items-center justify-between px-7 pt-3 pb-1 text-[13px] font-semibold num text-[#111] bg-[#f3f4f6]">
        <span>9:30</span><span className="flex items-center gap-1"><Signal size={14} /><Wifi size={14} /><BatteryFull size={17} /></span>
      </div>
      <div ref={scroller} className="phone-scroll flex-1 overflow-y-auto">
        {screen === "home" && home}
        {screen === "payments" && payments}
        {screen === "khata" && khataScreen}
        {screen === "profile" && profile}
      </div>

      {screen === "home" && (
        <button onClick={() => notInConcept("Show QR")}
          className="absolute bottom-4 left-1/2 -translate-x-1/2 z-10 rounded-full px-7 h-14 flex items-center gap-2.5 text-white text-[19px] font-semibold shadow-xl border-2 border-[#3d7fd9]"
          style={{ background: "linear-gradient(180deg,#1d5bb8 0%,#062a63 100%)" }}>
          <QrCode size={24} /> Show QR
        </button>
      )}

      {notif && (
        <button onClick={() => notif.cta && go("khata", "pakka")} className="absolute top-9 left-2.5 right-2.5 z-20 anim-in text-left">
          <div className="rounded-2xl bg-white/95 backdrop-blur shadow-xl border border-slate-200 p-3 flex gap-3">
            <span className="w-9 h-9 rounded-xl grid place-items-center shrink-0" style={{ background: NAVY }}><BookOpen size={17} className="text-white" /></span>
            <span className="min-w-0"><span className="flex items-center gap-2 text-[11px] text-ink-3"><b className="text-ink-2">Paytm for Business</b> now</span>
              <span className="block text-[13.5px] font-semibold leading-snug">{notif.title}</span>
              <span className="block text-[12.5px] text-ink-2 leading-snug">{notif.body}</span></span>
          </div>
        </button>
      )}
      {toast && (
        <div className="absolute left-3 right-3 bottom-24 z-20 anim-in" role="status" aria-live="polite">
          <div className={cx("rounded-xl px-4 py-3 text-[13.5px] shadow-lg flex items-start gap-3 text-white",
            { ok: "bg-[#0e3b2a]", info: "bg-[#002e6e]", warn: "bg-[#5b3a06]", err: "bg-[#7f1d1d]" }[toast.kind])}>
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
        <div className="h-eyebrow mb-2">Concept · inside Paytm for Business</div>
        <h1 className="text-[30px] font-bold tracking-tight leading-tight">Udhaar that keeps itself up to date.</h1>
        <p className="text-ink-2 mt-3 text-[15px] leading-relaxed">PakkaKhata lives in <b>Business Khata</b>. It reads the UPI payments already coming into the shop's QR and asks the shopkeeper one simple question at a time.</p>
        <ol className="mt-6 space-y-3 text-[14px]">
          {[
            ["A customer pays the QR", "A notification and a home-screen alert ask: is this udhaar?"],
            ["One tap clears it", "Nothing changes without the shopkeeper's tap."],
            ["Who you can trust", "Regular customers who agreed to share their payment record."],
            ["What's coming back", "A realistic range for the week."],
          ].map(([a, b], i) => (
            <li key={a} className="flex gap-3"><span className="w-7 h-7 rounded-full text-white grid place-items-center text-[13px] font-semibold shrink-0" style={{ background: NAVY }}>{i + 1}</span>
              <span><b className="block">{a}</b><span className="text-ink-3 text-[13px]">{b}</span></span></li>
          ))}
        </ol>
      </aside>

      <div className="justify-self-center w-full sm:w-auto">
        <div className="hidden sm:block w-[390px] h-[820px] rounded-[52px] bg-[#0b1220] p-3 shadow-phone">
          <div className="relative w-full h-full rounded-[42px] overflow-hidden">
            <div className="absolute top-2 left-1/2 -translate-x-1/2 w-24 h-6 rounded-full bg-[#0b1220] z-30" />
            {phone}
          </div>
        </div>
        <div className="sm:hidden h-[calc(100vh-150px)] rounded-3xl overflow-hidden border border-slate-200 shadow-card">{phone}</div>
        <div className="text-[11px] text-ink-3 text-center mt-3">Concept screen in Paytm's visual style, not the real app · synthetic data</div>
      </div>

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
