"""What's coming back (plan P2 step 5).

p7 = probability each open udhaar is repaid within 7 days (a second small LightGBM on behaviour features +
udhaar age + amount; split by shop). Expected = sum(p7 x amount). Range = 10th-90th percentile of 2,000 seeded
Monte Carlo draws. Each draw adds a SHARED shock on the logit scale (a bad week or a festival moves everyone
together), because independent draws make the range unrealistically narrow.
"""
from __future__ import annotations

import json
import sqlite3

import numpy as np
import pandas as pd

import config
from core import lgb_compat  # noqa: F401
from core.features import DAY, credit_features, payment_features, shop_credit_df, shop_payments_df, to_cutoff
from core.money import round_to_hundred_rupees

import lightgbm as lgb  # noqa: E402
from sklearn.metrics import brier_score_loss, roc_auc_score  # noqa: E402

P7_FEATURES = ["age_days", "amount_paise", "prior_ontime_rate", "n_prior_credit", "n_pay_90d", "recency_days",
               "active_weeks_share", "gap_std_days", "tenure_days"]
MODEL_FILE = "p7_model.txt"
PARAMS = dict(n_estimators=200, learning_rate=0.04, num_leaves=15, min_child_samples=40, subsample=0.8,
              subsample_freq=1, colsample_bytree=0.9, random_state=config.SEED, verbose=-1)


# ------------------------------------------------------------------ Monte Carlo range
def _sigmoid(x):
    return 1 / (1 + np.exp(-x))


def simulate(p7: np.ndarray, amounts: np.ndarray, draws: int = config.MC_DRAWS, shock_sd: float = config.MC_SHOCK_SD,
             seed: int = config.SEED) -> dict:
    p7 = np.clip(np.asarray(p7, float), 1e-4, 1 - 1e-4)
    amounts = np.asarray(amounts, float)
    if len(p7) == 0:
        return {"expected": 0, "p10": 0, "p90": 0}
    rng = np.random.default_rng(seed)
    shock = rng.normal(0, shock_sd, size=(draws, 1))                       # shared by everyone in a draw
    p = _sigmoid(np.log(p7 / (1 - p7)) + shock)
    totals = (rng.random((draws, len(p7))) < p).astype(float) @ amounts
    return {"expected": float(p7 @ amounts), "p10": float(np.percentile(totals, 10)), "p90": float(np.percentile(totals, 90))}


# ------------------------------------------------------------------ training rows from the synthetic world
def snapshot_rows(world: dict, cutoffs: list) -> pd.DataFrame:
    credit = world["credit"]
    rows = []
    for c in cutoffs:
        c = to_cutoff(c)
        open_ = credit[(credit["given_at"] < c) & ~((credit["repaid_at"].notna()) & (credit["repaid_at"] <= c))
                       & ((c - credit["given_at"]) / DAY < 60)].copy()       # written off after 60 days
        if open_.empty:
            continue
        pf = payment_features(world["payments"], c)
        cf = credit_features(credit, c)
        open_ = open_.join(pf, on="payer_key").join(cf, on="payer_key")
        open_["age_days"] = (c - open_["given_at"]) / DAY
        open_["label"] = (open_["repaid_at"].notna() & (open_["repaid_at"] <= c + 7 * DAY)).astype(int)
        open_["cutoff"] = c
        rows.append(open_)
    df = pd.concat(rows, ignore_index=True)
    df["n_prior_credit"] = df["n_prior_credit"].fillna(0)
    test = world["customers"]["is_test"]
    df["is_test"] = df["payer_key"].map(test).astype(int)
    return df


def train(world: dict) -> dict:
    start, cutoff = world["start"], world["cutoff"]
    cutoffs = [start + pd.Timedelta(days=d) for d in range(60, int((cutoff - start) / DAY) + 1, 7)]
    df = snapshot_rows(world, cutoffs)
    tr, te = df[df["is_test"] == 0], df[df["is_test"] == 1]
    model = lgb.LGBMClassifier(**PARAMS).fit(tr[P7_FEATURES].astype(float), tr["label"].values)
    p = model.predict_proba(te[P7_FEATURES].astype(float))[:, 1]
    te = te.assign(p7=p)

    # backtest: per held-out shop and week, did the realised total fall inside the 80% range?
    hits, n, abs_err, totals = 0, 0, [], []
    for (shop, c), g in te.groupby(["shop_id", "cutoff"]):
        sim = simulate(g["p7"].values, g["amount_paise"].values, seed=config.SEED)
        realised = float((g["label"] * g["amount_paise"]).sum())
        hits += int(sim["p10"] <= realised <= sim["p90"])
        n += 1
        abs_err.append(abs(realised - sim["expected"]))
        totals.append(float(g["amount_paise"].sum()))
    indep_hits = 0
    for (shop, c), g in te.groupby(["shop_id", "cutoff"]):   # same backtest without the shared shock, for contrast
        sim = simulate(g["p7"].values, g["amount_paise"].values, shock_sd=0.0, seed=config.SEED)
        realised = float((g["label"] * g["amount_paise"]).sum())
        indep_hits += int(sim["p10"] <= realised <= sim["p90"])
    metrics = {
        "label": "open udhaar repaid within the next 7 days",
        "train_rows": int(len(tr)), "test_rows": int(len(te)), "test_prevalence": round(float(te["label"].mean()), 3),
        "roc_auc": round(float(roc_auc_score(te["label"], p)), 4), "brier": round(float(brier_score_loss(te["label"], p)), 4),
        "backtest_shop_weeks": n, "backtest_coverage_80": round(hits / n, 3) if n else None,
        "backtest_coverage_80_without_shared_shock": round(indep_hits / n, 3) if n else None,
        "backtest_mean_abs_error_rupees": round(float(np.mean(abs_err)) / 100, 0) if abs_err else None,
        "backtest_mean_open_total_rupees": round(float(np.mean(totals)) / 100, 0) if totals else None,
        "mc_draws": config.MC_DRAWS, "mc_shared_shock_sd_logit": config.MC_SHOCK_SD,
    }
    return {"model": model, "metrics": metrics}


