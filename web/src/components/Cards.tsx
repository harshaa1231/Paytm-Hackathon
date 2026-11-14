import { useState } from "react";
import { ArrowDownLeft, CalendarClock, Check, Handshake, Info, Pencil, UserX, X } from "lucide-react";
import { cx, inr, type Action, type Card } from "../lib";

export type OnAction = (card: Card, body: Record<string, unknown>) => void;

function Shell({ tone, icon, eyebrow, children }: { tone: "money" | "trust" | "sky" | "muted"; icon: React.ReactNode; eyebrow: string; children: React.ReactNode }) {
  const bar = { money: "bg-money", trust: "bg-trust", sky: "bg-sky", muted: "bg-slate-300" }[tone];
  const dot = { money: "bg-money-soft text-money", trust: "bg-trust-soft text-trust", sky: "bg-sky-soft text-sky", muted: "bg-slate-100 text-ink-3" }[tone];
  return (
    <div className="anim-in relative bg-white rounded-2xl shadow-card border border-slate-200/80 overflow-hidden">
      <div className={cx("absolute left-0 top-0 bottom-0 w-1", bar)} />
      <div className="p-4 pl-5">
        <div className="flex items-center gap-2 mb-2">
          <span className={cx("w-7 h-7 rounded-full grid place-items-center", dot)}>{icon}</span>
          <span className="h-eyebrow">{eyebrow}</span>
        </div>
        {children}
      </div>
    </div>
  );
}

const pick = (a: Action) => {
  const b: Record<string, unknown> = { action: a.id };
  if (a.customer_id) b.customer_id = a.customer_id;
  if (a.amount_paise) b.amount_paise = a.amount_paise;
  if (a.extra) b.extra = a.extra;
  return b;
};

export function WhoPaidCard({ card, onAction, busy, labels }: { card: Card; onAction: OnAction; busy: boolean; labels: Record<string, string> }) {
  const [sheet, setSheet] = useState<null | "who" | "amount">(null);
  const cap = Math.min(card.amount_paise, card.open_paise ?? card.amount_paise);
  const [rupees, setRupees] = useState(Math.floor(cap / 100));
  const primary = card.actions.filter((a) => a.kind === "primary");
  const secondary = card.actions.filter((a) => a.kind !== "primary");
  return (
    <Shell tone="money" icon={<ArrowDownLeft size={15} strokeWidth={2.5} />} eyebrow="Who paid you">
      <div className="text-[15px] font-semibold leading-snug">{card.title}</div>
      <div className="text-[34px] font-bold tracking-tight text-money num leading-tight mt-1">+{inr(card.amount_paise)}</div>
      <p className="text-[14px] text-ink-2 leading-relaxed mt-1">{card.body}</p>
      {card.subtitle && <div className="mt-2 text-[11.5px] text-ink-3 bg-slate-50 rounded-lg px-2.5 py-1.5 inline-block">{card.subtitle}</div>}

      {sheet === null && (
        <div className="mt-3 space-y-2">
          {primary.map((a, i) => (
            <button key={i} disabled={busy} onClick={() => onAction(card, pick(a))}
              className={cx("btn btn-lg w-full", i === 0 ? "btn-money" : "btn-ghost")}>
              {i === 0 && <Check size={18} strokeWidth={2.5} />} {a.label}
            </button>
          ))}
          <div className="flex flex-wrap justify-center gap-x-4 gap-y-1 pt-1">
            {secondary.map((a, i) => (
              <button key={i} disabled={busy} className="btn btn-link text-[13px] h-8"
                onClick={() => (a.id === "not_him" && card.alternatives?.length ? setSheet("who") : onAction(card, pick(a)))}>
                {a.id === "not_him" && <UserX size={14} />} {a.label}
              </button>
            ))}
            {card.customer_id && (
              <button disabled={busy} className="btn btn-link text-[13px] h-8" onClick={() => setSheet("amount")}>
                <Pencil size={13} /> {labels.btn_other_amount ?? "Different amount"}
              </button>
            )}
          </div>
        </div>
      )}

      {sheet === "who" && (
        <div className="mt-3 rounded-xl bg-slate-50 p-3 space-y-2">
          <div className="flex items-center justify-between text-[13px] font-medium">Is it one of these customers?
            <button onClick={() => setSheet(null)} aria-label="Close"><X size={16} /></button></div>
          {card.alternatives!.map((alt) => (
            <button key={alt.customer_id} disabled={busy} className="btn btn-md w-full bg-white border border-slate-200 hover:border-slate-300"
              onClick={() => onAction(card, { action: "clear_part", customer_id: alt.customer_id, amount_paise: card.amount_paise })}>{alt.label}</button>
          ))}
          <button disabled={busy} className="btn btn-md w-full btn-ghost" onClick={() => onAction(card, { action: "not_him" })}>None of these</button>
        </div>
      )}

      {sheet === "amount" && (
        <div className="mt-3 rounded-xl bg-slate-50 p-3">
          <div className="flex items-center justify-between text-[13px] font-medium mb-2">Clear how much? (max {inr(cap)})
            <button onClick={() => setSheet(null)} aria-label="Close"><X size={16} /></button></div>
          <div className="flex gap-2">
            <div className="flex items-center flex-1 rounded-xl border border-slate-300 bg-white px-3">
              <span className="text-ink-3">₹</span>
              <input type="number" inputMode="numeric" min={1} max={Math.floor(cap / 100)} value={rupees}
                onChange={(e) => setRupees(Math.max(1, Math.min(Math.floor(cap / 100), Number(e.target.value) || 1)))}
                className="w-full h-11 px-2 outline-none text-[16px] num" />
            </div>
            <button disabled={busy} className="btn btn-lg btn-money"
              onClick={() => onAction(card, { action: "clear_part", customer_id: card.customer_id, amount_paise: rupees * 100 })}>Clear</button>
          </div>
        </div>
      )}
    </Shell>
  );
}

