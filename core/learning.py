"""Self-improving loop (plan P3 step 2).

1. Matcher: replay 4 synthetic weeks of repayments at a fresh shop. Each week the (simulated) shopkeeper confirms
   the true customer, which adds to vpa_map and match_examples. We measure, from the actual replay, the share of
   repayments auto-resolved and how many would need an LLM call.
2. Trust model: "Retrain on this week's repayments" adds the next batch of repayment OUTCOMES (more pilot shops
   reporting back) plus this shop's own closed udhaar, retrains, and shows before/after on the same held-out shops.
   Learns from repayments only - never from the shopkeeper's yes/no.
"""
from __future__ import annotations

import json
import tempfile
from datetime import timedelta
from pathlib import Path

import numpy as np
import pandas as pd

import config
from core import db, ledger, matcher, trust_model, world
from core.features import FEATURES, build, shop_credit_df, shop_payments_df, to_cutoff
from core.timeutil import iso, parse
from data import names as N

STATE_FILE = "learning_state.json"
BATCH_ORDER = [1, 2, 3]


# ------------------------------------------------------------------ 1) matcher replay
def replay_matcher(weeks: int = 4, n_customers: int = 80, seed: int = config.SEED) -> dict:
    rng = np.random.default_rng(seed + 7)
    path = Path(tempfile.mkdtemp()) / "replay.db"
    conn = db.connect(path)
    db.init_schema(conn)
    shop = "R001"
    ledger.add_shop(conn, shop, "Replay Kirana")
    start = parse(config.DEMO_NOW) - timedelta(days=7 * weeks + 2)
    people = []
    used = set()
    for i in range(n_customers):
        first, sur = N.pick_person(rng)
        while (first, sur[0]) in used:
            first, sur = N.pick_person(rng)
        used.add((first, sur[0]))
        khata = N.khata_name(rng, first, sur)
        cid = ledger.add_customer(conn, shop, khata, customer_id=f"R-C{i:03d}", created_at=iso(start))
        own = (N.vpa(rng, first), N.upi_name(rng, first, sur))
        fam_first, _ = N.pick_person(rng)
        family = (N.vpa(rng, fam_first), N.upi_name(rng, fam_first, sur))      # a family member sometimes pays
        people.append({"cid": cid, "khata": khata, "own": own, "family": family})

    weekly = []
    txn = 0
    for w in range(weeks):
        wk_start = start + timedelta(days=7 * w)
        # new udhaar this week for ~60% of customers
        for p in people:
            if rng.random() < 0.6:
                ledger.add_udhaar(conn, shop, p["cid"], int(rng.integers(5, 80)) * 1000,
                                  given_at=iso(wk_start + timedelta(hours=float(rng.uniform(1, 30)))))
        stats = {"week": w + 1, "repayments": 0, "auto_resolved": 0, "auto_correct": 0, "false_auto": 0,
                 "needs_llm": 0, "asked_pick": 0, "missed": 0, "vpa_memory": 0, "fuzzy_confident": 0}
        for p in people:
            open_ = ledger.open_udhaar(conn, shop, p["cid"])
            if not open_ or rng.random() > 0.7:
                continue
            u = open_[0]
            vpa, upi = p["own"] if rng.random() < 0.85 else p["family"]
            txn += 1
            ts = iso(wk_start + timedelta(days=float(rng.uniform(2, 6.9))))
            pay = {"txn_id": f"R-{txn:05d}", "shop_id": shop, "payer_vpa": vpa, "payer_name": upi,
                   "amount_paise": int(u["remaining_paise"]), "app": "PhonePe", "status": "SUCCESS", "ts": ts}
            ledger.record_payment(conn, pay)
            m = matcher.find_candidates(conn, shop, pay, use_llm=False)
            stats["repayments"] += 1
            st = m["stage"]
            if st in ("vpa_memory", "fuzzy_confident"):
                stats["auto_resolved"] += 1
                stats[st] += 1
                if m["customer_id"] == p["cid"]:
                    stats["auto_correct"] += 1
                else:
                    stats["false_auto"] += 1
            elif st == "ambiguous":
                stats["needs_llm"] += 1
            elif st == "blank_name_pick":
                stats["asked_pick"] += 1
            else:
                stats["missed"] += 1          # shown as "purchase"; the shopkeeper would add it by hand
            # the shopkeeper confirms the true customer -> ledger + learning (same as graph.learn)
            ledger.apply_payment(conn, shop, p["cid"], pay["txn_id"])
            conn.execute("INSERT OR REPLACE INTO vpa_map VALUES (?,?,?,?)", (shop, vpa, p["cid"], ts))
            if upi:
                conn.execute("INSERT INTO match_examples(shop_id,payer_name,khata_name,label,created_at) VALUES (?,?,?,?,?)",
                             (shop, upi, p["khata"], "match", ts))
            conn.commit()
        n = max(1, stats["repayments"])
        stats["auto_resolved_share"] = round(stats["auto_resolved"] / n, 3)
        stats["needs_llm_share"] = round(stats["needs_llm"] / n, 3)
        stats["false_auto_share"] = round(stats["false_auto"] / n, 3)
        stats["vpa_map_size"] = conn.execute("SELECT COUNT(*) FROM vpa_map").fetchone()[0]
        weekly.append(stats)
    conn.close()
    path.unlink(missing_ok=True)
    return {"weeks": weekly, "customers": n_customers, "seed": seed,
            "note": "From an actual replay: synthetic names with documented Indian spelling variation; the simulated "
                    "shopkeeper confirms the true customer each week. LLM not called; 'needs LLM' counts ambiguous cases."}


