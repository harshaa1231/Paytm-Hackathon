import { useEffect, useState } from "react";
import { ArrowRight, CheckCircle2, CircleDashed, MinusCircle, PauseCircle, XCircle } from "lucide-react";
import { api, cx, inr, pct, STAGE_LABEL, type DemoConfig } from "../lib";

const NODES = ["ingest_payment", "find_candidates", "build_card", "judge_card", "ask_shopkeeper", "apply_decision", "learn"];

function Section({ title, sub, children }: { title: string; sub?: string; children: React.ReactNode }) {
  return (
    <section className="panel panel-pad">
      <h3 className="font-semibold text-[16px]">{title}</h3>
      {sub && <p className="text-[13px] text-ink-3 mt-0.5 mb-3">{sub}</p>}
      <div className={sub ? "" : "mt-3"}>{children}</div>
    </section>
  );
}

function Tabs({ tab, setTab }: { tab: string; setTab: (t: string) => void }) {
  const items = [["pay", "Payment → card"], ["trust", "Trust & forecast"], ["json", "API JSON"], ["log", "Audit log"]];
  return (
    <div className="flex gap-1 bg-white border border-slate-200 p-1 rounded-xl w-fit">
      {items.map(([k, l]) => (
        <button key={k} onClick={() => setTab(k)} className={cx("btn btn-md", tab === k ? "bg-navy text-white" : "text-ink-2 hover:bg-slate-100")}>{l}</button>
      ))}
    </div>
  );
}

export default function UnderTheHood({ cfg, shop, setShop, lang }: { cfg: DemoConfig; shop: string; setShop: (s: string) => void; lang: string }) {
  const [tab, setTab] = useState("pay");
  const [payments, setPayments] = useState<any[]>([]);
  const [txn, setTxn] = useState<string | null>(null);
  const [tr, setTr] = useState<any>(null);
  const [internals, setInternals] = useState<any>(null);
  const [json, setJson] = useState<any>(null);
  const [events, setEvents] = useState<any[]>([]);

  useEffect(() => {
    api.payments(shop).then((r) => {
      const list = r.payments.filter((p) => p.kind === "match");
      setPayments(r.payments);
      const want = localStorage.getItem("pk_txn");
      setTxn(list.find((p) => p.txn_id === want)?.txn_id ?? list[0]?.txn_id ?? null);
    });
    api.internals(shop).then(setInternals);
    api.cards(shop, lang, cfg.shop_keys[shop]).then(setJson);
    api.events(shop).then((r) => setEvents(r.events));
  }, [shop, lang, cfg]);
  useEffect(() => { if (txn) api.trace(shop, txn).then(setTr); else setTr(null); }, [shop, txn]);

  return (
    <div className="space-y-5">
      <div className="flex flex-wrap items-end gap-4 justify-between">
        <div>
          <h1 className="text-2xl font-bold tracking-tight">Under the hood</h1>
          <p className="text-ink-2 text-[14px] mt-1 max-w-2xl">What happened behind each card: the name match, which model answered, the judge's two checks,
            and the LangGraph pause and resume. UPI IDs are masked everywhere.</p>
        </div>
        <div className="flex gap-2 items-center">
          <select value={shop} onChange={(e) => setShop(e.target.value)} className="h-10 rounded-xl border border-slate-300 bg-white px-3 text-sm">
            {cfg.shops.map((s) => <option key={s.id} value={s.id}>{s.name}</option>)}
          </select>
          <Tabs tab={tab} setTab={setTab} />
        </div>
      </div>

      {tab === "pay" && (
        payments.filter((p) => p.kind === "match").length === 0 ? (
          <div className="panel panel-pad text-ink-2">No payments processed yet. Go to <a className="text-sky underline" href="#/shopkeeper">Shopkeeper</a> and press
            <b> Simulate next payment</b>.</div>
        ) : (
          <div className="grid lg:grid-cols-[280px_1fr] gap-5 items-start">
            <div className="panel p-2">
              {payments.map((p, i) => (
                <button key={i} disabled={p.kind !== "match"} onClick={() => { setTxn(p.txn_id); localStorage.setItem("pk_txn", p.txn_id); }}
                  className={cx("w-full text-left rounded-xl px-3 py-2.5", txn === p.txn_id && p.kind === "match" ? "bg-sky-soft" : "hover:bg-slate-50",
                    p.kind !== "match" && "opacity-60 cursor-default")}>
                  <div className="text-[13px] font-medium truncate">{p.payer_name || "(no name on payment)"}</div>
                  <div className="text-[11.5px] text-ink-3">{p.kind === "match" ? STAGE_LABEL[p.stage] ?? p.stage
                    : p.kind === "payment_duplicate" ? "Duplicate event: ignored" : "Not SUCCESS: ignored"} · {p.txn_id}</div>
                </button>
              ))}
            </div>
            {tr && <Trace tr={tr} />}
          </div>
        )
      )}
      {tab === "trust" && internals && <Internals d={internals} />}
      {tab === "json" && json && (
        <Section title={`GET /v1/merchants/${shop}/cards?lang=${lang}`} sub={`Exactly what the phone renders · ${json.bytes} bytes`}>
          <pre className="text-[12px] bg-slate-950 text-slate-100 rounded-xl p-4 overflow-auto max-h-[70vh]">{JSON.stringify(json, null, 2)}</pre>
        </Section>
      )}
      {tab === "log" && (
        <Section title="Audit log" sub="Every event, newest first. Nothing is deleted; undo writes a compensating entry.">
          <div className="overflow-auto max-h-[70vh]">
            <table className="tbl"><thead><tr><th>Time</th><th>Type</th><th>Details</th></tr></thead>
              <tbody>{events.map((e) => (
                <tr key={e.id}><td className="num whitespace-nowrap text-ink-3">{e.ts.slice(11, 19)}</td><td className="whitespace-nowrap font-medium">{e.type}</td>
                  <td className="text-[12px] text-ink-2 font-mono break-all">{JSON.stringify(e.payload).slice(0, 260)}</td></tr>))}</tbody>
            </table>
          </div>
        </Section>
      )}
    </div>
  );
}

