"""Train every model on the synthetic world and write every report. Called by data/generate.py.

Reports (all numbers shown in the app/README come from these files, from real runs):
  reports/metrics.json            trust model on held-out shops (AUC, Brier, calibration, threshold)
  reports/forecast_metrics.json   p7 model + Monte Carlo backtest coverage
  reports/bias_experiment.json    Model A (shopkeeper's choices) vs Model B (repayments)
  reports/learning_matcher.json   4-week matcher replay
"""
from __future__ import annotations

import json
import time

import config
from core import forecast, trust_model, world

INITIAL_BATCHES = (1,)          # repayments observed so far; the Learning loop page adds batches 2, 3


def write_report(name: str, obj: dict) -> None:
    config.REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    (config.REPORTS_DIR / name).write_text(json.dumps(obj, indent=1, default=str, ensure_ascii=False))


def oracle_auc(w: dict) -> float:
    from sklearn.metrics import roc_auc_score
    df = trust_model.training_frame(w)
    te = df[df["is_test"] == 1]
    return round(float(roc_auc_score(te["label"], te["f_ontime"])), 4)


SWEEP_MULTS = (1.0, 1.3, 1.6, 2.0, 2.5)
SWEEP_SEEDS = (42, 43, 44)


def bias_sweep() -> dict:
    """Sensitivity analysis: how much bias does each model copy as the group proxy (basket size) gets stronger?
    Every level and seed is reported; nothing is picked."""
    import tempfile
    from pathlib import Path

    import numpy as np

    from core import bias_experiment
    from data.generate import make_training_world
    tmp = Path(tempfile.mkdtemp())
    runs = []
    for mult in SWEEP_MULTS:
        for seed in SWEEP_SEEDS:
            p = tmp / f"w_{mult}_{seed}.db"
            make_training_world(seed=seed, path=p, overrides={"ingroup_ticket_mult": mult}, quiet=True)
            r = bias_experiment.run(world.load_world(str(p)))
            world.load_world.cache_clear()
            p.unlink()
            runs.append({"ticket_mult": mult, "seed": seed,
                         "proxy_smd": r["proxy_check"]["std_mean_diff_A_minus_B"]["median_ticket_paise"],
                         "gap_shopkeeper": r["shopkeeper"]["gap_A_minus_B"], "gap_a": r["model_a"]["gap_A_minus_B"],
                         "gap_b": r["model_b"]["gap_A_minus_B"], "auc_a": r["repayment_auc"]["model_a"],
                         "auc_b": r["repayment_auc"]["model_b"]})
    levels = []
    for mult in SWEEP_MULTS:
        rs = [r for r in runs if r["ticket_mult"] == mult]
        levels.append({"ticket_mult": mult, **{k: round(float(np.mean([r[k] for r in rs])), 4)
                                               for k in ("proxy_smd", "gap_shopkeeper", "gap_a", "gap_b", "auc_a", "auc_b")},
                       "gap_a_min": min(r["gap_a"] for r in rs), "gap_a_max": max(r["gap_a"] for r in rs),
                       "gap_b_min": min(r["gap_b"] for r in rs), "gap_b_max": max(r["gap_b"] for r in rs)})
    return {"seeds": list(SWEEP_SEEDS), "default_ticket_mult": config.WORLD["ingroup_ticket_mult"],
            "levels": levels, "runs": runs,
            "note": "gap = recommendation rate among truly reliable customers, in-group minus out-group (top 15% per shop)."}


def run() -> dict:
    t0 = time.time()
    w = world.load_world()
    tr = trust_model.train(w, batches=INITIAL_BATCHES)
    tr["metrics"]["oracle_auc_ceiling"] = oracle_auc(w)
    tr["metrics"]["oracle_note"] = ("AUC of the TRUE synthetic repayment probability f(r): the best any model could do "
                                    "in this synthetic world. Real-world AUC is unknown until a pilot.")
    trust_model.save(tr["model"], tr["metrics"], tr["threshold"])
    write_report("metrics.json", tr["metrics"])
    print(f"[trust] AUC={tr['metrics']['roc_auc']} (oracle {tr['metrics']['oracle_auc_ceiling']}) "
          f"Brier={tr['metrics']['brier']} thr={tr['threshold']:.3f}")

    fc = forecast.train(w)
    forecast.save(fc["model"])
    write_report("forecast_metrics.json", fc["metrics"])
    print(f"[p7] AUC={fc['metrics']['roc_auc']} coverage80={fc['metrics']['backtest_coverage_80']} "
          f"(without shared shock {fc['metrics']['backtest_coverage_80_without_shared_shock']})")

    try:
        from core import bias_experiment
        be = bias_experiment.run(w)
        write_report("bias_experiment.json", be)
        print(f"[bias] {be['summary']}")
        sw = bias_sweep()
        write_report("bias_sweep.json", sw)
        print("[bias sweep] " + " | ".join(f"x{lv['ticket_mult']}: A {lv['gap_a']:+.3f} B {lv['gap_b']:+.3f}" for lv in sw["levels"]))
    except ImportError:
        pass
    try:
        from core import learning
        lm = learning.replay_matcher()
        write_report("learning_matcher.json", lm)
        learning.init_state()
        print(f"[learning] auto-resolved by week: {[wk['auto_resolved_share'] for wk in lm['weeks']]}")
    except ImportError:
        pass
    print(f"[train_all] {time.time() - t0:.1f}s")
    return {"trust": tr["metrics"], "forecast": fc["metrics"]}


if __name__ == "__main__":
    run()
