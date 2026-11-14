"""Real-data check #1: do our payment-behaviour features carry signal on real retail transactions?

Data: UCI Online Retail II (CC BY 4.0; 1,067,371 rows; UK online gift-ware retailer, many wholesale customers).
Features: core/features.py logic, computed only from invoices BEFORE the cutoff (2011-06-01).
Label: repeat_purchase_90d = bought again within 90 days after the cutoff.  THIS IS NOT REPAYMENT.
Split: by customer (no customer in both train and test). Time check: train at an earlier cutoff, test at the later one.
Money stays in pence (amount_minor); never converted to rupees.

    python experiments/download.py && python experiments/real_retail.py
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from sklearn.linear_model import LogisticRegression  # noqa: E402
from sklearn.metrics import average_precision_score, brier_score_loss, roc_auc_score  # noqa: E402

from core import trust_model  # noqa: E402
from core.features import BEHAVIOUR_FEATURES, payment_features  # noqa: E402
from data.loaders import clean_online_retail, repeat_label  # noqa: E402

RAW = ROOT / "experiments" / "raw" / "uci_online_retail_ii"
REPORTS = ROOT / "reports"
CUTOFF = pd.Timestamp("2011-06-01", tz="UTC")
EARLY_CUTOFF = pd.Timestamp("2011-03-01", tz="UTC")
SEED = 42


def load_lines() -> pd.DataFrame:
    pq = RAW / "online_retail_II.parquet"
    if pq.exists():
        return pd.read_parquet(pq)
    print("reading the Excel workbook once (takes a few minutes)...")
    sheets = pd.read_excel(RAW / "online_retail_II.xlsx", sheet_name=None, dtype={"Invoice": str, "StockCode": str})
    keep = ["Invoice", "Quantity", "InvoiceDate", "Price", "Customer ID"]     # Description etc. not needed
    lines = pd.concat([d[keep] for d in sheets.values()], ignore_index=True)
    lines["Invoice"] = lines["Invoice"].astype(str)
    lines.to_parquet(pq, index=False)
    return lines


def frame(inv: pd.DataFrame, cutoff: pd.Timestamp) -> pd.DataFrame:
    pay = inv.rename(columns={"amount_minor": "amount_paise"})       # feature code is unit-agnostic; units stay pence
    X = payment_features(pay, cutoff)[BEHAVIOUR_FEATURES]
    y = repeat_label(inv, cutoff).reindex(X.index).fillna(0).astype(int)
    return X.assign(label=y)


def split_customers(keys: pd.Index, test_share: float = 0.25, seed: int = SEED) -> tuple[set, set]:
    rng = np.random.default_rng(seed)
    k = np.array(sorted(keys))
    rng.shuffle(k)
    n = int(len(k) * test_share)
    return set(k[n:]), set(k[:n])


def evaluate(y, p) -> dict:
    return {"roc_auc": round(float(roc_auc_score(y, p)), 4), "pr_auc": round(float(average_precision_score(y, p)), 4),
            "brier": round(float(brier_score_loss(y, p)), 4)}


def run() -> dict:
    lines = load_lines()
    inv, quality = clean_online_retail(lines)
    df = frame(inv, CUTOFF)
    train_keys, test_keys = split_customers(df.index)
    assert not (train_keys & test_keys)
    tr, te = df[df.index.isin(train_keys)], df[df.index.isin(test_keys)]
    model = trust_model.fit(tr[BEHAVIOUR_FEATURES], tr["label"].values)
    p = model.predict_proba(te[BEHAVIOUR_FEATURES])[:, 1]
    base = LogisticRegression().fit(tr[["recency_days"]], tr["label"])
    pb = base.predict_proba(te[["recency_days"]])[:, 1]

    # time check: train on the earlier cutoff (train customers), score test customers at the later cutoff
    early = frame(inv, EARLY_CUTOFF)
    early_tr = early[early.index.isin(train_keys)]
    m_early = trust_model.fit(early_tr[BEHAVIOUR_FEATURES], early_tr["label"].values)
    p_time = m_early.predict_proba(te[BEHAVIOUR_FEATURES])[:, 1]

    res = {
        "dataset": "UCI Online Retail II (real UK retail invoices)", "label": "repeat_purchase_90d (bought again within 90 days) - NOT repayment",
        "cutoff": str(CUTOFF.date()), "features": BEHAVIOUR_FEATURES, "units": "pence (GBP minor units); never converted",
        "split": "by customer, 75/25, seed 42", "n_customers_train": int(len(tr)), "n_customers_test": int(len(te)),
        "prevalence": round(float(te["label"].mean()), 4),
        "model": evaluate(te["label"], p),
        "baseline_recency": evaluate(te["label"], pb),
        "time_check": {"trained_at_cutoff": str(EARLY_CUTOFF.date()), "scored_at_cutoff": str(CUTOFF.date()), **evaluate(te["label"], p_time)},
        "limitations": ["Online gift-ware retailer in the UK, many wholesale buyers: not a kirana.",
                        "Label is repeat purchase, not repayment: it validates that behaviour features carry signal, nothing more.",
                        "Invoice times treated as UTC; only day-level gaps matter for these features."],
    }
    REPORTS.mkdir(exist_ok=True)
    (REPORTS / "real_retail_metrics.json").write_text(json.dumps(res, indent=1))
    (REPORTS / "real_retail_data_quality.json").write_text(json.dumps(quality, indent=1))
    man = json.loads((REPORTS / "dataset_manifest.json").read_text())
    man["uci_online_retail_ii"].update({"rows_before_cleaning": quality["rows_raw"], "invoices_after_cleaning": quality["invoices"],
                                        "currency_units": "GBP pence", "split": res["split"], "limitations": res["limitations"]})
    (REPORTS / "dataset_manifest.json").write_text(json.dumps(man, indent=1))
    return res


if __name__ == "__main__":
    out = run()
    print(json.dumps({k: out[k] for k in ("prevalence", "model", "baseline_recency", "time_check", "n_customers_test")}, indent=1))