export function TrustCard({ card, onAction, busy }: { card: Card; onAction: OnAction; busy: boolean }) {
  if (card.info) {
    return (
      <Shell tone="muted" icon={<Handshake size={15} />} eyebrow="Who to trust">
        <div className="text-[15px] font-semibold">{card.title}</div>
        <p className="text-[14px] text-ink-2 mt-1">{card.body}</p>
      </Shell>
    );
  }
  const [yes, no] = [card.actions.find((a) => a.id === "offer_yes"), card.actions.find((a) => a.id === "offer_no")];
  return (
    <Shell tone="trust" icon={<Handshake size={15} />} eyebrow="Who to trust">
      <div className="text-[15px] font-semibold leading-snug">{card.title}</div>
      <div className="flex items-baseline gap-2 mt-1">
        <span className="text-[34px] font-bold tracking-tight text-trust num leading-tight">{inr(card.amount_paise)}</span>
        <span className="text-[13px] text-ink-3">udhaar limit</span>
      </div>
      <p className="text-[14px] text-ink-2 leading-relaxed mt-1">{card.body}</p>
      {card.note && <div className="mt-2 text-[12.5px] font-medium text-money">{card.note}</div>}
      <div className="mt-3 grid grid-cols-[1fr_auto] gap-2">
        {yes && <button disabled={busy} className="btn btn-lg btn-navy" onClick={() => onAction(card, { action: "offer_yes" })}><Check size={18} strokeWidth={2.5} />{yes.label}</button>}
        {no && <button disabled={busy} className="btn btn-lg btn-ghost px-5" onClick={() => onAction(card, { action: "offer_no" })}>{no.label}</button>}
      </div>
    </Shell>
  );
}

export function ForecastCard({ card }: { card: Card }) {
  const r = card.range;
  if (!r) {
    return (
      <Shell tone="muted" icon={<CalendarClock size={15} />} eyebrow="What's coming back">
        <div className="text-[15px] font-semibold">{card.title}</div>
        <p className="text-[14px] text-ink-2 mt-1">{card.body}</p>
      </Shell>
    );
  }
  const W = (x: number) => `${Math.max(0, Math.min(100, (x / Math.max(1, r.total_paise)) * 100))}%`;
  return (
    <Shell tone="sky" icon={<CalendarClock size={15} />} eyebrow="What's coming back">
      <div className="text-[15px] font-semibold">{card.title}</div>
      <div className="flex items-baseline gap-2 mt-1">
        <span className="text-[34px] font-bold tracking-tight text-sky num leading-tight">~{inr(card.amount_paise)}</span>
        <span className="text-[13px] text-ink-3">of {inr(r.total_paise)}</span>
      </div>
      {/* range bar: 0 .. total owed, shaded likely range, marker at the expected value */}
      <div className="mt-3" role="img" aria-label={`Likely between ${inr(r.low_paise)} and ${inr(r.high_paise)}, expected ${inr(card.amount_paise)}, of ${inr(r.total_paise)} owed`}>
        <div className="relative h-3 rounded-full bg-slate-100">
          <div className="absolute top-0 bottom-0 rounded-full bg-sky/25" style={{ left: W(r.low_paise), width: `calc(${W(r.high_paise)} - ${W(r.low_paise)})` }} />
          <div className="absolute -top-1 w-1 h-5 rounded bg-sky" style={{ left: `calc(${W(card.amount_paise)} - 2px)` }} />
        </div>
        <div className="relative h-4 mt-1 text-[11px] text-ink-3 num">
          <span className="absolute -translate-x-1/2" style={{ left: W(r.low_paise) }}>{inr(r.low_paise)}</span>
          <span className="absolute -translate-x-1/2" style={{ left: W(r.high_paise) }}>{inr(r.high_paise)}</span>
        </div>
      </div>
      <p className="text-[14px] text-ink-2 leading-relaxed mt-2">{card.body}</p>
      {card.note && <div className="mt-2 flex gap-1.5 text-[12px] text-ink-3"><Info size={14} className="shrink-0 mt-px" />{card.note}</div>}
    </Shell>
  );
}

export function CardView(p: { card: Card; onAction: OnAction; busy: boolean; labels: Record<string, string> }) {
  if (p.card.type === "who_paid") return <WhoPaidCard {...p} />;
  if (p.card.type === "who_to_trust") return <TrustCard {...p} />;
  return <ForecastCard card={p.card} />;
}
