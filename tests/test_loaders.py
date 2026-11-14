"""External-data adapters, tested OFFLINE on tiny made-up fixtures (never the real downloads)."""
import numpy as np
import pandas as pd
import pytest

from core.features import BEHAVIOUR_FEATURES, payment_features
from data.loaders import TAIWAN_AUDIT_ONLY, TAIWAN_FEATURES, clean_online_retail, clean_taiwan, repeat_label
from experiments import real_retail


def retail_fixture():
    return pd.DataFrame({
        "Invoice": ["1001", "1001", "C1002", "1003", "1004", "1005", "1006"],
        "Quantity": [2, 1, -1, 3, 0, 1, 2],
        "InvoiceDate": pd.to_datetime(["2011-01-05 10:00", "2011-01-05 10:00", "2011-01-06 09:00", "2011-02-01 09:00", "2011-02-02 09:00",
                                       "2011-07-01 09:00", "2011-02-10 09:00"]),
        "Price": [1.5, 2.25, 1.0, 1.0, 5.0, 4.0, 1.0],
        "Customer ID": [12345.0, 12345.0, 12345.0, 12345.0, 12345.0, 12345.0, np.nan],
    })


def test_retail_cleaning_steps_and_units():
    inv, q = clean_online_retail(retail_fixture())
    assert q["rows_raw"] == 7 and q["after_drop_missing_customer"] == 6
    assert q["after_drop_cancellations"] == 5 and q["after_drop_nonpositive_qty_or_price"] == 4
    assert q["invoices"] == 3                                   # two lines of invoice 1001 collapse into one visit
    first = inv[inv["invoice"] == "1001"].iloc[0]
    assert first["amount_minor"] == 525 and first["currency"] == "GBP"   # 2*1.50 + 1*2.25 = £5.25 -> 525 pence
    assert inv["payer_key"].str.startswith("uci_retail:").all()          # namespaced ids


def test_retail_label_is_future_only_and_features_past_only():
    inv, _ = clean_online_retail(retail_fixture())
    cut = pd.Timestamp("2011-06-01", tz="UTC")
    assert repeat_label(inv, cut).to_dict() == {"uci_retail:12345": 1}
    f = payment_features(inv.rename(columns={"amount_minor": "amount_paise"}), cut)
    assert f.loc["uci_retail:12345", "recency_days"] > 0           # the July invoice is not used as a feature


def test_split_is_by_customer():
    tr, te = real_retail.split_customers(pd.Index([f"uci_retail:{i}" for i in range(100)]))
    assert not tr & te and len(tr) + len(te) == 100


def taiwan_fixture(n=400, seed=0):
    rng = np.random.default_rng(seed)
    d = {"ID": np.arange(1, n + 1), "LIMIT_BAL": rng.integers(10, 500, n) * 1000, "SEX": rng.integers(1, 3, n),
         "AGE": rng.integers(21, 70, n), "PAY_0": rng.integers(-1, 3, n)}
    for i in (2, 3, 4, 5, 6):
        d[f"PAY_{i}"] = rng.integers(-1, 3, n)
    for i in range(1, 7):
        d[f"BILL_AMT{i}"] = rng.integers(0, 50_000, n)
        d[f"PAY_AMT{i}"] = rng.integers(0, 5_000, n)
    df = pd.DataFrame(d)
    df["default payment next month"] = (rng.random(n) < 0.15 + 0.15 * (df["PAY_0"] > 0)).astype(int)
    return df


def test_taiwan_audit_attributes_are_not_features():
    df = clean_taiwan(taiwan_fixture())
    assert not set(TAIWAN_AUDIT_ONLY) & set(TAIWAN_FEATURES)
    assert df["client_key"].str.startswith("taiwan_credit:").all()
    assert set(df["sex_group"]) == {"male", "female"}
    assert (df["repaid"] == 1 - df["default payment next month"]).all()


def test_fairness_audit_runs_on_fixture(tmp_path, monkeypatch):
    pytest.importorskip("fairlearn")       # validation-layer extra (requirements-validation.txt)
    from experiments import fairness_external
    monkeypatch.setattr(fairness_external, "REPORTS", tmp_path)
    out = fairness_external.run(clean_taiwan(taiwan_fixture(600)))
    assert {"groups", "equal_opportunity_difference"} <= set(out["by_sex"])
    assert sum(g["count"] for g in out["by_age"]["groups"]) == out["n_test"]
    assert "SEX" not in out["features"] and "AGE" not in out["features"]


def test_behaviour_features_unit_agnostic():
    assert "median_ticket_paise" in BEHAVIOUR_FEATURES   # name says paise; for UCI data the values are pence (documented)
