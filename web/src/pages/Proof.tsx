import { useEffect, useState } from "react";
import {
  Bar, BarChart, CartesianGrid, LabelList, Legend, Line, LineChart, ReferenceLine, ResponsiveContainer, Scatter, ScatterChart,
  Tooltip, XAxis, YAxis, ZAxis,
} from "recharts";
import { api, pct, signedPct } from "../lib";

const C1 = "#2a78d6", C2 = "#eb6834", C3 = "#1baf7a", GRID = "#e5e7eb", AX = "#64748b";
const axis = { stroke: AX, fontSize: 12, tickLine: false, axisLine: { stroke: GRID } };

function Stat({ label, value, sub }: { label: string; value: string; sub?: string }) {
  return (
    <div className="rounded-xl bg-slate-50 px-4 py-3">
      <div className="text-[12px] text-ink-3">{label}</div>
      <div className="text-[24px] font-bold tracking-tight num">{value}</div>
      {sub && <div className="text-[11.5px] text-ink-3 mt-0.5">{sub}</div>}
    </div>
  );
}

function Block({ n, title, children }: { n: number; title: string; children: React.ReactNode }) {
  return (
    <section className="panel panel-pad space-y-4">
      <h2 className="text-[19px] font-bold tracking-tight"><span className="text-ink-3 mr-2 num">{n}</span>{title}</h2>
      {children}
    </section>
  );
}

const tipStyle = { borderRadius: 12, border: "1px solid #e2e8f0", fontSize: 12.5, boxShadow: "0 4px 16px rgba(15,23,42,.08)" };

