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


def run(write: bool = True) -> dict:
    cases = json.loads(CASES.read_text())["cases"]
    tmp = Path(tempfile.mkdtemp())
    rows = [run_case(c, tmp, i) for i, c in enumerate(cases)]
    auto = [r for r in rows if r["auto"]]
    correct = [r for r in auto if r["picked"] == r["truth"]]
    false = [r for r in auto if r["picked"] != r["truth"]]
    positives = [r for r in rows if r["truth"] is not None]
    negatives = [r for r in rows if r["truth"] is None]
    res = {
        "n_pairs": len(rows), "n_same_person": len(positives), "n_should_not_auto_match": len(negatives),
        "auto_matched": len(auto),
        "precision_auto": round(len(correct) / len(auto), 4) if auto else None,
        "recall_auto": round(len([r for r in positives if r["auto"] and r["picked"] == r["truth"]]) / len(positives), 4),
        "false_match_rate": round(len(false) / len(rows), 4),
        "false_matches": [{k: r[k] for k in ("upi", "type", "stage", "top_score")} for r in false],
        "sent_to_llm_or_shopkeeper": len([r for r in rows if r["stage"] in ("ambiguous", "blank_name_pick")]),
        "source_of_variation_types": "IDinsight's article on fuzzy-matching Indian names (transliteration, v/b, many spellings); "
                                     "their code (github.com/IDinsight/hindi-fuzzy-merge) was NOT copied.",
        "cases": rows,
    }
    if write:
        (ROOT / "reports" / "matcher_metrics.json").write_text(json.dumps(res, indent=1, ensure_ascii=False))
    return res


if __name__ == "__main__":
    r = run()
    print({k: r[k] for k in ("n_pairs", "auto_matched", "precision_auto", "recall_auto", "false_match_rate", "sent_to_llm_or_shopkeeper")})
    for f in r["false_matches"]:
        print("FALSE:", f)
    print("missed same-person:", [(c["upi"], c["stage"], c["top_score"]) for c in r["cases"] if c["truth"] is not None and not (c["auto"] and c["picked"] == c["truth"])])
