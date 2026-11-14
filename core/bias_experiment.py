"""Bias experiment (plan P3 step 1): approvals-trained vs repayments-trained.

Same synthetic shops, same behaviour features (no group, no names; prior_ontime_rate excluded because it is NaN
exactly when the shopkeeper never gave credit, i.e. it would leak his decision).
  Model A  label = the shopkeeper's past decision (offered credit yes/no)       -> trained on all customers
  Model B  label = actual repayment outcome (credit customers + exploration arm) -> trained on observed outcomes
Evaluation on HELD-OUT shops with a fixed top-k budget per shop:
  - recommendation rate among truly reliable customers, by audit group (equal-opportunity view)
  - repayment AUC (against every held-out customer's would-be repayment, known only because data is synthetic)
The audit group is used ONLY here, for auditing. It is never a model feature.
Honesty: whatever comes out is reported. The caption is generated from the numbers, not written in advance.
"""
from __future__ import annotations

import numpy as np
import pandas as pd
from sklearn.metrics import roc_auc_score

import config
from core import trust_model
from core.features import BEHAVIOUR_FEATURES, build

TOP_K_SHARE = 0.15            # each shop can recommend 15% of its customers
RELIABLE_F = 0.85             # "truly reliable" = true on-time probability >= 85% (synthetic ground truth)


def _topk_flags(df: pd.DataFrame, score_col: str) -> pd.Series:
    flags = pd.Series(False, index=df.index)
    for _, g in df.groupby("shop_id"):
        k = max(1, int(round(TOP_K_SHARE * len(g))))
        flags.loc[g[score_col].nlargest(k).index] = True
    return flags


def _rates(df: pd.DataFrame, flag_col: str) -> dict:
    rel = df[df["f_ontime"] >= RELIABLE_F]
    out = {}
    for g in ("A", "B"):
        sub = rel[rel["grp"] == g]
        out[g] = {"n_reliable": int(len(sub)), "rec_rate": round(float(sub[flag_col].mean()), 4)}
    out["gap_A_minus_B"] = round(out["A"]["rec_rate"] - out["B"]["rec_rate"], 4)
    out["ratio_A_over_B"] = round(out["A"]["rec_rate"] / out["B"]["rec_rate"], 3) if out["B"]["rec_rate"] else None
    return out


def _bootstrap_gap(df: pd.DataFrame, flag_col: str, n: int = 300, seed: int = config.SEED) -> list[float]:
    rng = np.random.default_rng(seed)
    shops = df["shop_id"].unique()
    rel = df[df["f_ontime"] >= RELIABLE_F]
    by_shop = {s: g for s, g in rel.groupby("shop_id")}
    gaps = []
    for _ in range(n):
        pick = rng.choice(shops, size=len(shops), replace=True)
        sample = pd.concat([by_shop[s] for s in pick if s in by_shop])
        a = sample.loc[sample["grp"] == "A", flag_col].mean()
        b = sample.loc[sample["grp"] == "B", flag_col].mean()
        gaps.append(a - b)
    return [round(float(np.percentile(gaps, 2.5)), 4), round(float(np.percentile(gaps, 97.5)), 4)]