export default function Proof() {
  const [r, setR] = useState<any>(null);
  useEffect(() => { api.reports().then(setR); }, []);
  if (!r) return <div className="text-ink-3">Loading reports…</div>;
  const { bias: be, sweep: sw, trust: tm, forecast: fm } = r;

  const NAMES: [string, string][] = [["shopkeeper", "Shopkeeper's own choices"], ["model_a", "Model A: learns his yes/no"], ["model_b", "Model B: learns repayments"]];
  const barData = be ? NAMES.map(([k, n]) => ({ who: n, "In-group": be[k].A.rec_rate, "Out-group": be[k].B.rec_rate, nA: be[k].A.n_reliable, nB: be[k].B.n_reliable })) : [];
  const sweepData = sw ? sw.levels.map((lv: any) => ({ proxy: lv.proxy_smd, mult: lv.ticket_mult, a: lv.gap_a, b: lv.gap_b, s: lv.gap_shopkeeper })) : [];
  const defaultProxy = sw?.levels.find((lv: any) => lv.ticket_mult === sw.default_ticket_mult)?.proxy_smd;
  const cal = tm ? tm.calibration.filter((c: any) => c.n) : [];

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-bold tracking-tight">Proof</h1>
        <p className="text-ink-2 text-[14px] mt-1 max-w-3xl">Every number here comes from a real run on seeded synthetic data (files in <code>reports/</code>). Nothing is rounded up or picked.</p>
      </div>

      {be && (
        <Block n={1} title="Trained on the shopkeeper's choices vs trained on repayments">
          <div className="rounded-xl bg-sky-soft text-[#123b6d] px-4 py-3 text-[14.5px] leading-relaxed">{be.caption}</div>
          <div className="h-[340px]">
            <ResponsiveContainer>
              <BarChart data={barData} barGap={2} barCategoryGap="28%" margin={{ top: 24, right: 8, left: 0, bottom: 0 }}>
                <CartesianGrid vertical={false} stroke={GRID} />
                <XAxis dataKey="who" {...axis} />
                <YAxis {...axis} tickFormatter={(v) => pct(v)} domain={[0, (max: number) => Math.min(1, Math.ceil((max + 0.05) * 10) / 10)]} />
                <Tooltip contentStyle={tipStyle} cursor={{ fill: "rgba(148,163,184,.12)" }}
                  formatter={(v: number, name: string, p: any) => [`${pct(v, 1)} of ${name === "In-group" ? p.payload.nA : p.payload.nB} reliable customers`, name]} />
                <Legend verticalAlign="top" align="left" iconType="circle" wrapperStyle={{ fontSize: 13, paddingBottom: 8 }} />
                {[["In-group", C1], ["Out-group", C2]].map(([k, c]) => (
                  <Bar key={k} dataKey={k} isAnimationActive={false} fill={c} radius={[4, 4, 0, 0]} stroke="#fff" strokeWidth={2}>
                    <LabelList dataKey={k} position="top" formatter={(v: number) => pct(v)} style={{ fill: "#475569", fontSize: 12 }} />
                  </Bar>
                ))}
              </BarChart>
            </ResponsiveContainer>
          </div>
          <p className="text-[12.5px] text-ink-3">Share of <b>truly reliable</b> customers ({be.setup.truly_reliable_definition}, known only because the data is synthetic) who get
            recommended, on {be.setup.test_shops} held-out shops, each recommending its top {pct(be.setup.top_k_share_per_shop)}. The group is an audit label only: never a feature.</p>
          <div className="overflow-x-auto">
            <table className="tbl">
              <thead><tr><th></th><th>In-group</th><th>Out-group</th><th>Gap</th><th>95% CI of gap (bootstrap by shop)</th><th>Repayment AUC</th></tr></thead>
              <tbody>{NAMES.map(([k, n]) => (
                <tr key={k}><td className="font-medium">{n}</td><td className="num">{pct(be[k].A.rec_rate, 1)}</td><td className="num">{pct(be[k].B.rec_rate, 1)}</td>
                  <td className="num font-semibold">{signedPct(be[k].gap_A_minus_B)}</td>
                  <td className="num">{be[k].gap_95ci_bootstrap_by_shop ? `[${signedPct(be[k].gap_95ci_bootstrap_by_shop[0])}, ${signedPct(be[k].gap_95ci_bootstrap_by_shop[1])}]` : "—"}</td>
                  <td className="num">{be.repayment_auc[k] ?? "—"}</td></tr>))}</tbody>
            </table>
          </div>
          <p className="text-[12.5px] text-ink-3">Oracle AUC (the true synthetic repayment probability): {be.repayment_auc.oracle_f_r}. Precision of recommended:
            Model A {pct(be.precision_of_recommended.model_a, 1)}, Model B {pct(be.precision_of_recommended.model_b, 1)}.</p>

          {sw && (
            <div className="pt-2 border-t border-slate-100">
              <h3 className="font-semibold text-[16px] mt-3">How much bias gets copied depends on how strongly behaviour hints at the group</h3>
              <p className="text-[13px] text-ink-2 mt-1 max-w-3xl">Neither model sees the group. A model trained on the shopkeeper's yes/no can only copy his bias through a proxy. Here that's basket
                size, which in-group customers have slightly bigger (a documented generator choice, unrelated to repayment). We swept the proxy's strength and averaged {sw.seeds.length} seeds.
                Every level is shown.</p>
              <div className="h-[320px] mt-3">
                <ResponsiveContainer>
                  <LineChart data={sweepData} margin={{ top: 10, right: 16, left: 0, bottom: 18 }}>
                    <CartesianGrid stroke={GRID} vertical={false} />
                    <XAxis dataKey="proxy" type="number" domain={["dataMin", "dataMax"]} {...axis} tickFormatter={(v) => v.toFixed(1)}
                      label={{ value: "Proxy strength (standardized basket-size difference between groups)", position: "bottom", offset: 2, fill: AX, fontSize: 12 }} />
                    <YAxis {...axis} tickFormatter={(v) => signedPct(v, 0)} />
                    <ReferenceLine y={0} stroke="#94a3b8" strokeDasharray="4 3" />
                    {defaultProxy != null && <ReferenceLine x={defaultProxy} stroke="#94a3b8" label={{ value: "app's world", fill: AX, fontSize: 11, position: "insideTopRight" }} />}
                    <Tooltip contentStyle={tipStyle} labelFormatter={(v) => `Proxy strength ${Number(v).toFixed(2)}`} formatter={(v: number, n: string) => [signedPct(v), n]} />
                    <Legend verticalAlign="top" align="left" iconType="circle" wrapperStyle={{ fontSize: 13, paddingBottom: 8 }} />
                    <Line isAnimationActive={false} dataKey="a" name="Model A: learns his yes/no" stroke={C2} strokeWidth={2} dot={{ r: 4, strokeWidth: 2, stroke: "#fff", fill: C2 }} />
                    <Line isAnimationActive={false} dataKey="b" name="Model B: learns repayments" stroke={C1} strokeWidth={2} dot={{ r: 4, strokeWidth: 2, stroke: "#fff", fill: C1 }} />
                    <Line isAnimationActive={false} dataKey="s" name="Shopkeeper's own choices" stroke={C3} strokeWidth={2} dot={{ r: 4, strokeWidth: 2, stroke: "#fff", fill: C3 }} />
                  </LineChart>
                </ResponsiveContainer>
              </div>
              <p className="text-[12.5px] text-ink-3">y = in-group minus out-group recommendation rate among truly reliable customers. The real-world proxy strength is unknown: a pilot measures it.</p>
            </div>
          )}
        </Block>
      )}

      {tm && (
        <Block n={2} title="Trust model on held-out shops">
          <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
            <Stat label="ROC-AUC" value={String(tm.roc_auc)} sub="shops never seen in training" />
            <Stat label="Oracle ceiling" value={String(tm.oracle_auc_ceiling)} sub="best possible in this synthetic world" />
            <Stat label="Brier score" value={String(tm.brier)} sub={`base-rate guess: ${tm.brier_baseline_prevalence}`} />
            <Stat label="Threshold" value={String(tm.threshold)} sub={`validation precision ${tm.threshold_val_precision} (target ${pct(r.trust_target_precision)})`} />
          </div>
          <p className="text-[13px] text-ink-2">Label: {tm.label}. Trained on {tm.train_rows} outcomes from {tm.train_shops} shops (the shopkeepers' credit customers plus the random ₹100 exploration arm),
            tested on {tm.test_rows} from {tm.test_shops} other shops. At the threshold, among test customers with no credit history: {tm.test_cold_start_selected} selected,
            {" "}{pct(tm.test_cold_start_precision)} repaid on time (base rate {pct(tm.test_cold_start_base_rate)}).</p>
          <div className="h-[300px] max-w-[560px]">
            <ResponsiveContainer>
              <ScatterChart margin={{ top: 10, right: 16, left: 0, bottom: 18 }}>
                <CartesianGrid stroke={GRID} />
                <XAxis type="number" dataKey="mean_predicted" domain={[0, 1]} {...axis} tickFormatter={(v) => pct(v)} name="Predicted"
                  label={{ value: "Predicted chance of on-time repayment", position: "bottom", offset: 2, fill: AX, fontSize: 12 }} />
                <YAxis type="number" dataKey="observed_rate" domain={[0, 1]} {...axis} tickFormatter={(v) => pct(v)} name="Observed" />
                <ZAxis range={[90, 90]} />
                <ReferenceLine segment={[{ x: 0, y: 0 }, { x: 1, y: 1 }]} stroke="#94a3b8" strokeDasharray="4 3" />
                <Tooltip contentStyle={tipStyle} formatter={(v: number, n: string) => [pct(v, 1), n]} />
                <Scatter isAnimationActive={false} data={cal} fill={C1} stroke="#fff" strokeWidth={2} name="Calibration bins" />
              </ScatterChart>
            </ResponsiveContainer>
          </div>
          <p className="text-[12.5px] text-ink-3">Calibration on held-out shops (10 bins; dashed line = perfect). Bins with fewer customers are noisier.</p>
        </Block>
      )}

      {fm && (
        <Block n={3} title="Repayment forecast">
          <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
            <Stat label="p7 ROC-AUC" value={String(fm.roc_auc)} />
            <Stat label="80% range coverage" value={pct(fm.backtest_coverage_80)} sub={`${fm.backtest_shop_weeks} held-out shop-weeks`} />
            <Stat label="…without shared shock" value={pct(fm.backtest_coverage_80_without_shared_shock)} />
            <Stat label="Mean abs. error" value={`₹${Math.round(fm.backtest_mean_abs_error_rupees).toLocaleString("en-IN")}`} sub={`avg open total ₹${Math.round(fm.backtest_mean_open_total_rupees).toLocaleString("en-IN")}`} />
          </div>
          <p className="text-[13px] text-ink-2">Coverage above 80% means the range is conservative (wider than it needs to be) in this synthetic world. Said honestly rather than tuned away.</p>
        </Block>
      )}

      {(r.real_retail || r.fairness_external || r.matcher_metrics) && (
        <Block n={4} title="Checks on real public data">
          <p className="text-[13px] text-ink-2">The kirana demo is synthetic. Separately, each method was checked on real public data. These are <b>not</b> kirana repayments.</p>
          {r.real_retail && <p className="text-[14px]"><b>Behaviour features on UCI Online Retail II</b> (real UK retail invoices; label = buys again within 90 days, not repayment):
            ROC-AUC {r.real_retail.model.roc_auc} vs recency-only baseline {r.real_retail.baseline_recency.roc_auc}; PR-AUC {r.real_retail.model.pr_auc};
            Brier {r.real_retail.model.brier}; {r.real_retail.n_customers_test} test customers, split by customer.</p>}
          {r.fairness_external && <p className="text-[14px]"><b>Fairness audit on UCI Default of Credit Card Clients</b> (real, Taiwan 2005; sex and age used only as audit groups):
            equal-opportunity difference by sex {r.fairness_external.by_sex.equal_opportunity_difference}, by age band {r.fairness_external.by_age.equal_opportunity_difference}
            {" "}(AUC {r.fairness_external.roc_auc}). This checks the audit method; it has no shopkeeper decisions, so it doesn't replicate the Model A vs B experiment.</p>}
          {r.matcher_metrics && <p className="text-[14px]"><b>Name matcher on {r.matcher_metrics.n_pairs} labelled name pairs</b> (documented Indian spelling variation, incl. hard negatives):
            precision at auto-match {r.matcher_metrics.precision_auto}, false-match rate {r.matcher_metrics.false_match_rate}, recall {r.matcher_metrics.recall_auto}.</p>}
        </Block>
      )}

      <Block n={(r.real_retail || r.fairness_external || r.matcher_metrics) ? 5 : 4} title="What the field study found (context, not our data)">
        <ul className="list-disc pl-5 space-y-1.5 text-[14px] text-ink-2">
          {["in_group_favouritism", "random_borrowers", "revisits", "owner_lending", "credit_customers_share_of_revenue", "hours_chasing"].map((k) => <li key={k}>{r.facts[k]}</li>)}
        </ul>
        <p className="text-[12.5px] text-ink-3">Source: {r.facts.study}. We used published findings only, not the study's data.</p>
      </Block>
    </div>
  );
}
