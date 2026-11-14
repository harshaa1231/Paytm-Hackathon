"""Payment-behaviour features (plan P2 step 1).

Computed ONLY from payments strictly before a cutoff. No names, no group, no gender, no location.
Repayment payments (confirmed allocations) are excluded so features describe buying behaviour,
not the shopkeeper's past credit decisions. Identity = payer VPA ("payer_key").
"""
from __future__ import annotations

import sqlite3

import numpy as np
import pandas as pd

FEATURES = ["n_pay_90d", "active_weeks_share", "gap_std_days", "recency_days", "tenure_days",
            "median_ticket_paise", "max_gap_days", "prior_ontime_rate"]
# For the bias experiment: prior_ontime_rate is NaN exactly when the shopkeeper never gave credit,
# so it would leak his decision. Both models there use only buying behaviour.
BEHAVIOUR_FEATURES = [f for f in FEATURES if f != "prior_ontime_rate"]
DAY = pd.Timedelta(days=1)


def to_ts(s: pd.Series) -> pd.Series:
    return pd.to_datetime(s, format="ISO8601", utc=True)


def to_cutoff(c) -> pd.Timestamp:
    t = pd.Timestamp(c)
    return t.tz_localize("UTC") if t.tzinfo is None else t.tz_convert("UTC")


def payment_features(pay: pd.DataFrame, cutoff) -> pd.DataFrame:
    """pay: columns payer_key, ts (tz-aware), amount_paise. Returns one row per payer_key seen before cutoff."""
    cutoff = to_cutoff(cutoff)
    p = pay.loc[pay["ts"] < cutoff, ["payer_key", "ts", "amount_paise"]].sort_values(["payer_key", "ts"])
    cols = [f for f in FEATURES if f != "prior_ontime_rate"]
    if p.empty:
        return pd.DataFrame(columns=cols, dtype=float)
    g = p.groupby("payer_key", sort=False)
    first, last = g["ts"].min(), g["ts"].max()
    out = pd.DataFrame(index=first.index)
    out["tenure_days"] = (cutoff - first) / DAY
    out["recency_days"] = (cutoff - last) / DAY
    out["n_pay_90d"] = p.loc[p["ts"] >= cutoff - 90 * DAY].groupby("payer_key").size().reindex(out.index).fillna(0)
    week_idx = ((cutoff - p["ts"]) / DAY // 7).astype(int)
    active = week_idx.groupby(p["payer_key"]).nunique()
    weeks_seen = np.maximum(1, np.ceil(out["tenure_days"] / 7))
    out["active_weeks_share"] = (active.reindex(out.index) / weeks_seen).clip(upper=1.0)
    gaps = g["ts"].diff() / DAY
    gp = gaps.groupby(p["payer_key"])
    out["gap_std_days"] = gp.std(ddof=0).where(gp.count() >= 2)
    out["max_gap_days"] = gp.max()
    out["median_ticket_paise"] = g["amount_paise"].median()
    return out[cols].astype(float)


def credit_features(credit: pd.DataFrame | None, cutoff, key: str = "payer_key") -> pd.DataFrame:
    """credit: columns <key>, given_at, due_at, repaid_at (NaT if not repaid). Only episodes whose due date has
    passed by the cutoff count, and repaid_at is only compared with due_at (<= cutoff): no future leakage."""
    cutoff = to_cutoff(cutoff)
    if credit is None or credit.empty:
        return pd.DataFrame(columns=["prior_ontime_rate", "n_prior_credit"], dtype=float)
    c = credit.loc[credit["due_at"] <= cutoff]
    on_time = c["repaid_at"].notna() & (c["repaid_at"] <= c["due_at"])
    g = on_time.groupby(c[key])
    return pd.DataFrame({"prior_ontime_rate": g.mean().astype(float), "n_prior_credit": g.size().astype(float)})


def build(pay: pd.DataFrame, cutoff, credit: pd.DataFrame | None = None) -> pd.DataFrame:
    pf = payment_features(pay, cutoff)
    cf = credit_features(credit, cutoff)
    out = pf.join(cf[["prior_ontime_rate"]], how="left")
    return out[FEATURES]


# ------------------------------------------------------------------ app DB loaders (shop-scoped)
def shop_payments_df(conn: sqlite3.Connection, shop_id: str) -> pd.DataFrame:
    """SUCCESS UPI payments that are NOT confirmed repayments, keyed by payer VPA."""
    rows = conn.execute(
        "SELECT p.payer_vpa AS payer_key, p.payer_name, p.ts, p.amount_paise FROM payments p "
        "WHERE p.shop_id=? AND p.status='SUCCESS' AND p.payer_vpa<>'' "
        "AND COALESCE((SELECT SUM(a.amount_paise) FROM allocations a WHERE a.txn_id=p.txn_id),0) <= 0",
        (shop_id,)).fetchall()
    df = pd.DataFrame([dict(r) for r in rows], columns=["payer_key", "payer_name", "ts", "amount_paise"])
    df["ts"] = to_ts(df["ts"]) if not df.empty else pd.Series(dtype="datetime64[ns, UTC]")
    return df


def shop_credit_df(conn: sqlite3.Connection, shop_id: str) -> pd.DataFrame:
    """Udhaar history per customer, with every VPA confirmed for that customer (payer_key may be NaN)."""
    rows = conn.execute(
        "SELECT u.customer_id, u.id AS udhaar_id, u.given_at, u.due_at, u.amount_paise, u.status, "
        "CASE WHEN u.status='closed' THEN u.closed_at END AS repaid_at, v.payer_vpa AS payer_key "
        "FROM udhaar u LEFT JOIN vpa_map v ON v.shop_id=u.shop_id AND v.customer_id=u.customer_id WHERE u.shop_id=?",
        (shop_id,)).fetchall()
    df = pd.DataFrame([dict(r) for r in rows],
                      columns=["customer_id", "udhaar_id", "given_at", "due_at", "amount_paise", "status", "repaid_at", "payer_key"])
    for c in ("given_at", "due_at", "repaid_at"):
        df[c] = to_ts(df[c]) if not df.empty else pd.Series(dtype="datetime64[ns, UTC]")
    return df
