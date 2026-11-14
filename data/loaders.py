"""Adapters for external data (plan 13 / 13b). Pure functions over DataFrames so tests run offline on tiny fixtures.

Rules: namespace every external ID ("uci_retail:12345", "taiwan_credit:12345") so they never collide with app IDs;
keep money in the source's own units (pence for UCI retail; NT$ for the Taiwan data); never convert to rupees.
Nothing here is imported by the app.
"""
from __future__ import annotations

import pandas as pd

TAIWAN_FEATURES = (["LIMIT_BAL"] + [f"PAY_{i}" for i in (0, 2, 3, 4, 5, 6)]
                   + [f"BILL_AMT{i}" for i in range(1, 7)] + [f"PAY_AMT{i}" for i in range(1, 7)])
TAIWAN_AUDIT_ONLY = ["SEX", "AGE"]          # audit groups ONLY, never features
TAIWAN_TARGET = "default payment next month"


def clean_online_retail(lines: pd.DataFrame) -> tuple[pd.DataFrame, dict]:
    """UCI Online Retail II line items -> one row per invoice (one invoice = one visit).

    Steps (row counts recorded after each): drop missing Customer ID; drop cancellations (Invoice starts with "C");
    drop Quantity <= 0 or Price <= 0; collapse to invoices.
    Returns (invoices[payer_key, invoice, ts, amount_minor, currency], data_quality).
    """
    q: dict = {"rows_raw": int(len(lines))}
    df = lines.rename(columns={"Customer ID": "customer_id", "InvoiceDate": "invoice_date", "Invoice": "invoice"})
    df = df[df["customer_id"].notna()]
    q["after_drop_missing_customer"] = int(len(df))
    df = df[~df["invoice"].astype(str).str.upper().str.startswith("C")]
    q["after_drop_cancellations"] = int(len(df))
    df = df[(df["Quantity"] > 0) & (df["Price"] > 0)]
    q["after_drop_nonpositive_qty_or_price"] = int(len(df))
    df = df.assign(line_minor=(df["Quantity"] * df["Price"] * 100).round().astype("int64"))
    inv = (df.groupby(["customer_id", "invoice"], as_index=False)
             .agg(ts=("invoice_date", "min"), amount_minor=("line_minor", "sum")))
    inv["payer_key"] = "uci_retail:" + inv["customer_id"].astype("int64").astype(str)
    inv["ts"] = pd.to_datetime(inv["ts"]).dt.tz_localize("UTC")     # source times are UK local; treated as UTC (hours don't matter here)
    inv["currency"] = "GBP"
    q["invoices"] = int(len(inv))
    q["customers"] = int(inv["payer_key"].nunique())
    return inv[["payer_key", "invoice", "ts", "amount_minor", "currency"]], q


def repeat_label(inv: pd.DataFrame, cutoff: pd.Timestamp, days: int = 90) -> pd.Series:
    """1 if the customer bought again within `days` after the cutoff. This is NOT repayment."""
    after = inv[(inv["ts"] >= cutoff) & (inv["ts"] < cutoff + pd.Timedelta(days=days))]
    return pd.Series(1, index=after["payer_key"].unique(), dtype=int)


def clean_taiwan(raw: pd.DataFrame) -> pd.DataFrame:
    """UCI Default of Credit Card Clients: second header row holds the names. Adds a namespaced id,
    `repaid` (= 1 - default) and an age band used only for auditing."""
    df = raw.copy()
    if "ID" not in df.columns and "Y" in df.columns:          # raw sheet read with the X1..X23 row as header
        df.columns = df.iloc[0]
        df = df.iloc[1:]
    df = df.rename(columns={"PAY_1": "PAY_0"})
    for c in TAIWAN_FEATURES + TAIWAN_AUDIT_ONLY + [TAIWAN_TARGET, "ID"]:
        df[c] = pd.to_numeric(df[c])
    df["client_key"] = "taiwan_credit:" + df["ID"].astype("int64").astype(str)
    df["repaid"] = 1 - df[TAIWAN_TARGET].astype(int)
    df["sex_group"] = df["SEX"].map({1: "male", 2: "female"})            # coding per the UCI documentation
    df["age_band"] = pd.cut(df["AGE"], [0, 29, 39, 49, 200], labels=["<30", "30-39", "40-49", "50+"]).astype(str)
    return df.reset_index(drop=True)