# ------------------------------------------------------------------ 2) trust retrain on repayments only
def _state_path() -> Path:
    return config.MODELS_DIR / STATE_FILE


def load_state() -> dict:
    try:
        return json.loads(_state_path().read_text())
    except Exception:
        return {}


def init_state() -> None:
    m = json.loads((config.REPORTS_DIR / "metrics.json").read_text())
    st = {"batches": list(m["batches"]), "history": [{"step": 0, "label": "initial model", "batches": m["batches"],
                                                       "train_rows": m["train_rows"], "roc_auc": m["roc_auc"], "brier": m["brier"],
                                                       "shop_outcomes_used": 0}]}
    _state_path().write_text(json.dumps(st, indent=1))


def shop_outcome_rows(conn, shop_id: str) -> pd.DataFrame:
    """This shop's real repayment outcomes (closed/written-off udhaar, not voided), with payment features at the
    time each udhaar was given. Only for customers with a confirmed VPA (behaviour must be attributable)."""
    rows = conn.execute("SELECT o.udhaar_id, o.repaid_on_time FROM outcomes o JOIN udhaar u ON u.id=o.udhaar_id "
                        "WHERE u.shop_id=? AND o.voided=0", (shop_id,)).fetchall()
    if not rows:
        return pd.DataFrame()
    labels = {r["udhaar_id"]: r["repaid_on_time"] for r in rows}
    credit = shop_credit_df(conn, shop_id)
    pay = shop_payments_df(conn, shop_id)
    c = credit[credit["udhaar_id"].isin(labels)].dropna(subset=["payer_key"]).drop_duplicates("udhaar_id")
    out = []
    hist = credit.dropna(subset=["payer_key"])
    for r in c.itertuples():
        X = build(pay[pay["payer_key"] == r.payer_key], to_cutoff(r.given_at), hist[hist["payer_key"] == r.payer_key])
        if r.payer_key in X.index:
            row = X.loc[r.payer_key].to_dict()
            row.update(label=int(labels[r.udhaar_id]), shop_id=shop_id)
            out.append(row)
    return pd.DataFrame(out, columns=FEATURES + ["label", "shop_id"])


def retrain_next(conn=None, shop_id: str = config.DEMO_SHOP_ID) -> dict:
    """Add the next batch of repayment outcomes (+ this shop's own), retrain, save, report before/after."""
    st = load_state() or {"batches": [1], "history": []}
    remaining = [b for b in BATCH_ORDER if b not in st["batches"]]
    new_batches = st["batches"] + remaining[:1]
    own_conn = conn is None
    conn = conn or db.connect()
    try:
        extra = shop_outcome_rows(conn, shop_id)
    finally:
        if own_conn:
            conn.close()
    w = world.load_world()
    before = st["history"][-1] if st["history"] else None
    res = trust_model.train(w, batches=tuple(new_batches), extra_rows=extra)
    trust_model.save(res["model"], res["metrics"], res["threshold"])
    after = {"step": len(st["history"]), "label": f"+ repayments batch {remaining[0]}" if remaining else "+ this shop's repayments only",
             "batches": new_batches, "train_rows": res["metrics"]["train_rows"], "roc_auc": res["metrics"]["roc_auc"],
             "brier": res["metrics"]["brier"], "shop_outcomes_used": int(len(extra)), "threshold": round(res["threshold"], 4)}
    st["batches"] = new_batches
    st["history"].append(after)
    _state_path().write_text(json.dumps(st, indent=1))
    db_conn = db.connect()
    try:
        db.log_event(db_conn, "trust_retrained", {"before": before, "after": after,
                                                   "labels": "repayment outcomes only (never shopkeeper yes/no)"}, shop_id)
    finally:
        db_conn.close()
    return {"before": before, "after": after, "metrics": res["metrics"]}