def run(world: dict) -> dict:
    cust = world["customers"]
    X = build(world["payments"], world["cutoff"], world["credit"])[BEHAVIOUR_FEATURES]
    df = cust.join(X, how="inner")
    tr, te = df[df["is_test"] == 0], df[df["is_test"] == 1].copy()

    model_a = trust_model.fit(tr[BEHAVIOUR_FEATURES], tr["offered"].values)
    obs = tr[(tr["offered"] == 1) | (tr["explored"] == 1)]
    model_b = trust_model.fit(obs[BEHAVIOUR_FEATURES], obs["would_repay"].values)

    te["score_a"] = model_a.predict_proba(te[BEHAVIOUR_FEATURES])[:, 1]
    te["score_b"] = model_b.predict_proba(te[BEHAVIOUR_FEATURES])[:, 1]
    te["rec_a"] = _topk_flags(te, "score_a")
    te["rec_b"] = _topk_flags(te, "score_b")
    te["shopkeeper"] = te["offered"] == 1

    res = {
        "setup": {"train_shops": int(tr["shop_id"].nunique()), "test_shops": int(te["shop_id"].nunique()),
                  "model_a_rows": int(len(tr)), "model_b_rows": int(len(obs)), "test_customers": int(len(te)),
                  "top_k_share_per_shop": TOP_K_SHARE, "truly_reliable_definition": f"true on-time probability >= {RELIABLE_F}",
                  "features": BEHAVIOUR_FEATURES},
        "shopkeeper": _rates(te, "shopkeeper"),
        "model_a": _rates(te, "rec_a"),
        "model_b": _rates(te, "rec_b"),
        "repayment_auc": {"model_a": round(float(roc_auc_score(te["would_repay"], te["score_a"])), 4),
                          "model_b": round(float(roc_auc_score(te["would_repay"], te["score_b"])), 4),
                          "oracle_f_r": round(float(roc_auc_score(te["would_repay"], te["f_ontime"])), 4)},
        "precision_of_recommended": {"model_a": round(float(te.loc[te["rec_a"], "would_repay"].mean()), 4),
                                     "model_b": round(float(te.loc[te["rec_b"], "would_repay"].mean()), 4)},
    }
    res["model_a"]["gap_95ci_bootstrap_by_shop"] = _bootstrap_gap(te, "rec_a")
    res["model_b"]["gap_95ci_bootstrap_by_shop"] = _bootstrap_gap(te, "rec_b")

    # proxy check: which behaviour features differ by group? (standardised mean difference)
    proxy = {}
    for f in BEHAVIOUR_FEATURES:
        a, b = df.loc[df["grp"] == "A", f], df.loc[df["grp"] == "B", f]
        sd = df[f].std()
        proxy[f] = round(float((a.mean() - b.mean()) / sd), 3) if sd and not np.isnan(sd) else None
    gain_a = dict(zip(BEHAVIOUR_FEATURES, model_a.booster_.feature_importance("gain")))
    gain_b = dict(zip(BEHAVIOUR_FEATURES, model_b.booster_.feature_importance("gain")))
    tot_a, tot_b = sum(gain_a.values()), sum(gain_b.values())
    res["proxy_check"] = {
        "std_mean_diff_A_minus_B": proxy,
        "ticket_share_of_gain": {"model_a": round(float(gain_a["median_ticket_paise"] / tot_a), 3),
                                 "model_b": round(float(gain_b["median_ticket_paise"] / tot_b), 3)},
        "note": ("Neither model sees the group. In this synthetic world in-group customers buy slightly bigger "
                 "baskets (a documented generator choice, unrelated to repayment), so basket size is a proxy a model "
                 "CAN use to copy group bias."),
    }

    # caption from the numbers (never pre-written)
    ga, gb = res["model_a"]["gap_A_minus_B"], res["model_b"]["gap_A_minus_B"]
    auc_a, auc_b = res["repayment_auc"]["model_a"], res["repayment_auc"]["model_b"]
    ci_b = res["model_b"]["gap_95ci_bootstrap_by_shop"]
    copies = ga > 0.02 and res["model_a"]["gap_95ci_bootstrap_by_shop"][0] > 0
    b_fair = ci_b[0] <= 0 <= ci_b[1] or abs(gb) < 0.02
    parts = []
    parts.append("Trained on the shopkeeper's choices, the model copies his bias" if copies
                 else "Trained on the shopkeeper's choices, the model did NOT show a clear group gap in this run")
    parts.append(f"(reliable in-group customers recommended {res['model_a']['A']['rec_rate']:.0%} vs "
                 f"{res['model_a']['B']['rec_rate']:.0%}).")
    parts.append("Trained on who actually repays, it doesn't" if b_fair else
                 f"Trained on repayments, a gap of {gb:+.1%} remains (investigate)")
    parts.append(f"({res['model_b']['A']['rec_rate']:.0%} vs {res['model_b']['B']['rec_rate']:.0%}),")
    parts.append(("and it predicts repayment better" if auc_b > auc_a + 0.005 else
                  "and it predicts repayment about as well" if abs(auc_b - auc_a) <= 0.005 else
                  "but it predicts repayment worse") + f" (AUC {auc_b:.2f} vs {auc_a:.2f}).")
    res["caption"] = " ".join(parts)
    res["summary"] = {"gap_a": ga, "gap_b": gb, "auc_a": auc_a, "auc_b": auc_b, "copies_bias": copies, "b_fair": b_fair}
    return res
