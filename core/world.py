"""Loader for the synthetic training world (data/train_world.db), cached per process."""
from __future__ import annotations

import sqlite3
from functools import lru_cache

import pandas as pd

import config
from core.features import to_ts


@lru_cache(maxsize=2)
def load_world(path: str | None = None) -> dict:
    p = str(path or config.TRAIN_DB_PATH)
    conn = sqlite3.connect(p)
    try:
        customers = pd.read_sql("SELECT * FROM t_customers", conn).set_index("payer_key")
        payments = pd.read_sql("SELECT shop_id, payer_key, ts, amount_paise FROM t_payments WHERE is_repayment=0", conn)
        credit = pd.read_sql("SELECT * FROM t_credit", conn)
        meta = dict(conn.execute("SELECT key, value FROM t_meta").fetchall())
    finally:
        conn.close()
    payments["ts"] = to_ts(payments["ts"])
    for c in ("given_at", "due_at", "repaid_at"):
        credit[c] = to_ts(credit[c])
    return {"customers": customers, "payments": payments, "credit": credit, "meta": meta,
            "cutoff": pd.Timestamp(meta["cutoff"]).tz_convert("UTC"),
            "start": pd.Timestamp(meta["world_start"]).tz_convert("UTC")}
