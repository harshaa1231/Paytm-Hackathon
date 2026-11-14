"""Self-improving loop (plan P3 step 2).

1. Matcher: replay 4 synthetic weeks of repayments at a fresh shop. Each week the (simulated) shopkeeper confirms
   the true customer, which adds to vpa_map and match_examples. We measure, from the actual replay, the share of
   repayments auto-resolved and how many would need an LLM call.
2. Trust model: "Retrain on this week's repayments" adds the next batch of SYNTHETIC repayment outcomes, retrains, and
   shows before/after on the same held-out shops, with a bootstrap noise band. Learns only from repayments - never from
   the shopkeeper's yes/no - and a customer's record is never shared with other shops.
"""
from __future__ import annotations

import json
import tempfile
from datetime import timedelta
from pathlib import Path

import numpy as np

import config
from core import db, ledger, matcher, trust_model, world
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
                                                       "train_rows": m["train_rows"], "roc_auc": m["roc_auc"],
                                                       "roc_auc_ci95": m.get("roc_auc_ci95"), "brier": m["brier"]}]}
    _state_path().write_text(json.dumps(st, indent=1))


def retrain_next(conn=None, shop_id: str = config.DEMO_SHOP_ID) -> dict:
    """Add the next batch of SYNTHETIC repayment outcomes, retrain, save, report before/after on the same held-out shops.

    Learns only from repayments. A customer's record is never shared with other shops: no shop's own data is ever
    added to this shared model (conn/shop_id are only used for the audit log)."""
    st = load_state() or {"batches": [1], "history": []}
    remaining = [b for b in BATCH_ORDER if b not in st["batches"]]
    before = st["history"][-1] if st["history"] else None
    if not remaining:
        return {"before": before, "after": before, "metrics": None, "status": "no new repayment batches",
                "history": st["history"]}
    new_batches = st["batches"] + remaining[:1]
    res = trust_model.train(world.load_world(), batches=tuple(new_batches))
    trust_model.save(res["model"], res["metrics"], res["threshold"])
    m = res["metrics"]
    after = {"step": len(st["history"]), "label": f"+ repayments batch {remaining[0]}", "batches": new_batches,
             "train_rows": m["train_rows"], "roc_auc": m["roc_auc"], "roc_auc_ci95": m["roc_auc_ci95"],
             "brier": m["brier"], "threshold": round(res["threshold"], 4)}
    if before:
        delta = round(after["roc_auc"] - before["roc_auc"], 4)
        half = (m["roc_auc_ci95"][1] - m["roc_auc_ci95"][0]) / 2
        after["auc_change"] = delta
        after["auc_change_within_noise"] = bool(abs(delta) <= half)
    st["batches"] = new_batches
    st["history"].append(after)
    _state_path().write_text(json.dumps(st, indent=1))
    log_conn = db.connect()
    try:
        db.log_event(log_conn, "trust_retrained", {"before": before, "after": after,
                                                    "labels": "repayment outcomes only; no shop's own data is shared"}, shop_id)
    finally:
        log_conn.close()
    return {"before": before, "after": after, "metrics": m, "status": "retrained", "history": st["history"]}
