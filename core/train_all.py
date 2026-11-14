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
