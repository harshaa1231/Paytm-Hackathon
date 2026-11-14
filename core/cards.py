"""Cards: the ONE function both the Streamlit app and the API use (plan 12c).

Public card JSON: {card_id, type: who_paid|who_to_trust|coming_back, title, body, amount_paise, actions:[...], ...}
Internal extras (judge verdicts, match details) stay in the DB / "Under the hood", not in the API payload.
"""
from __future__ import annotations

import json
import sqlite3

from core import ledger
from core.i18n import t
from core.money import fmt_inr
from core.privacy import mask_vpa

PUBLIC_KEYS = ("card_id", "type", "title", "body", "amount_paise", "actions", "note", "subtitle", "lang", "created_at")


def display_upi_name(name: str | None) -> str:
    n = (name or "").strip()
    return " ".join(w.capitalize() if len(w) > 1 else w.upper() for w in n.split()) if n else ""


def public(card: dict) -> dict:
    return {k: card[k] for k in PUBLIC_KEYS if k in card}


# ------------------------------------------------------------------ who paid
def build_who_paid(conn: sqlite3.Connection, shop_id: str, payment: dict, match: dict, lang: str = "en") -> tuple[dict, dict]:
    """Returns (card, judge_facts). Template text only; judge.py may swap in a checked rephrase."""
    amount = payment["amount_paise"]
    app = payment.get("app") or "UPI"
    upi = display_upi_name(payment.get("payer_name"))
    upi_line = t("wp_upi_line", lang, upi=(upi or "—") + " · " + mask_vpa(payment.get("payer_vpa")))
    card = {"card_id": f"pay:{payment['txn_id']}", "type": "who_paid", "txn_id": payment["txn_id"], "amount_paise": amount,
            "lang": lang, "subtitle": upi_line, "actions": []}
    allowed = {amount}
    facts = {"shop_id": shop_id, "card_type": "who_paid", "requires_open_udhaar": False}

    cid = match.get("customer_id")
    if cid:
        cust = ledger.get_customer(conn, shop_id, cid)
        open_amt = ledger.open_total(conn, shop_id, cid, as_of=payment["ts"])
        name = cust["khata_name"]
        card["customer_id"] = cid
        card["title"] = t("wp_title", lang, name=name, amount=fmt_inr(amount))
        allowed |= {open_amt}
        if amount == open_amt:
            card["body"] = t("wp_body_exact", lang, app=app, open=fmt_inr(open_amt))
            card["actions"] = [
                {"id": "clear_full", "label": t("btn_clear", lang, amount=fmt_inr(amount)), "kind": "primary", "customer_id": cid},
                {"id": "purchase", "label": t("btn_purchase", lang), "kind": "primary"},
                {"id": "not_him", "label": t("btn_not_him", lang), "kind": "secondary"},
            ]
        elif amount < open_amt:
            rest = open_amt - amount
            allowed |= {rest}
            card["body"] = t("wp_body_partial", lang, app=app, amount=fmt_inr(amount), open=fmt_inr(open_amt), rest=fmt_inr(rest))
            card["actions"] = [
                {"id": "clear_part", "label": t("btn_clear", lang, amount=fmt_inr(amount)), "kind": "primary",
                 "customer_id": cid, "amount_paise": amount},
                {"id": "purchase", "label": t("btn_purchase", lang), "kind": "primary"},
                {"id": "not_him", "label": t("btn_not_him", lang), "kind": "secondary"},
            ]
        else:
            extra = amount - open_amt
            allowed |= {extra}
            card["body"] = t("wp_body_over", lang, app=app, open=fmt_inr(open_amt), extra=fmt_inr(extra))
            card["actions"] = [
                {"id": "clear_full", "extra": "advance", "customer_id": cid, "kind": "primary",
                 "label": t("btn_clear_advance", lang, open=fmt_inr(open_amt), extra=fmt_inr(extra))},
                {"id": "clear_full", "extra": "purchase", "customer_id": cid, "kind": "primary",
                 "label": t("btn_clear_rest_purchase", lang, open=fmt_inr(open_amt))},
                {"id": "purchase", "label": t("btn_purchase", lang), "kind": "secondary"},
                {"id": "not_him", "label": t("btn_not_him", lang), "kind": "secondary"},
            ]
        card["open_paise"] = open_amt
        facts.update(requires_open_udhaar=True, customer_id=cid)
        # alternatives for "Not this customer"
        card["alternatives"] = [
            {"customer_id": c["customer_id"], "label": t("btn_pick", lang, name=c["khata_name"], open=fmt_inr(sum(c["open_amounts"])))}
            for c in match.get("candidates", []) if c["customer_id"] != cid][:3]
    else:
        # no confident proposal: let the shopkeeper pick (ambiguous / blank name)
        cands = match.get("candidates", [])[:3]
        card["title"] = t("wp_title_unknown", lang, amount=fmt_inr(amount), app=app) if not upi else \
            t("wp_title", lang, name=upi, amount=fmt_inr(amount))
        card["body"] = t("wp_body_pick", lang, app=app)
        for c in cands:
            total = sum(c["open_amounts"])
            allowed |= {total}
            card["actions"].append({"id": "clear_full", "customer_id": c["customer_id"], "kind": "primary",
                                    "label": t("btn_pick", lang, name=c["khata_name"], open=fmt_inr(total))})
        card["actions"].append({"id": "purchase", "label": t("btn_purchase", lang), "kind": "secondary"})
    facts["allowed_amounts_paise"] = sorted(allowed)
    facts["allowed_amounts_display"] = [fmt_inr(a) for a in sorted(allowed)]
    return card, facts


# ------------------------------------------------------------------ stored (pending) cards
def save_card(conn: sqlite3.Connection, card: dict, shop_id: str, created_at: str) -> None:
    """Upsert a pending card (idempotent: a decided card is never reopened)."""
    row = conn.execute("SELECT status FROM cards WHERE card_id=?", (card["card_id"],)).fetchone()
    if row and row["status"] != "pending":
        return
    card = {**card, "created_at": created_at}
    conn.execute(
        "INSERT OR REPLACE INTO cards(card_id, shop_id, txn_id, type, payload_json, status, created_at) VALUES (?,?,?,?,?, 'pending', ?)",
        (card["card_id"], shop_id, card.get("txn_id"), card["type"], json.dumps(card, ensure_ascii=False), created_at))
    conn.commit()


def get_card(conn: sqlite3.Connection, shop_id: str, card_id: str) -> dict | None:
    r = conn.execute("SELECT * FROM cards WHERE shop_id=? AND card_id=?", (shop_id, card_id)).fetchone()
    if not r:
        return None
    d = json.loads(r["payload_json"])
    d["status"] = r["status"]
    d["decision"] = json.loads(r["decision_json"]) if r["decision_json"] else None
    return d


def pending_cards(conn: sqlite3.Connection, shop_id: str, type_: str | None = None) -> list[dict]:
    q = "SELECT payload_json FROM cards WHERE shop_id=? AND status='pending'"
    args: list = [shop_id]
    if type_:
        q += " AND type=?"
        args.append(type_)
    q += " ORDER BY created_at, card_id"
    return [json.loads(r["payload_json"]) for r in conn.execute(q, args).fetchall()]


def mark_decided(conn: sqlite3.Connection, shop_id: str, card_id: str, decision: dict, decided_at: str) -> None:
    conn.execute("UPDATE cards SET status='decided', decided_at=?, decision_json=? WHERE shop_id=? AND card_id=?",
                 (decided_at, json.dumps(decision), shop_id, card_id))
    conn.commit()
