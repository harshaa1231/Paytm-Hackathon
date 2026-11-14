"""Hidden regulars (plan P2 step 3): who to trust next.

Rule: never had credit AND >= 12 payments in 90 days AND paid within 14 days AND trust score >= threshold
(threshold picked on validation shops for ~90% precision). Top 3 per shop, sorted by score.
A "No" from the shopkeeper is logged as a decision and NEVER used as a training label.
"""
from __future__ import annotations

import hashlib
import sqlite3

import pandas as pd

import config
from core import trust_model
from core.cards import display_upi_name
from core.features import FEATURES, build, shop_credit_df, shop_payments_df, to_cutoff
from core.timeutil import parse


def payer_ref(shop_id: str, vpa: str) -> str:
    """Opaque reference for a payer (card ids never expose a VPA)."""
    return hashlib.sha256(f"{shop_id}|{vpa}".encode()).hexdigest()[:12]


def _excluded_vpas(conn: sqlite3.Connection, shop_id: str, as_of: str) -> set[str]:
    """VPAs already on the ladder / with credit history / recently declined."""
    ex = set()
    for r in conn.execute("SELECT DISTINCT v.payer_vpa FROM vpa_map v JOIN udhaar u ON u.customer_id=v.customer_id "
                          "AND u.shop_id=v.shop_id WHERE v.shop_id=?", (shop_id,)):
        ex.add(r[0])
    for r in conn.execute("SELECT payer_vpa, decision, decided_at FROM credit_offers WHERE shop_id=? AND payer_vpa IS NOT NULL",
                          (shop_id,)):
        if r["decision"] == "yes":
            ex.add(r["payer_vpa"])
        elif r["decision"] == "no" and r["decided_at"] and \
                (parse(as_of) - parse(r["decided_at"])).days < config.DECLINE_SNOOZE_DAYS:
            ex.add(r["payer_vpa"])
    return ex


def consented_vpas(conn: sqlite3.Connection, shop_id: str) -> set[str]:
    """DPDP: payers who agreed to share their payment record with THIS shop."""
    return {r[0] for r in conn.execute("SELECT payer_vpa FROM consents WHERE shop_id=? AND consent=1", (shop_id,))}


def scored_payers(conn: sqlite3.Connection, shop_id: str, as_of: str) -> pd.DataFrame:
    """Scores ONLY this shop's own payments, ONLY for payers who consented. Nothing is pooled across shops."""
    pay = shop_payments_df(conn, shop_id)
    pay = pay[pay["payer_key"].isin(consented_vpas(conn, shop_id))]
    if pay.empty:
        return pd.DataFrame()
    if pay.empty:
        return pd.DataFrame()
    cut = to_cutoff(pd.Timestamp(as_of))
    credit = shop_credit_df(conn, shop_id).dropna(subset=["payer_key"])
    X = build(pay, cut, credit if not credit.empty else None)
    X["score"] = trust_model.predict(X)
    names = (pay[pay["payer_name"] != ""].sort_values("ts").groupby("payer_key")["payer_name"].last())
    X["display_name"] = [display_upi_name(names.get(k, "")) or "UPI customer" for k in X.index]
    X["n_total"] = pay[pay["ts"] < cut].groupby("payer_key").size().reindex(X.index).fillna(0).astype(int)
    return X


def hidden_regulars(conn: sqlite3.Connection, shop_id: str, as_of: str, top_k: int = config.HIDDEN_REGULAR_TOP_K) -> dict:
    pay_first = conn.execute("SELECT MIN(ts) FROM payments WHERE shop_id=? AND status='SUCCESS'", (shop_id,)).fetchone()[0]
    if not pay_first or (parse(as_of) - parse(pay_first)).days < config.MIN_SHOP_HISTORY_DAYS:
        return {"status": "need_more_data", "items": [], "threshold": config.trust_threshold()}
    X = scored_payers(conn, shop_id, as_of)
    thr = config.trust_threshold()
    if X.empty:
        return {"status": "ok", "items": [], "threshold": thr}
    ex = _excluded_vpas(conn, shop_id, as_of)
    elig = X[(~X.index.isin(ex)) & X["prior_ontime_rate"].isna()
             & (X["n_pay_90d"] >= config.HIDDEN_REGULAR_MIN_PAYMENTS_90D)
             & (X["recency_days"] <= config.HIDDEN_REGULAR_MAX_RECENCY_DAYS)]
    near = elig.sort_values("score", ascending=False)
    picked = near[near["score"] >= thr].head(top_k)
    reasons = trust_model.explain(picked) if not picked.empty else []
    items = []
    for (vpa, row), rs in zip(picked.iterrows(), reasons):
        months = max(1, int(round(row["tenure_days"] / 30)))
        items.append({"payer_ref": payer_ref(shop_id, vpa), "payer_vpa": vpa, "display_name": row["display_name"],
                      "score": round(float(row["score"]), 3), "consent": True, "n_total": int(row["n_total"]), "n_pay_90d": int(row["n_pay_90d"]),
                      "months": months, "reasons": rs, "features": {f: (None if pd.isna(row[f]) else round(float(row[f]), 2)) for f in FEATURES}})
    return {"status": "ok", "items": items, "threshold": thr,
            "eligible_by_rule": int(len(elig)), "below_threshold": int((near["score"] < thr).sum()),
            "near_misses": [{"display_name": r["display_name"], "score": round(float(r["score"]), 3)}
                            for _, r in near[near["score"] < thr].head(3).iterrows()]}


def find_by_ref(conn: sqlite3.Connection, shop_id: str, ref: str) -> str | None:
    for r in conn.execute("SELECT DISTINCT payer_vpa FROM payments WHERE shop_id=? AND payer_vpa<>''", (shop_id,)):
        if payer_ref(shop_id, r[0]) == ref:
            return r[0]
    return None


def first_payment_days(conn: sqlite3.Connection, shop_id: str, as_of: str) -> float:
    r = conn.execute("SELECT MIN(ts) FROM payments WHERE shop_id=?", (shop_id,)).fetchone()[0]
    return (parse(as_of) - parse(r)).total_seconds() / 86400 if r else 0.0

