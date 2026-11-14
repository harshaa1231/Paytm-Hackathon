"""LLM-as-judge (plan P1 step 3). Runs on every card before it is shown.

Stage 1 (deterministic, always runs, cannot be skipped):
  - every ₹ amount in the text is one of the ledger values for this card
  - the named customer exists and has open udhaar (repayment cards)
  - no phone number, no full VPA
  - no sensitive attributes / slurs (config.JUDGE_BLOCKLIST)
Stage 2 (second LLM call through core/llm.py): {"numbers_match", "fair_and_polite", "reason"}.
If the candidate text (e.g. an LLM rephrase) fails either stage, or stage 2 is unavailable, the plain
template text is shown instead. The template itself must always pass stage 1.
"""
from __future__ import annotations

import json
import re
import sqlite3

import config
from core import ledger, llm
from core.money import rupees_to_paise
from core.privacy import find_phone_numbers, find_unmasked_vpas
from core.schemas import RephraseAnswer, ToneVerdict

AMOUNT_RE = re.compile(r"₹\s?((?:\d{1,3}(?:,\d{2})*,\d{3})|\d+)(?:\.(\d{1,2}))?")


def amounts_in(text: str) -> list[int]:
    out = []
    for m in AMOUNT_RE.finditer(text):
        rupees = m.group(1).replace(",", "")
        paise = m.group(2) or "0"
        out.append(rupees_to_paise(f"{rupees}.{paise.ljust(2, '0')}"))
    return out


def stage1(text: str, facts: dict, conn: sqlite3.Connection | None = None) -> dict:
    problems: list[str] = []
    allowed = set(int(a) for a in facts.get("allowed_amounts_paise", []))
    for a in amounts_in(text):
        if a not in allowed:
            problems.append(f"amount ₹{a / 100:g} is not a ledger value for this card")
    if facts.get("requires_open_udhaar") and conn is not None:
        cid, shop = facts.get("customer_id"), facts.get("shop_id")
        if not cid or not ledger.get_customer(conn, shop, cid):
            problems.append("named customer does not exist in this shop")
        elif ledger.open_total(conn, shop, cid) <= 0:
            problems.append("named customer has no open udhaar")
    if find_phone_numbers(text):
        problems.append("contains a phone number")
    if find_unmasked_vpas(text):
        problems.append("contains an unmasked UPI ID")
    low = text.lower()
    for w in config.JUDGE_BLOCKLIST:
        if re.search(rf"\b{re.escape(w)}\b", low):
            problems.append(f"blocked word: {w}")
    return {"ok": not problems, "problems": problems}


def keeps_meaning(template: str, candidate: str) -> list[str]:
    """Deterministic checks for a rephrase: it may not DROP any ₹ amount from the template, and if the template asks
    the shopkeeper a question, the rephrase must still ask it (no deciding for them)."""
    problems = []
    missing = sorted(set(amounts_in(template)) - set(amounts_in(candidate)))
    if missing:
        problems.append("rephrase dropped amount(s): " + ", ".join(f"₹{m / 100:g}" for m in missing))
    if template.rstrip().endswith("?") and "?" not in candidate:
        problems.append("rephrase dropped the question to the shopkeeper")
    return problems


def tone_prompt(text: str, facts: dict) -> str:
    public_facts = {k: v for k, v in facts.items() if k in ("allowed_amounts_display", "card_type", "count_facts")}
    return (
        "You are checking a short message that a ledger app will show to a small shopkeeper in India.\n"
        f"Ledger facts (ground truth): {json.dumps(public_facts, ensure_ascii=False)}\n"
        f"Message: {llm.wrap_data(text)}\n"
        "numbers_match = every rupee amount and count in the message agrees with the ledger facts.\n"
        "fair_and_polite = the message is respectful, doesn't shame or judge the customer, mentions no religion, "
        "caste, gender or other personal attribute, and doesn't pressure the shopkeeper.\n"
        'Return JSON: {"numbers_match": true|false, "fair_and_polite": true|false, "reason": "<short>"}'
    )


def rephrase_prompt(text: str) -> str:
    return (
        "Rewrite this ledger-app message as short, warm, simple Hinglish in Latin script for a kirana shopkeeper "
        "(max 2 sentences). Keep EVERY ₹ amount and number exactly as written (do not drop any), keep the names exactly, "
        "keep words like 'about' and 'likely' (don't make an estimate sound certain), and if the message ends with a "
        "question, end with the same question: the shopkeeper decides, so never tell them what to do. Add no new facts.\n"
        f"Message: {llm.wrap_data(text)}\n"
        'Return JSON: {"text": "<rewritten message>"}'
    )


def judge_card(template_text: str, facts: dict, *, conn: sqlite3.Connection | None = None,
               try_rephrase: bool = False, shop_id: str | None = None, mode: str | None = None) -> dict:
    """Returns {"text": final text to show, "source": "llm_rephrase"|"template", "stage1": ..., "stage2": ..., "rephrase": ...}."""
    s1_template = stage1(template_text, facts, conn)
    out = {"template_stage1": s1_template, "rephrase": None}
    candidate, source = template_text, "template"
    if try_rephrase and config.REPHRASE_WITH_LLM:
        ans, meta = llm.call("rephrase_card", rephrase_prompt(template_text), RephraseAnswer, shop_id=shop_id, mode=mode)
        out["rephrase"] = {"provider": meta["provider"], "error": meta["error"], "latency_ms": meta["latency_ms"]}
        if ans is not None:
            candidate, source = ans.text.strip(), "llm_rephrase"

    s1 = stage1(candidate, facts, conn)
    if source == "llm_rephrase":
        extra = keeps_meaning(template_text, candidate)
        s1 = {"ok": s1["ok"] and not extra, "problems": s1["problems"] + extra}
    verdict, meta2 = llm.call("tone_check", tone_prompt(candidate, facts), ToneVerdict, shop_id=shop_id, mode=mode)
    s2 = {"provider": meta2["provider"], "latency_ms": meta2["latency_ms"], "error": meta2["error"],
          "available": verdict is not None,
          "numbers_match": getattr(verdict, "numbers_match", None),
          "fair_and_polite": getattr(verdict, "fair_and_polite", None),
          "reason": getattr(verdict, "reason", "LLM judge unavailable: showing the checked template text")}
    passed = s1["ok"] and verdict is not None and verdict.numbers_match and verdict.fair_and_polite
    if source == "llm_rephrase" and not passed:
        candidate, source = template_text, "template"
    out.update(stage1=s1, stage2=s2, text=candidate, source=source,
               shown_reason=("LLM text passed both checks" if source == "llm_rephrase" else
                             "template text (passed stage 1)" if s1_template["ok"] else "template FAILED stage 1"))
    return out
