"""Who paid? Map a UPI payment to a khata customer with open udhaar (plan P1 step 2).

Pipeline, stopping at the first confident answer:
1. VPA memory (vpa_map)                         -> confidence 0.99
2. only customers with OPEN udhaar are candidates; none -> purchase, no card
3. RapidFuzz over normalized names (max of token_set_ratio, WRatio) + initials rule + exact-amount bonus
4. top >= 90 and margin >= 10 -> confident; top < 60 -> no match; otherwise ambiguous
5. ambiguous -> LLM with this shop's confirmed examples as few-shot (in-context learning).
   The answer must be one of the supplied candidate ids, else it is treated as null.
The shopkeeper confirms EVERY card; the matcher only decides which customer the card proposes.
"""
from __future__ import annotations

import json
import sqlite3

from rapidfuzz import fuzz

import config
from core import ledger, llm
from core.money import fmt_inr
from core.normalize import NormName, normalize
from core.schemas import MatchAnswer


def name_score(payer: NormName, cand: NormName) -> tuple[float, list[str]]:
    """0-100 fuzzy score plus initials adjustments. Returns (score, notes)."""
    notes: list[str] = []
    if payer.is_blank or cand.is_blank:
        return 0.0, ["blank name"]
    base = max(fuzz.token_set_ratio(payer.key, cand.key), fuzz.WRatio(payer.key, cand.key))
    score = float(min(100.0, base))
    # initials rule: "RAMESH K" fits "Ramesh Kumar" / "Ramesh K. Rao" / "Ramesh dudh wala" (no info),
    # but conflicts with "Ramesh Gupta"
    p_extra = set(payer.initials) | {t[0] for t in payer.tokens if t not in cand.tokens}
    c_extra_tokens = [t for t in cand.tokens if t not in payer.tokens]
    c_letters = set(cand.initials) | {t[0] for t in c_extra_tokens}
    if payer.initials and c_letters:
        if set(payer.initials) & c_letters:
            score += config.INITIAL_MATCH_BONUS
            notes.append("initial matches")
        else:
            score -= config.INITIAL_CONFLICT_PENALTY
            notes.append("initial conflicts")
    elif cand.initials and p_extra and not (set(cand.initials) & p_extra):
        score -= config.INITIAL_CONFLICT_PENALTY
        notes.append("initial conflicts")
    return score, notes


def few_shot_examples(conn: sqlite3.Connection, shop_id: str, k: int = config.MAX_FEWSHOT_EXAMPLES) -> list[dict]:
    rows = conn.execute(
        "SELECT payer_name, khata_name, label FROM match_examples WHERE shop_id=? AND payer_name<>'' ORDER BY id DESC LIMIT ?",
        (shop_id, k)).fetchall()
    return [dict(r) for r in rows]


def build_match_prompt(payment: dict, cands: list[dict], examples: list[dict]) -> str:
    cand_json = [{"id": c["customer_id"], "khata_name": llm.wrap_data(c["khata_name"]),
                  "open_udhaar": [fmt_inr(u) for u in c["open_amounts"]]} for c in cands]
    ex_lines = "\n".join(f"- bank name {llm.wrap_data(e['payer_name'])} -> khata {llm.wrap_data(e['khata_name'])}: {e['label']}"
                         for e in examples) or "- (none yet)"
    return (
        "Task: decide which khata customer (if any) made this UPI payment to a small shop.\n"
        "Bank names are often ALL CAPS, use initials, spelling variants (Laxmi/Lakshmi, Suneeta/Sunita) or a family "
        "member's name. Khata names may include nicknames or descriptors (dudh wala, auto, amma).\n"
        f"Payment: payer name {llm.wrap_data(payment.get('payer_name'))}, amount {fmt_inr(payment['amount_paise'])}.\n"
        f"Candidates (ONLY these ids are valid): {json.dumps(cand_json, ensure_ascii=False)}\n"
        f"This shop's past confirmed decisions:\n{ex_lines}\n"
        'Return JSON: {"candidate_id": "<one id from the list or null>", "confidence": <0..1>, '
        '"reason": "<one short sentence>"}. If unsure between two people, return null.'
    )


def _rule_fallback(payment: dict, cands: list[dict]) -> MatchAnswer:
    """No LLM: propose the candidate whose open udhaar exactly equals the payment, if exactly one does."""
    exact = [c for c in cands if payment["amount_paise"] in c["open_amounts"]
             or payment["amount_paise"] == sum(c["open_amounts"])]
    if len(exact) == 1:
        return MatchAnswer(candidate_id=exact[0]["customer_id"], confidence=0.6,
                           reason="rules: payment equals this customer's open udhaar exactly")
    return MatchAnswer(candidate_id=None, confidence=0.0, reason="rules: can't tell between candidates; ask the shopkeeper")


