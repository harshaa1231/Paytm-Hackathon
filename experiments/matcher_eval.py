"""Real-data check #3: name matcher on labelled Indian name-variation cases (tests/data/name_cases.json).

Each case is a mini shop (customers with open udhaar) and a UPI payer name. We run the matcher WITHOUT the LLM
and only count AUTO-matches (VPA memory off, RapidFuzz confident). Because a false match costs the shopkeeper money,
precision matters more than recall; ambiguous cases going to the LLM / shopkeeper are fine.

    python experiments/matcher_eval.py      -> reports/matcher_metrics.json
"""
from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from core import db, ledger, matcher  # noqa: E402

CASES = ROOT / "tests" / "data" / "name_cases.json"


def run_case(case: dict, tmp: Path, i: int) -> dict:
    conn = db.connect(tmp / f"c{i}.db")
    db.init_schema(conn)
    ledger.add_shop(conn, "M1", "Eval shop")
    ids = []
    for k, name in enumerate(case["khata"]):
        cid = ledger.add_customer(conn, "M1", name, customer_id=f"M1-C{k}", created_at="2026-10-01T10:00:00+05:30")
        ledger.add_udhaar(conn, "M1", cid, 10_000 * (k + 3), given_at="2026-11-01T10:00:00+05:30")
        ids.append(cid)
    pay = {"txn_id": f"E{i}", "shop_id": "M1", "payer_vpa": "", "payer_name": case["upi"], "amount_paise": 12_345,
           "ts": "2026-11-14T09:00:00+05:30"}
    m = matcher.find_candidates(conn, "M1", pay, use_llm=False)
    conn.close()
    auto = m["stage"] in ("fuzzy_confident", "vpa_memory")
    picked = ids.index(m["customer_id"]) if auto and m.get("customer_id") in ids else None
    return {"upi": case["upi"], "type": case["type"], "truth": case["truth"], "stage": m["stage"], "auto": auto, "picked": picked,
            "top_score": m["candidates"][0]["score"] if m.get("candidates") else None}


PAIRS = ROOT / "tests" / "data" / "name_pairs.json"


def run_pairs(tmp: Path) -> dict:
    """Part A: ~60 labelled pairs. Each pair is a shop with ONE customer (the khata name) with open udhaar; the
    payment carries the UPI name. 'Auto-match' = the matcher proposes that customer without the LLM or a pick list
    (name score >= the auto-match threshold, config.MATCH_CONFIDENT_SCORE)."""
    pairs = json.loads(PAIRS.read_text())["pairs"]
    rows = []
    for i, p in enumerate(pairs):
        r = run_case({"upi": p["upi"], "khata": [p["khata"]], "truth": 0 if p["label"] == "same_person" else None,
                      "type": p["type"]}, tmp, 1000 + i)
        rows.append({**r, "khata": p["khata"], "label": p["label"]})
    auto = [r for r in rows if r["auto"]]
    tp = [r for r in auto if r["label"] == "same_person"]
    fp = [r for r in auto if r["label"] == "different_person"]
    same = [r for r in rows if r["label"] == "same_person"]
    diff = [r for r in rows if r["label"] == "different_person"]
    return {"n_pairs": len(rows), "n_same_person": len(same), "n_different_person": len(diff),
            "auto_match_threshold": f"name score >= {matcher.config.MATCH_CONFIDENT_SCORE}",
            "auto_matched": len(auto),
            "precision_at_auto_match": round(len(tp) / len(auto), 4) if auto else None,
            "false_match_rate": round(len(fp) / len(diff), 4) if diff else None,
            "recall_same_person": round(len(tp) / len(same), 4) if same else None,
            "false_matches": [{k: r[k] for k in ("upi", "khata", "type", "top_score")} for r in fp],
            "same_person_not_auto_matched": [{k: r[k] for k in ("upi", "khata", "type", "stage", "top_score")}
                                             for r in same if not r["auto"]],
            "pairs": rows}


def run(write: bool = True) -> dict:
    cases = json.loads(CASES.read_text())["cases"]
    tmp = Path(tempfile.mkdtemp())
    pairs = run_pairs(tmp)
    rows = [run_case(c, tmp, i) for i, c in enumerate(cases)]
    auto = [r for r in rows if r["auto"]]
    correct = [r for r in auto if r["picked"] == r["truth"]]
    false = [r for r in auto if r["picked"] != r["truth"]]
    positives = [r for r in rows if r["truth"] is not None]
    negatives = [r for r in rows if r["truth"] is None]
    shop_level = {
        "n_pairs": len(rows), "n_same_person": len(positives), "n_should_not_auto_match": len(negatives),
        "auto_matched": len(auto),
        "precision_auto": round(len(correct) / len(auto), 4) if auto else None,
        "recall_auto": round(len([r for r in positives if r["auto"] and r["picked"] == r["truth"]]) / len(positives), 4),
        "false_match_rate": round(len(false) / len(rows), 4),
        "false_matches": [{k: r[k] for k in ("upi", "type", "stage", "top_score")} for r in false],
        "sent_to_llm_or_shopkeeper": len([r for r in rows if r["stage"] in ("ambiguous", "blank_name_pick")]),
        "source_of_variation_types": "Variation types from IDinsight's published work on Hindi name matching (transliteration "
                                     "spellings, v/b swaps, many Latin spellings of one name). Their code was not copied.",
        "cases": rows,
    }
    res = {"title": "Indian name matching (first validation task)",
           "part_a_labelled_pairs": pairs,
           "part_b_shop_level": {**{k: v for k, v in shop_level.items() if k not in ("source_of_variation_types",)},
                                 "note": "Mini shops with 2+ customers, incl. different people with near-identical names, "
                                         "which must stay ambiguous (go to the LLM / shopkeeper) rather than auto-match."},
           "source_of_variation_types": shop_level["source_of_variation_types"],
           # headline numbers (kept at top level for the UI)
           "n_pairs": pairs["n_pairs"], "precision_auto": pairs["precision_at_auto_match"],
           "false_match_rate": pairs["false_match_rate"], "recall_auto": pairs["recall_same_person"]}
    if write:
        (ROOT / "reports" / "matcher_metrics.json").write_text(json.dumps(res, indent=1, ensure_ascii=False))
    return res


if __name__ == "__main__":
    r = run()
    a, b = r["part_a_labelled_pairs"], r["part_b_shop_level"]
    print("A pairs:", {k: a[k] for k in ("n_pairs", "n_same_person", "n_different_person", "auto_matched",
                                          "precision_at_auto_match", "false_match_rate", "recall_same_person")})
    print("  false matches:", a["false_matches"])
    print("  same person, not auto-matched:", [(x["upi"], x["khata"], x["stage"], x["top_score"]) for x in a["same_person_not_auto_matched"]])
    print("B shop-level:", {k: b[k] for k in ("n_pairs", "auto_matched", "precision_auto", "false_match_rate")},
          "two-people cases auto-matched:", [c["upi"] for c in b["cases"] if "two people" in c["type"] and c["auto"]])
