import { useCallback, useEffect, useState } from "react";
import { BatteryFull, BookOpen, CheckCircle2, ChevronRight, Play, RotateCcw, Signal, Undo2, Wifi } from "lucide-react";
import { CardView } from "../components/Cards";
import { api, cx, inr, STAGE_LABEL, type Card, type DemoConfig, type ShopState } from "../lib";

type Toast = { kind: "ok" | "info" | "warn" | "err"; text: string; undo?: string } | null;
type LogItem = { label: string; status: string; stage?: string; txn: string; amount: number; app: string };

const fmt = (s: string | undefined, kw: Record<string, string>) =>
  (s ?? "").replace(/\{(\w+)\}/g, (_, k) => kw[k] ?? `{${k}}`);

export default function Shopkeeper({ cfg, shop, setShop, lang, setLang }:
  { cfg: DemoConfig; shop: string; setShop: (s: string) => void; lang: string; setLang: (l: string) => void }) {
  const [cards, setCards] = useState<Card[]>([]);
  const [bytes, setBytes] = useState(0);
  const [st, setSt] = useState<ShopState | null>(null);
  const [L, setL] = useState<Record<string, string>>({});
  const [busy, setBusy] = useState(false);
  const [toast, setToast] = useState<Toast>(null);
  const [log, setLog] = useState<LogItem[]>([]);
  const key = cfg.shop_keys[shop];

  const refresh = useCallback(async () => {
    const [c, s] = await Promise.all([api.cards(shop, lang, key), api.state(shop)]);
    setCards(c.cards); setBytes(c.bytes); setSt(s);
  }, [shop, lang, key]);

  useEffect(() => { refresh().catch((e) => setToast({ kind: "err", text: e.message })); }, [refresh]);
  useEffect(() => { api.i18n(lang).then(setL).catch(() => {}); }, [lang]);
  useEffect(() => { if (!toast || toast.undo) return; const t = setTimeout(() => setToast(null), 4500); return () => clearTimeout(t); }, [toast]);

  const run = async (fn: () => Promise<void>) => {
    setBusy(true);
    try { await fn(); } catch (e: any) { setToast({ kind: "err", text: e.message || String(e) }); }
    finally { setBusy(false); }
  };

  const simulate = () => run(async () => {
    const r = await api.simulate(shop, lang);
    const p = r.payment;
    setLog((l) => [{ label: r.label, status: r.status, stage: r.match_stage, txn: p.txn_id, amount: p.amount_paise, app: p.app }, ...l].slice(0, 12));
    const amount = inr(p.amount_paise);
    const msg: Record<string, Toast> = {
      card_pending: { kind: "info", text: `${amount} came in on ${p.app}. Check the card.` },
      purchase_no_card: { kind: "ok", text: fmt(L.toast_purchase, { amount, app: p.app }) },
      duplicate: { kind: "warn", text: fmt(L.toast_ignored, { reason: "same payment ID seen before" }) },
      ignored: { kind: "warn", text: fmt(L.toast_ignored, { reason: `status ${p.status}` }) },
    };
    setToast(msg[r.status] ?? { kind: "info", text: r.status });
    await refresh();
  });

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
        setToast({ kind: "ok", text: res.action === "purchase" ? "Counted as a purchase." : "Got it: not this customer. Remembered for next time." });
      } else if (r.status === "rejected") setToast({ kind: "err", text: res.error });
      else setToast({ kind: "info", text: "Already decided." });
    } else if (r.status === "done") {
      setToast({ kind: "ok", text: r.action === "offer_yes" ? fmt(L.toast_offer, { amount: inr(r.amount_paise), name: r.name })
        : `Okay, not now for ${r.name}. We won't suggest them again for 30 days.` });
    }
    await refresh();
  });

  const undo = (txn: string) => run(async () => {
    const r = await api.undo(shop, txn);
    setToast({ kind: "info", text: `Undone: ${inr(r.restored)} is owed again. History is kept.` });
    await refresh();
  });

  const reset = () => run(async () => {
    await api.reset(); setLog([]); setToast({ kind: "info", text: "Demo reset to the seeded morning." }); await refresh();
  });

  const pending = cards.filter((c) => c.type === "who_paid");
  const rest = cards.filter((c) => c.type !== "who_paid");

  const screen = (
    <div className="relative flex flex-col h-full bg-[#f2f4f8]">
      <div className="bg-navy text-white">
        <div className="flex items-center justify-between px-5 pt-3 pb-1 text-[12px] font-semibold num">
          <span>9:30</span><span className="flex items-center gap-1"><Signal size={13} /><Wifi size={13} /><BatteryFull size={15} /></span>
        </div>
        <div className="px-4 pt-2 pb-3 flex items-center gap-2">
          <BookOpen size={20} />
          <div className="leading-tight">
            <div className="font-semibold text-[16px]">{L.app_bar ?? "Business Khata"}</div>
            <div className="text-[11.5px] text-white/70">{st?.name ?? ""}</div>
          </div>
        </div>
        <div className="flex gap-1 px-3 pb-2 text-[13px]">
          {[L.tab_khata ?? "Khata", L.tab_payments ?? "Payments"].map((t) => (
            <span key={t} className="flex-1 text-center py-1.5 rounded-lg text-white/45">{t}</span>
          ))}
          <span className="flex-1 text-center py-1.5 rounded-lg bg-white text-navy font-semibold">{L.tab_pakka ?? "PakkaKhata ✨"}</span>
        </div>
      </div>

      <div className="phone-scroll flex-1 overflow-y-auto px-3 pt-3 pb-24 space-y-3">
        <div className="rounded-2xl bg-white border border-slate-200/80 p-4 shadow-card">
          <div className="text-[12px] text-ink-3">{L.owed_total ?? "Total udhaar owed to you"}</div>
          <div className="text-[30px] font-bold tracking-tight num">{st ? inr(st.owed_total_paise) : "…"}</div>
          <div className="text-[12px] text-ink-3">{st?.open_customers ?? 0} customers with open udhaar</div>
        </div>
        {pending.length === 0 && (
          <div className="flex items-center gap-2 text-[13px] text-ink-3 px-1"><CheckCircle2 size={16} className="text-money" />
            {L.done_title ?? "All caught up"}: no payments waiting for you.</div>
        )}
        {[...pending, ...rest].map((c) => <CardView key={c.card_id} card={c} onAction={onAction} busy={busy} labels={L} />)}
      </div>

      {toast && (
        <div className="absolute left-3 right-3 bottom-3 anim-in" role="status" aria-live="polite">
          <div className={cx("rounded-xl px-4 py-3 text-[13.5px] shadow-lg flex items-start gap-3 text-white",
            { ok: "bg-[#0e3b2a]", info: "bg-navy", warn: "bg-[#5b3a06]", err: "bg-[#7f1d1d]" }[toast.kind])}>
            <span className="flex-1 leading-snug">{toast.text}</span>
            {toast.undo && <button className="font-semibold text-emerald-300 flex items-center gap-1 shrink-0" onClick={() => undo(toast.undo!)}>
              <Undo2 size={14} />{L.btn_undo ?? "Undo"}</button>}
            <button className="text-white/60 shrink-0" onClick={() => setToast(null)} aria-label="Dismiss">✕</button>
          </div>
        </div>
      )}
    </div>
  );

  return (
    <div className="grid grid-cols-1 lg:grid-cols-[minmax(0,1fr)_400px_minmax(0,1fr)] gap-6 items-start">
      {/* left: presenter controls */}
      <section className="space-y-4 order-2 lg:order-1 min-w-0">
        <div className="panel panel-pad space-y-4">
          <div className="h-eyebrow">Demo controls</div>
          <div>
            <div className="text-xs text-ink-3 mb-1.5">Shop</div>
            <div className="grid grid-cols-2 gap-1 bg-slate-100 p-1 rounded-xl">
              {cfg.shops.map((s) => (
                <button key={s.id} onClick={() => { setShop(s.id); setLog([]); setToast(null); }}
                  className={cx("rounded-lg py-2 text-[13px] font-medium", shop === s.id ? "bg-white shadow-sm" : "text-ink-2")}>
                  {s.name}<div className="text-[11px] text-ink-3 capitalize">{s.shop_type}</div>
                </button>
              ))}
            </div>
          </div>
          <div>
            <div className="text-xs text-ink-3 mb-1.5">Language</div>
            <div className="flex gap-1">
              {Object.entries(cfg.langs).map(([k, v]) => (
                <button key={k} onClick={() => setLang(k)}
                  className={cx("btn btn-md flex-1", lang === k ? "btn-navy" : "btn-ghost")}>{v.name}</button>
              ))}
            </div>
            {lang !== "en" && <p className="text-[11.5px] text-ink-3 mt-1.5">{cfg.langs[lang].reviewed}/{cfg.langs[lang].total} strings checked by a native
              speaker; the rest stay in English until reviewed. Adding a language is a translation file, not engineering.</p>}
          </div>
          <button disabled={busy || !st?.queue_left || shop !== "S001"} onClick={simulate} className="btn btn-lg btn-money w-full">
            <Play size={17} fill="currentColor" /> Simulate next payment {st && shop === "S001" ? `(${st.queue_left} left)` : ""}
          </button>
          <p className="text-[12.5px] text-ink-2 -mt-2 min-h-[2.5em]">
            {shop !== "S001" ? "The demo payment queue runs on Suresh Kirana." : st?.next_label ? <>Next: {st.next_label}</> : "Queue finished. Reset to replay."}
          </p>
          <button disabled={busy} onClick={reset} className="btn btn-md btn-ghost w-full"><RotateCcw size={15} /> Reset demo</button>
        </div>
        {log.length > 0 && (
          <div className="panel panel-pad">
            <div className="h-eyebrow mb-3">What just happened</div>
            <ul className="space-y-2.5">
              {log.map((l, i) => (
                <li key={i} className="text-[13px]">
                  <div className="flex items-center gap-2">
                    <span className="font-semibold num">{inr(l.amount)}</span><span className="text-ink-3">{l.app}</span>
                    <span className={cx("chip ml-auto", l.status === "card_pending" ? "bg-money-soft text-money" : "bg-slate-100 text-ink-2")}>
                      {l.stage ? STAGE_LABEL[l.stage] ?? l.stage : l.status}</span>
                  </div>
                  <div className="text-ink-3 text-[12px] mt-0.5">{l.label}</div>
                  {l.stage && <a href="#/hood" onClick={() => localStorage.setItem("pk_txn", l.txn)}
                    className="text-[12px] text-sky inline-flex items-center gap-0.5 hover:underline">Under the hood <ChevronRight size={12} /></a>}
                </li>
              ))}
            </ul>
          </div>
        )}
      </section>

      {/* center: the phone */}
      <section className="order-1 lg:order-2 flex flex-col items-center min-w-0">
        <div className="text-[11px] text-ink-3 mb-2 text-center">{L.concept_label ?? "Concept: inside Paytm for Business"} · not the real app</div>
        <div className="hidden sm:block w-[390px] h-[800px] rounded-[48px] bg-[#0b1220] p-3 shadow-phone">
          <div className="relative w-full h-full rounded-[38px] overflow-hidden">
            <div className="absolute top-2 left-1/2 -translate-x-1/2 w-24 h-6 rounded-full bg-[#0b1220] z-10" />
            {screen}
          </div>
        </div>
        <div className="sm:hidden w-full h-[78vh] rounded-3xl overflow-hidden border border-slate-200 shadow-card">{screen}</div>
      </section>

      {/* right: integration story */}
      <section className="order-3 space-y-4 min-w-0">
        <div className="panel panel-pad">
          <div className="h-eyebrow mb-2">Same JSON as the API</div>
          <p className="text-[13.5px] text-ink-2 leading-relaxed">This phone renders <code className="text-[12px] bg-slate-100 px-1.5 py-0.5 rounded">GET /v1/merchants/{shop}/cards</code>,
            the endpoint Paytm's app team would call. Response size now: <b className="num">{(bytes / 1024).toFixed(1)} KB</b> (budget 5 KB for low-end phones).</p>
          <a href="/docs" target="_blank" rel="noreferrer" className="btn btn-md btn-ghost mt-3">Open API docs</a>
        </div>
        <div className="panel panel-pad">
          <div className="h-eyebrow mb-2">How it plugs in</div>
          <ol className="text-[13.5px] text-ink-2 space-y-2 list-decimal pl-4">
            <li>UPI payments into the shop's QR arrive as events.</li>
            <li>PakkaKhata matches them to khata customers and scores who pays reliably.</li>
            <li>Cards appear in the Business Khata tab. Nothing changes until the shopkeeper taps.</li>
          </ol>
          <p className="text-[12px] text-ink-3 mt-3">No new app or hardware. Works wherever UPI works.</p>
        </div>
      </section>
    </div>
  );
}
