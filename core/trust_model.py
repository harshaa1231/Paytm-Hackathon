"""Trust model: LightGBM on payment behaviour, trained on REPAYMENT OUTCOMES ONLY (plan P2 step 2).

Training rows = customers who actually got credit: the shopkeeper's own credit customers PLUS the random
exploration arm (small Rs100 starter offers). The exploration arm is how the system learns about people the
shopkeeper never trusted - it corrects the selection bias in his own history.
Split by SHOP (held-out shops never seen in training). Threshold chosen on validation folds (GroupKFold by shop)
for ~90% precision among people who never had credit (that's who the hidden-regular card is for).
Never trained on the shopkeeper's yes/no.
"""
from __future__ import annotations

import json

import numpy as np
import pandas as pd

import config
from core import lgb_compat  # noqa: F401  (macOS libomp shim)
from core.features import FEATURES, build

import lightgbm as lgb  # noqa: E402
from sklearn.metrics import brier_score_loss, roc_auc_score  # noqa: E402
from sklearn.model_selection import GroupKFold  # noqa: E402

PARAMS = dict(n_estimators=250, learning_rate=0.03, num_leaves=15, min_child_samples=40, subsample=0.8,
              subsample_freq=1, colsample_bytree=0.9, reg_lambda=1.0, random_state=config.SEED, verbose=-1)

MODEL_FILE = "trust_model.txt"
META_FILE = "trust_meta.json"