def find_candidates(conn: sqlite3.Connection, shop_id: str, payment: dict, *, use_llm: bool = True,
                    mode: str | None = None) -> dict:
    """Returns {"stage", "customer_id"|None, "confidence", "candidates": [...], "reason", "llm": meta|None, ...}.

    stage: vpa_memory | fuzzy_confident | llm | ambiguous | no_open_udhaar | no_match | blank_name_pick
    """
    amount = payment["amount_paise"]
    open_map = ledger.customers_with_open_udhaar(conn, shop_id, as_of=payment["ts"])
    payer = normalize(payment.get("payer_name"))
    result = {"payer_norm": {"tokens": payer.tokens, "initials": payer.initials, "hints": payer.hints},
              "candidates": [], "llm": None, "few_shot": []}

    # 1) VPA memory
    vpa = payment.get("payer_vpa") or ""
    if vpa:
        r = conn.execute("SELECT customer_id FROM vpa_map WHERE shop_id=? AND payer_vpa=?", (shop_id, vpa)).fetchone()
        if r:
            cid = r["customer_id"]
            if cid in open_map:
                c = ledger.get_customer(conn, shop_id, cid)
                result.update(stage="vpa_memory", customer_id=cid, confidence=config.VPA_MEMORY_CONFIDENCE,
                              reason="this UPI ID was confirmed for this customer before",
                              candidates=[{"customer_id": cid, "khata_name": c["khata_name"], "score": 100.0,
                                           "open_amounts": [u["remaining_paise"] for u in open_map[cid]], "notes": ["VPA memory"]}])
                return result
            result.update(stage="no_open_udhaar", customer_id=None, confidence=0.0,
                          reason="known payer with no open udhaar: a purchase")
            return result

    # 2) only customers with open udhaar
    if not open_map:
        result.update(stage="no_open_udhaar", customer_id=None, confidence=0.0, reason="no open udhaar in this shop")
        return result

    cands = []
    for cid, us in open_map.items():
        c = ledger.get_customer(conn, shop_id, cid)
        cn = normalize(c["khata_name"])
        score, notes = name_score(payer, cn)
        amounts = [u["remaining_paise"] for u in us]
        if score > 0 and (amount in amounts or amount == sum(amounts)):
            score += config.AMOUNT_BONUS
            notes.append("amount equals open udhaar")
        cands.append({"customer_id": cid, "khata_name": c["khata_name"], "score": round(score, 1),
                      "open_amounts": amounts, "notes": notes})
    cands.sort(key=lambda x: -x["score"])
    result["candidates"] = cands[:config.MAX_LLM_CANDIDATES]

    # blank UPI name and unknown VPA: shopkeeper picks, but only if the amount fits someone's udhaar exactly
    if payer.is_blank:
        exact = [c for c in cands if amount in c["open_amounts"] or amount == sum(c["open_amounts"])]
        if exact:
            result.update(stage="blank_name_pick", customer_id=None, confidence=0.0, candidates=exact[:config.MAX_LLM_CANDIDATES],
                          reason="no name on this payment; amount matches open udhaar, so ask which customer")
        else:
            result.update(stage="no_match", customer_id=None, confidence=0.0, reason="no name and no amount match: a purchase")
        return result

    top = cands[0]
    second = cands[1]["score"] if len(cands) > 1 else 0.0
    if top["score"] < config.MATCH_MIN_SCORE:
        result.update(stage="no_match", customer_id=None, confidence=0.0,
                      reason=f"best name score {top['score']:.0f} < {config.MATCH_MIN_SCORE}: treat as a purchase")
        return result
    if top["score"] >= config.MATCH_CONFIDENT_SCORE and top["score"] - second >= config.MATCH_MARGIN:
        result.update(stage="fuzzy_confident", customer_id=top["customer_id"], confidence=min(0.95, top["score"] / 105),
                      reason=f"name score {top['score']:.0f}, next best {second:.0f}")
        return result

    # 5) ambiguous -> LLM (only the plausible candidates)
    plausible = [c for c in cands if c["score"] >= config.MATCH_MIN_SCORE][:config.MAX_LLM_CANDIDATES]
    result["candidates"] = plausible
    if not use_llm:
        result.update(stage="ambiguous", customer_id=None, confidence=0.0, reason="ambiguous; LLM not used")
        return result
    examples = few_shot_examples(conn, shop_id)
    result["few_shot"] = examples
    prompt = build_match_prompt(payment, plausible, examples)
    ans, meta = llm.call("match_name", prompt, MatchAnswer, fallback=lambda: _rule_fallback(payment, plausible),
                         shop_id=shop_id, mode=mode)
    result["llm"] = meta
    valid_ids = {c["customer_id"] for c in plausible}
    cid = ans.candidate_id if ans else None
    if cid is not None and cid not in valid_ids:
        meta["error"] = (meta.get("error") or "") + "; id not in candidate list -> null"
        cid = None
    result.update(stage="llm", customer_id=cid, confidence=float(ans.confidence) if (ans and cid) else 0.0,
                  reason=(ans.reason if ans else "no answer"))
    return result
