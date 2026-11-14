"""Real-data check #2: does our fairness AUDIT method work on real credit data?

Data: UCI Default of Credit Card Clients (Taiwan, 2005; CC BY 4.0; 30,000 clients).
Model: LightGBM on repayment-history features only (LIMIT_BAL, PAY_*, BILL_AMT*, PAY_AMT*).
SEX and AGE (banded) are used ONLY as audit groups, never as features.
Decision: "select" a client if predicted chance of repaying >= a threshold chosen on validation folds for ~90%
precision (the same rule the app uses for hidden regulars).
Audit per group: count, selection rate, TPR (selected | repaid), FPR (selected | defaulted), equal-opportunity
difference (max - min TPR across groups). Uses fairlearn's MetricFrame.
Say it accurately: this is an external real-data check of the AUDIT. The data has no shopkeeper decisions, so it
does NOT replicate the Model A vs Model B experiment (that stays synthetic).

    python experiments/download.py && python experiments/fairness_external.py
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from fairlearn.metrics import MetricFrame, false_positive_rate, selection_rate, true_positive_rate  # noqa: E402
from sklearn.metrics import roc_auc_score  # noqa: E402
from sklearn.model_selection import KFold  # noqa: E402

from core import trust_model  # noqa: E402
from data.loaders import TAIWAN_FEATURES, clean_taiwan  # noqa: E402

RAW = ROOT / "experiments" / "raw" / "uci_default_credit_card_taiwan"
REPORTS = ROOT / "reports"
SEED = 42


def audit(y: np.ndarray, sel: np.ndarray, groups: pd.Series) -> dict:
    mf = MetricFrame(metrics={"selection_rate": selection_rate, "tpr": true_positive_rate, "fpr": false_positive_rate,
                              "count": lambda yt, yp: len(yt)},
                     y_true=y, y_pred=sel, sensitive_features=groups)
    rows = []
    for g, r in mf.by_group.iterrows():
        rows.append({"group": str(g), "count": int(r["count"]), "selection_rate": round(float(r["selection_rate"]), 4),
                     "tpr": round(float(r["tpr"]), 4), "fpr": round(float(r["fpr"]), 4)})
    tprs = [r["tpr"] for r in rows]
    return {"groups": rows, "equal_opportunity_difference": round(max(tprs) - min(tprs), 4)}


def run(df: pd.DataFrame | None = None) -> dict:
    if df is None:
        raw = pd.read_excel(RAW / "default of credit card clients.xls", header=1)
        df = clean_taiwan(raw)
    rng = np.random.default_rng(SEED)
    idx = rng.permutation(len(df))
    n_test = int(0.3 * len(df))
    te, tr = df.iloc[idx[:n_test]], df.iloc[idx[n_test:]]          # each row is one client: split by client
    assert not set(te["client_key"]) & set(tr["client_key"])

    oof = np.zeros(len(tr))
    for a, b in KFold(5, shuffle=True, random_state=SEED).split(tr):
        m = trust_model.fit(tr.iloc[a][TAIWAN_FEATURES], tr.iloc[a]["repaid"].values)
        oof[b] = m.predict_proba(tr.iloc[b][TAIWAN_FEATURES])[:, 1]
    thr = trust_model.pick_threshold(tr["repaid"].values, oof, target=0.90)
    model = trust_model.fit(tr[TAIWAN_FEATURES], tr["repaid"].values)
    p = model.predict_proba(te[TAIWAN_FEATURES])[:, 1]
    sel = (p >= thr["threshold"]).astype(int)
    y = te["repaid"].values
    res = {
        "dataset": "UCI Default of Credit Card Clients (Taiwan, 2005)", "n_train": int(len(tr)), "n_test": int(len(te)),
        "features": TAIWAN_FEATURES, "audit_only_attributes": ["SEX", "AGE (banded)"],
        "decision_rule": f"select if P(repay) >= {thr['threshold']:.4f} (validation precision {thr['precision']:.3f})",
        "roc_auc": round(float(roc_auc_score(y, p)), 4), "test_repay_rate": round(float(y.mean()), 4),
        "precision_of_selected": round(float(y[sel == 1].mean()), 4) if sel.any() else None,
        "by_sex": audit(y, sel, te["sex_group"]), "by_age": audit(y, sel, te["age_band"]),
        "note": "External real-data check of the fairness AUDIT. No shopkeeper decisions in this data, so it does not "
                "replicate Model A vs Model B. 'Fair' here would need a judgement about acceptable differences; we only report them.",
    }
    REPORTS.mkdir(exist_ok=True)
    (REPORTS / "fairness_external.json").write_text(json.dumps(res, indent=1))
    try:
        man = json.loads((REPORTS / "dataset_manifest.json").read_text())
        man["uci_default_credit_card_taiwan"].update({"rows_before_cleaning": int(len(df)), "rows_after_cleaning": int(len(df)),
                                                      "currency_units": "NT$ (as in source)", "split": "by client, 70/30, seed 42",
                                                      "limitations": ["Taiwan credit cards, 2005: not kirana udhaar.",
                                                                      "No shopkeeper decisions: checks the audit, not Model A vs B."]})
        (REPORTS / "dataset_manifest.json").write_text(json.dumps(man, indent=1))
    except (FileNotFoundError, KeyError):
        pass
    return res


if __name__ == "__main__":
    out = run()
    print(json.dumps({k: out[k] for k in ("roc_auc", "decision_rule", "precision_of_selected")}, indent=1))
    for k in ("by_sex", "by_age"):
        print(k, out[k]["equal_opportunity_difference"], out[k]["groups"])