# plain-word reasons, chosen from the top positive contributions (and only if the statement is true)
def _reason(feat: str, v: float) -> str | None:
    if pd.isna(v):
        return None
    if feat == "active_weeks_share":
        return "comes every week" if v >= 0.95 else (f"comes most weeks ({v:.0%})" if v >= 0.6 else None)
    if feat == "n_pay_90d":
        return f"paid {int(v)} times in the last 90 days" if v >= 6 else None
    if feat == "gap_std_days":
        return "visits on a steady schedule" if v <= 3 else None
    if feat == "recency_days":
        return "paid in the last few days" if v <= 5 else (f"last paid {int(v)} days ago" if v <= 14 else None)
    if feat == "tenure_days":
        m = int(v // 30)
        return f"a customer for {m} months" if m >= 2 else None
    if feat == "max_gap_days":
        return f"never away more than {int(np.ceil(v))} days" if v <= 21 else None
    if feat == "prior_ontime_rate":
        return f"repaid {v:.0%} of past udhaar on time" if v >= 0.7 else None
    if feat == "median_ticket_paise":
        return None   # basket size is not a reason we say out loud
    return None


def fit(X: pd.DataFrame, y: np.ndarray, params: dict | None = None) -> lgb.LGBMClassifier:
    m = lgb.LGBMClassifier(**(params or PARAMS))
    m.fit(X, y)
    return m


def calibration_table(y: np.ndarray, p: np.ndarray, bins: int = 10) -> list[dict]:
    edges = np.linspace(0, 1, bins + 1)
    idx = np.clip(np.digitize(p, edges[1:-1]), 0, bins - 1)
    out = []
    for b in range(bins):
        m = idx == b
        out.append({"bin": f"{edges[b]:.1f}-{edges[b + 1]:.1f}", "n": int(m.sum()),
                    "mean_predicted": round(float(p[m].mean()), 3) if m.any() else None,
                    "observed_rate": round(float(y[m].mean()), 3) if m.any() else None})
    return out


def pick_threshold(y: np.ndarray, p: np.ndarray, target: float = config.TRUST_TARGET_PRECISION, min_n: int = 30) -> dict:
    """Lowest threshold whose precision (on validation rows) reaches the target with at least min_n selected."""
    order = np.argsort(-p)
    ys, ps = y[order], p[order]
    prec = np.cumsum(ys) / np.arange(1, len(ys) + 1)
    best = None
    for k in range(min_n, len(ys) + 1):
        if prec[k - 1] >= target:
            best = k
    if best is None:   # target unreachable: take the most precise reasonably-sized set and say so
        k = int(np.argmax(prec[min_n - 1:]) + min_n)
        return {"threshold": float(ps[k - 1]), "precision": float(prec[k - 1]), "selected": k, "target_met": False}
    return {"threshold": float(ps[best - 1]), "precision": float(prec[best - 1]), "selected": best, "target_met": True}


def auc_ci_by_shop(y: np.ndarray, p: np.ndarray, shops: np.ndarray, n: int = 300, seed: int = config.SEED) -> list[float]:
    """95% bootstrap interval of ROC-AUC, resampling held-out SHOPS (the unit of generalisation)."""
    rng = np.random.default_rng(seed)
    uniq = np.unique(shops)
    idx = {s: np.where(shops == s)[0] for s in uniq}
    aucs = []
    for _ in range(n):
        take = np.concatenate([idx[s] for s in rng.choice(uniq, size=len(uniq), replace=True)])
        if len(np.unique(y[take])) == 2:
            aucs.append(roc_auc_score(y[take], p[take]))
    return [round(float(np.percentile(aucs, 2.5)), 4), round(float(np.percentile(aucs, 97.5)), 4)]


def training_frame(world: dict) -> pd.DataFrame:
    """One row per customer who actually got credit at the cutoff (historical credit + exploration arm)."""
    cust = world["customers"]
    feats = build(world["payments"], world["cutoff"], world["credit"])
    df = cust.join(feats, how="inner")
    df = df[(df["offered"] == 1) | (df["explored"] == 1)].copy()
    df["label"] = df["would_repay"].astype(int)
    return df


def train(world: dict, batches: tuple[int, ...] = (1,)) -> dict:
    df = training_frame(world)
    tr = df[(df["is_test"] == 0) & (df["batch"].isin(batches))]
    te = df[df["is_test"] == 1]

    # out-of-fold predictions on training shops -> threshold (validation by shop)
    oof = np.full(len(tr), np.nan)
    gkf = GroupKFold(n_splits=5)
    for a, b in gkf.split(tr[FEATURES], tr["label"], groups=tr["shop_id"]):
        m = fit(tr.iloc[a][FEATURES], tr.iloc[a]["label"].values)
        oof[b] = m.predict_proba(tr.iloc[b][FEATURES])[:, 1]
    cold = tr["prior_ontime_rate"].isna().values
    thr = pick_threshold(tr["label"].values[cold], oof[cold])

    model = fit(tr[FEATURES], tr["label"].values)
    p = model.predict_proba(te[FEATURES])[:, 1]
    y = te["label"].values
    cold_te = te["prior_ontime_rate"].isna().values
    sel = cold_te & (p >= thr["threshold"])
    metrics = {
        "label": "repaid on time (within 14 days) - repayment outcomes only",
        "train_rows": int(len(tr)), "train_shops": int(tr["shop_id"].nunique()), "batches": list(batches),
        "test_rows": int(len(te)), "test_shops": int(te["shop_id"].nunique()),
        "test_prevalence": round(float(y.mean()), 3),
        "roc_auc": round(float(roc_auc_score(y, p)), 4),
        "roc_auc_ci95": auc_ci_by_shop(y, p, te["shop_id"].values),
        "brier": round(float(brier_score_loss(y, p)), 4),
        "brier_baseline_prevalence": round(float(brier_score_loss(y, np.full_like(p, tr["label"].mean()))), 4),
        "calibration": calibration_table(y, p),
        "threshold": round(thr["threshold"], 4), "threshold_val_precision": round(thr["precision"], 3),
        "threshold_target_met": thr["target_met"],
        "test_cold_start_selected": int(sel.sum()),
        "test_cold_start_precision": round(float(y[sel].mean()), 3) if sel.any() else None,
        "test_cold_start_base_rate": round(float(y[cold_te].mean()), 3) if cold_te.any() else None,
        "feature_importance_gain": dict(sorted(zip(FEATURES, [round(float(x), 1) for x in
                                        model.booster_.feature_importance("gain")]), key=lambda kv: -kv[1])),
    }
    return {"model": model, "metrics": metrics, "threshold": thr["threshold"]}


# ------------------------------------------------------------------ persistence + inference
def save(model: lgb.LGBMClassifier, metrics: dict, threshold: float) -> None:
    config.MODELS_DIR.mkdir(parents=True, exist_ok=True)
    model.booster_.save_model(str(config.MODELS_DIR / MODEL_FILE))
    (config.MODELS_DIR / META_FILE).write_text(json.dumps({"threshold": threshold, "features": FEATURES,
                                                           "batches": metrics.get("batches"),
                                                           "metrics": {k: metrics[k] for k in ("roc_auc", "brier", "train_rows")}},
                                                          indent=1))


_booster_cache: dict = {}


def load() -> lgb.Booster:
    path = config.MODELS_DIR / MODEL_FILE
    key = (str(path), path.stat().st_mtime)
    if key not in _booster_cache:
        _booster_cache.clear()
        _booster_cache[key] = lgb.Booster(model_file=str(path))
    return _booster_cache[key]


def predict(X: pd.DataFrame, booster: lgb.Booster | None = None) -> np.ndarray:
    b = booster or load()
    return b.predict(X[FEATURES].astype(float))


def explain(X: pd.DataFrame, booster: lgb.Booster | None = None, top: int = 2) -> list[list[str]]:
    """Top positive SHAP-style contributions (pred_contrib=True) turned into plain, TRUE statements."""
    b = booster or load()
    contrib = b.predict(X[FEATURES].astype(float), pred_contrib=True)[:, :-1]   # last column = bias
    out = []
    for i in range(len(X)):
        order = np.argsort(-contrib[i])
        reasons = []
        for j in order:
            if contrib[i, j] <= 0:
                break
            r = _reason(FEATURES[j], X.iloc[i][FEATURES[j]])
            if r:
                reasons.append(r)
            if len(reasons) >= top:
                break
        out.append(reasons)
    return out