function Trace({ tr }: { tr: any }) {
  const m = tr.match || {};
  const card = tr.card;
  const j = card?.judge;
  const traceBy: Record<string, any> = {};
  (tr.graph.trace || []).forEach((t: any) => { traceBy[t.node] = t; });
  const paused = tr.graph.next.includes("ask_shopkeeper");
  return (
    <div className="space-y-5 min-w-0">
      <Section title="Bank name → khata name">
        <div className="flex flex-wrap items-center gap-3">
          <div className="rounded-xl bg-slate-50 px-4 py-3"><div className="h-eyebrow">UPI name</div>
            <div className="text-lg font-semibold">{tr.payment.payer_name || "(blank)"}</div>
            <div className="text-[12px] text-ink-3 num">{tr.payment.payer_vpa} · {inr(tr.payment.amount_paise)} · {tr.payment.app}</div></div>
          <ArrowRight className="text-ink-3" />
          <div className="rounded-xl bg-money-soft px-4 py-3"><div className="h-eyebrow">Proposed khata customer</div>
            <div className="text-lg font-semibold">{tr.proposed_khata_name ?? "— (ask the shopkeeper)"}</div>
            <div className="text-[12px] text-ink-2">{STAGE_LABEL[m.stage] ?? m.stage}</div></div>
        </div>
        <p className="text-[13px] text-ink-2 mt-3">Reason: {m.reason}</p>
        {m.payer_norm && <p className="text-[12px] text-ink-3 mt-1 font-mono">normalized: tokens={JSON.stringify(m.payer_norm.tokens)} initials={JSON.stringify(m.payer_norm.initials)} hints={JSON.stringify(m.payer_norm.hints)}</p>}
        {m.conflict && <p className="text-[12.5px] text-trust mt-1">Guard: {m.conflict}, so it's not auto-proposed.</p>}
      </Section>

      {m.candidates?.length > 0 && (
        <Section title="Candidates" sub={`Only customers with open udhaar. Confident if top ≥ ${tr.thresholds.confident} and ≥ ${tr.thresholds.margin} ahead; below ${tr.thresholds.min} = no match; otherwise ambiguous → LLM.`}>
          <table className="tbl"><thead><tr><th>Khata name</th><th className="w-[40%]">Score</th><th>Open udhaar</th><th>Notes</th></tr></thead>
            <tbody>{m.candidates.map((c: any) => (
              <tr key={c.customer_id}>
                <td className="font-medium">{c.khata_name}</td>
                <td><div className="flex items-center gap-2"><div className="flex-1 h-2 rounded-full bg-slate-100 relative">
                  <div className="absolute inset-y-0 left-0 rounded-full bg-s1" style={{ width: `${Math.min(100, (c.score / 110) * 100)}%` }} />
                  <div className="absolute -top-1 -bottom-1 w-px bg-ink-3" style={{ left: `${(tr.thresholds.confident / 110) * 100}%` }} title="confident threshold" />
                </div><span className="num text-[13px] w-10 text-right">{c.score}</span></div></td>
                <td className="num">{c.open_amounts.map(inr).join(", ")}</td>
                <td className="text-[12px] text-ink-2">{c.notes.join(", ")}</td>
              </tr>))}</tbody>
          </table>
        </Section>
      )}

      {m.llm && (
        <Section title={`LLM call · ${m.llm.provider}`} sub={`${m.llm.latency_ms} ms · ~${m.llm.prompt_tokens_est} prompt tokens · answer must be one of the candidate ids`}>
          {m.llm.error && <p className="text-[12.5px] text-ink-2 mb-3">Fallback path: <span className="font-mono">{m.llm.error}</span></p>}
          <div className="h-eyebrow mb-2">Few-shot examples sent (this shop's confirmed matches = in-context learning)</div>
          {m.few_shot?.length ? (
            <table className="tbl"><thead><tr><th>Bank name</th><th>Khata name</th><th>Label</th></tr></thead>
              <tbody>{m.few_shot.map((e: any, i: number) => <tr key={i}><td>{e.payer_name}</td><td>{e.khata_name}</td><td>{e.label}</td></tr>)}</tbody></table>
          ) : <p className="text-[13px] text-ink-3">None yet for this shop.</p>}
        </Section>
      )}

      {j && (
        <Section title="Judge: a second model checks the first" sub="Runs on every card before it's shown.">
          <div className="grid sm:grid-cols-2 gap-3">
            <Verdict ok={j.stage1.ok} title="Stage 1 · deterministic (always runs)"
              text={j.stage1.ok ? "₹ amounts equal the ledger · customer exists with open udhaar · no phone number or full UPI ID · no sensitive words"
                : j.stage1.problems.join("; ")} />
            <Verdict ok={j.stage2.available ? j.stage2.numbers_match && j.stage2.fair_and_polite : null}
              title={`Stage 2 · LLM judge (${j.stage2.provider})`}
              text={j.stage2.available ? `numbers_match=${j.stage2.numbers_match} · fair_and_polite=${j.stage2.fair_and_polite} · ${j.stage2.reason}` : j.stage2.reason} />
          </div>
          <div className="mt-3 text-[13px]"><span className="text-ink-3">Shown:</span> <b>{j.source === "llm_rephrase" ? "LLM rephrase" : "template"}</b> — {j.shown_reason}</div>
          <div className="mt-2 rounded-xl bg-slate-50 px-4 py-3 text-[14px]">{card.body}</div>
          {card.template_body && card.template_body !== card.body && <div className="text-[12px] text-ink-3 mt-1">Template was: {card.template_body}</div>}
        </Section>
      )}

      <Section title="LangGraph workflow" sub={paused ? "Paused at interrupt() — waiting for the shopkeeper's tap. No ledger write has happened."
        : card?.decision ? `Resumed with Command(resume=${JSON.stringify(card.decision)})` : "Finished."}>
        <div className="flex flex-wrap items-center gap-1.5">
          {NODES.map((n, i) => {
            const done = traceBy[n];
            const isPause = n === "ask_shopkeeper" && paused;
            return (
              <div key={n} className="flex items-center gap-1.5">
                <div className={cx("rounded-lg px-2.5 py-1.5 text-[12px] font-mono border",
                  isPause ? "border-trust bg-trust-soft text-trust" : done ? "border-money/40 bg-money-soft text-[#0b6b3d]" : "border-slate-200 text-ink-3")}>
                  <span className="inline-flex items-center gap-1">{isPause ? <PauseCircle size={13} /> : done ? <CheckCircle2 size={13} /> : <CircleDashed size={13} />}{n}</span>
                  {done && !isPause && <div className="text-[10.5px] opacity-70">{done.result ?? ""}{done.ms ? ` · ${done.ms} ms` : ""}</div>}
                </div>
                {i < NODES.length - 1 && <ArrowRight size={13} className="text-ink-3" />}
              </div>
            );
          })}
        </div>
        <p className="text-[12px] text-ink-3 mt-3">Card status: <b>{card?.status ?? "—"}</b>. Resuming twice never writes twice: the card is marked decided and the ledger is idempotent on the payment ID.</p>
      </Section>
    </div>
  );
}

function Verdict({ ok, title, text }: { ok: boolean | null; title: string; text: string }) {
  return (
    <div className={cx("rounded-xl border p-3", ok === true ? "border-money/40 bg-money-soft/50" : ok === false ? "border-red-200 bg-red-50" : "border-slate-200 bg-slate-50")}>
      <div className="flex items-center gap-1.5 font-medium text-[13.5px]">
        {ok === true ? <CheckCircle2 size={16} className="text-money" /> : ok === false ? <XCircle size={16} className="text-red-600" /> : <MinusCircle size={16} className="text-ink-3" />}
        {title}</div>
      <p className="text-[12.5px] text-ink-2 mt-1">{text}</p>
    </div>
  );
}

function Internals({ d }: { d: any }) {
  const hr = d.hidden_regulars;
  const fc = d.forecast;
  return (
    <div className="grid xl:grid-cols-2 gap-5 items-start">
      <Section title="Hidden regulars" sub={`Rule: no credit on record, ≥ ${d.rule.min_payments_90d} payments in 90 days, paid in the last ${d.rule.max_recency_days} days, trust score ≥ ${hr.threshold.toFixed(3)} (picked on validation shops). The model never sees names, group, gender or location.`}>
        {hr.status === "need_more_data" && <p className="text-ink-2">Need about 4 weeks of payments to suggest anyone.</p>}
        {hr.items.map((it: any) => (
          <div key={it.payer_ref} className="rounded-xl border border-slate-200 p-4 mb-3">
            <div className="flex items-center justify-between">
              <div><div className="font-semibold">{it.display_name}</div><div className="text-[12px] text-ink-3 num">{it.payer_vpa}</div></div>
              <div className="text-right"><div className="text-[22px] font-bold num">{it.score.toFixed(3)}</div><div className="text-[11px] text-ink-3">trust score</div></div>
            </div>
            <div className="relative h-2 rounded-full bg-slate-100 mt-3">
              <div className="absolute inset-y-0 left-0 rounded-full bg-trust" style={{ width: `${it.score * 100}%` }} />
              <div className="absolute -top-1 -bottom-1 w-0.5 bg-ink" style={{ left: `${hr.threshold * 100}%` }} title="threshold" />
            </div>
            <div className="flex flex-wrap gap-1.5 mt-3">{it.reasons.map((r: string) => <span key={r} className="chip bg-trust-soft text-trust">{r}</span>)}</div>
            <p className="text-[11.5px] text-ink-3 mt-2">Reasons = top positive contributions from LightGBM <code>pred_contrib</code>, only shown when the statement is true.</p>
            <table className="tbl mt-2"><tbody>{Object.entries(it.features).map(([k, v]) => (
              <tr key={k}><td className="font-mono text-[12px]">{k}</td><td className="num text-right">{v === null ? "never had credit" : String(v)}</td></tr>))}</tbody></table>
          </div>
        ))}
        {hr.near_misses?.length > 0 && <p className="text-[12.5px] text-ink-3">Passed the rule but below the threshold: {hr.near_misses.map((n: any) => `${n.display_name} (${n.score})`).join(", ")}</p>}
      </Section>
      {fc && fc.status === "ok" && (
        <Section title="Repayment forecast" sub={`p7 = chance each open udhaar comes back within 7 days. Expected = Σ p7 × amount = ${inr(fc.expected_exact_paise)}. Range = 10th–90th percentile of ${d.mc.draws} seeded Monte Carlo draws with a shared weekly shock (sd ${d.mc.shock_sd}, logit scale).`}>
          <table className="tbl"><thead><tr><th>Customer</th><th>Owes</th><th>Age</th><th className="w-[35%]">p7</th></tr></thead>
            <tbody>{fc.items.map((it: any) => (
              <tr key={it.customer_id}><td>{it.khata_name}</td><td className="num">{inr(it.amount_paise)}</td><td className="num text-ink-3">{it.age_days}d</td>
                <td><div className="flex items-center gap-2"><div className="flex-1 h-2 rounded-full bg-slate-100"><div className="h-2 rounded-full bg-sky" style={{ width: pct(it.p7) }} /></div>
                  <span className="num text-[12px] w-9 text-right">{pct(it.p7)}</span></div></td></tr>))}</tbody></table>
        </Section>
      )}
    </div>
  );
}
