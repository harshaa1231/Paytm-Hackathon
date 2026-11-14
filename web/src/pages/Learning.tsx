import { useEffect, useState } from "react";
import { Bar, BarChart, CartesianGrid, Legend, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { RefreshCcw, ShieldCheck } from "lucide-react";
import { api, pct } from "../lib";

const STAGES: [string, string, string][] = [
  ["vpa_memory", "VPA memory", "#2a78d6"], ["fuzzy_confident", "Name match (RapidFuzz)", "#eb6834"], ["needs_llm", "Needs LLM (ambiguous)", "#1baf7a"],
  ["asked_pick", "Shopkeeper picks", "#eda100"], ["missed", "Missed (shown as purchase)", "#e87ba4"],
];
const tipStyle = { borderRadius: 12, border: "1px solid #e2e8f0", fontSize: 12.5 };

export default function Learning() {
  const [r, setR] = useState<any>(null);
  const [busy, setBusy] = useState(false);
  const [last, setLast] = useState<any>(null);
  const [err, setErr] = useState<string | null>(null);
  useEffect(() => { api.reports().then(setR); }, []);

  const retrain = async () => {
    setBusy(true); setErr(null);
    try {
      const out = await api.retrain();
      setLast(out);
      setR((x: any) => ({ ...x, learning_state: { ...(x?.learning_state || {}), history: out.history } }));
    } catch (e: any) {
      setErr(e.status === 401 ? "Admin key needed on this deployment." : e.message);
    } finally { setBusy(false); }
  };

  if (!r) return <div className="text-ink-3">Loading…</div>;
  const weeks = r.matcher_replay?.weeks ?? [];
  const data = weeks.map((w: any) => Object.fromEntries([["week", `Week ${w.week}`], ...STAGES.map(([k]) => [k, w[k] / w.repayments]), ["n", w.repayments]]));
  const hist = r.learning_state?.history ?? [];

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-bold tracking-tight">Learning loop</h1>
        <p className="text-ink-2 text-[14px] mt-1">Two things get better with use, and neither learns from the shopkeeper's yes/no on credit.</p>
      </div>

      <section className="panel panel-pad space-y-4">
        <h2 className="text-[19px] font-bold tracking-tight"><span className="text-ink-3 mr-2">1</span>The name matcher remembers</h2>
        <p className="text-[13.5px] text-ink-2 max-w-3xl">Four synthetic weeks of repayments at a new shop. Each week the shopkeeper confirms who paid; confirmed UPI IDs go into VPA memory and
          confirmed name pairs become few-shot examples for the LLM.</p>
        <div className="h-[320px]">
          <ResponsiveContainer>
            <BarChart data={data} stackOffset="expand" barCategoryGap="30%" margin={{ top: 8, right: 8, left: 0, bottom: 0 }}>
              <CartesianGrid vertical={false} stroke="#e5e7eb" />
              <XAxis dataKey="week" stroke="#64748b" fontSize={12} tickLine={false} />
              <YAxis stroke="#64748b" fontSize={12} tickLine={false} tickFormatter={(v) => pct(v)} />
              <Tooltip contentStyle={tipStyle} cursor={{ fill: "rgba(148,163,184,.12)" }} formatter={(v: number, n: string) => [pct(v), n]} />
              <Legend verticalAlign="top" align="left" iconType="circle" wrapperStyle={{ fontSize: 13, paddingBottom: 8 }} />
              {STAGES.map(([k, label, c], i) => (
                <Bar key={k} isAnimationActive={false} dataKey={k} name={label} stackId="s" fill={c} stroke="#fff" strokeWidth={2} radius={i === STAGES.length - 1 ? [4, 4, 0, 0] : 0} />
              ))}
            </BarChart>
          </ResponsiveContainer>
        </div>
        <div className="overflow-x-auto">
          <table className="tbl">
            <thead><tr><th>Week</th><th>Repayments</th>{STAGES.map(([, l]) => <th key={l}>{l}</th>)}<th>Wrong customer proposed</th><th>Auto-resolved</th></tr></thead>
            <tbody>{weeks.map((w: any) => (
              <tr key={w.week}><td>{w.week}</td><td className="num">{w.repayments}</td>{STAGES.map(([k]) => <td key={k} className="num">{w[k]}</td>)}
                <td className="num">{w.false_auto}</td><td className="num font-semibold">{pct(w.auto_resolved_share)}</td></tr>))}</tbody>
          </table>
        </div>
        <p className="text-[12.5px] text-ink-3">{r.matcher_replay?.note} Every card still needs the shopkeeper's tap. A guard stops auto-proposals when the name points to one
          customer but the amount exactly matches another's udhaar (a family member paying).</p>
      </section>

      <section className="panel panel-pad space-y-4">
        <div className="flex flex-wrap items-center gap-3 justify-between">
          <h2 className="text-[19px] font-bold tracking-tight"><span className="text-ink-3 mr-2">2</span>The trust model retrains on repayments</h2>
          <button onClick={retrain} disabled={busy} className="btn btn-lg btn-navy"><RefreshCcw size={17} className={busy ? "animate-spin" : ""} />
            {busy ? "Retraining…" : "Retrain on this week's repayments"}</button>
        </div>
        <div className="flex items-center gap-2 rounded-xl bg-money-soft text-[#0b6b3d] px-4 py-3 text-[14px] font-medium">
          <ShieldCheck size={18} /> Learns from repayments only — never from the shopkeeper's yes/no.</div>
        {err && <p className="text-red-700 text-sm">{err}</p>}
        {last && (
          <div className="grid grid-cols-3 gap-3">
            {[["Training outcomes", "train_rows", 0], ["AUC (same held-out shops)", "roc_auc", 4], ["Brier", "brier", 4]].map(([l, k, d]) => {
              const b = last.before?.[k as string] ?? 0, a = last.after[k as string];
              const delta = a - b;
              return (<div key={k as string} className="rounded-xl bg-slate-50 px-4 py-3"><div className="text-[12px] text-ink-3">{l}</div>
                <div className="text-[24px] font-bold num">{typeof a === "number" ? a.toFixed(d as number) : a}</div>
                <div className="text-[12px] num text-ink-2">{delta >= 0 ? "+" : ""}{delta.toFixed(d as number)} vs before</div></div>);
            })}
          </div>
        )}
        <table className="tbl">
          <thead><tr><th>Step</th><th>What was added</th><th>Training outcomes</th><th>This shop's outcomes</th><th>AUC</th><th>Brier</th></tr></thead>
          <tbody>{hist.map((h: any) => (
            <tr key={h.step}><td>{h.step}</td><td>{h.label}</td><td className="num">{h.train_rows}</td><td className="num">{h.shop_outcomes_used}</td>
              <td className="num">{h.roc_auc}</td><td className="num">{h.brier}</td></tr>))}</tbody>
        </table>
        <p className="text-[12.5px] text-ink-3">Each step adds the next batch of repayment outcomes (more pilot shops reporting back) plus this shop's own closed udhaar, then scores the same
          held-out shops. Reset demo on the Shopkeeper page restores the seeded model.</p>
      </section>
    </div>
  );
}