def save(model) -> None:
    config.MODELS_DIR.mkdir(parents=True, exist_ok=True)
    model.booster_.save_model(str(config.MODELS_DIR / MODEL_FILE))


_cache: dict = {}


def load() -> lgb.Booster:
    path = config.MODELS_DIR / MODEL_FILE
    key = (str(path), path.stat().st_mtime)
    if key not in _cache:
        _cache.clear()
        _cache[key] = lgb.Booster(model_file=str(path))
    return _cache[key]


# ------------------------------------------------------------------ shop forecast (app)
def open_udhaar_features(conn: sqlite3.Connection, shop_id: str, as_of: str) -> pd.DataFrame:
    """One row per open udhaar with p7 features. Customer behaviour comes from the customer's confirmed VPAs."""
    c = to_cutoff(pd.Timestamp(as_of))
    credit = shop_credit_df(conn, shop_id)
    if credit.empty:
        return pd.DataFrame()
    rem = {r["id"]: r["rem"] for r in conn.execute(
        "SELECT u.id, u.amount_paise - COALESCE((SELECT SUM(a.amount_paise) FROM allocations a WHERE a.udhaar_id=u.id),0) AS rem "
        "FROM udhaar u WHERE u.shop_id=? AND u.status IN ('open','partial')", (shop_id,)).fetchall()}
    open_ = credit[credit["udhaar_id"].isin([k for k, v in rem.items() if v > 0])].drop_duplicates("udhaar_id").copy()
    if open_.empty:
        return pd.DataFrame()
    open_["amount_paise"] = open_["udhaar_id"].map(rem).astype(int)
    open_["age_days"] = (c - open_["given_at"]) / DAY
    # customer-level credit history (no VPA needed)
    hist = credit.drop_duplicates("udhaar_id")
    cf = credit_features(hist.rename(columns={"customer_id": "ck"}), c, key="ck")
    open_ = open_.join(cf, on="customer_id")
    # behaviour from the customer's confirmed VPAs (most active VPA)
    pf = payment_features(shop_payments_df(conn, shop_id), c)
    vmap = credit.dropna(subset=["payer_key"]).drop_duplicates(["customer_id", "payer_key"])
    best = {}
    for cid, g in vmap.groupby("customer_id"):
        keys = [k for k in g["payer_key"] if k in pf.index]
        if keys:
            best[cid] = max(keys, key=lambda k: pf.loc[k, "n_pay_90d"])
    beh = pd.DataFrame([pf.loc[best[cid]].to_dict() | {"customer_id": cid} for cid in best]) if best else pd.DataFrame(columns=["customer_id"])
    open_ = open_.merge(beh, on="customer_id", how="left")
    open_["n_prior_credit"] = open_["n_prior_credit"].fillna(0)
    for f in P7_FEATURES:
        if f not in open_:
            open_[f] = np.nan
    return open_


def shop_forecast(conn: sqlite3.Connection, shop_id: str, as_of: str) -> dict:
    rows = open_udhaar_features(conn, shop_id, as_of)
    if rows.empty:
        return {"status": "nothing", "total_paise": 0, "expected_paise": 0, "low_paise": 0, "high_paise": 0, "n_open": 0, "items": []}
    p7 = load().predict(rows[P7_FEATURES].astype(float))
    sim = simulate(p7, rows["amount_paise"].values)
    names = {r["id"]: r["khata_name"] for r in conn.execute("SELECT id, khata_name FROM customers WHERE shop_id=?", (shop_id,))}
    items = [{"customer_id": r.customer_id, "khata_name": names.get(r.customer_id, ""), "amount_paise": int(r.amount_paise),
              "age_days": round(float(r.age_days), 1), "p7": round(float(p), 3)}
             for r, p in zip(rows.itertuples(), p7)]
    items.sort(key=lambda x: -x["p7"] * x["amount_paise"])
    total = int(rows["amount_paise"].sum())
    cap = lambda v: min(total, max(0, round_to_hundred_rupees(v)))   # noqa: E731  (rounding must never exceed what is owed)
    return {"status": "ok", "total_paise": total,
            "expected_paise": cap(sim["expected"]),
            "low_paise": cap(sim["p10"]), "high_paise": cap(sim["p90"]),
            "expected_exact_paise": int(round(sim["expected"])), "n_open": len(items),
            "few": len(items) < config.FORECAST_FEW_ENTRIES, "items": items,
            "mc": {"draws": config.MC_DRAWS, "shock_sd": config.MC_SHOCK_SD, "seed": config.SEED}}


def load_metrics() -> dict:
    try:
        return json.loads((config.REPORTS_DIR / "forecast_metrics.json").read_text())
    except Exception:
        return {}
