"""Service layer: the SAME functions back every FastAPI endpoint, so the web app shows exactly what the API returns.

"The app screen and the API return exactly the same cards, so Paytm's app team would only render this JSON."
"""
from __future__ import annotations

import json
import shutil
import sqlite3

import config
from core import cards, db, forecast, graph, judge, ladder, ledger, recommend
from core.i18n import t
from core.money import fmt_inr
from datetime import timedelta

from core.timeutil import iso, now_iso, parse


# ------------------------------------------------------------------ cards
def _sentence(reasons: list[str]) -> str:
    if not reasons:
        return "Pays you regularly"
    s = " and ".join(reasons) if len(reasons) <= 2 else ", ".join(reasons[:-1]) + " and " + reasons[-1]
    return s[0].upper() + s[1:]


def trust_cards(conn: sqlite3.Connection, shop_id: str, lang: str = "en", mode: str | None = None) -> list[dict]:
    as_of = now_iso()
    recs = recommend.hidden_regulars(conn, shop_id, as_of)
    if recs["status"] == "need_more_data":
        return [{"card_id": f"trust:info:{shop_id}", "type": "who_to_trust", "title": t("wt_info_title", lang),
                 "body": t("need_4_weeks", lang), "amount_paise": 0, "actions": [], "lang": lang, "info": True}]
    out = []
    amount = ladder.STEPS[0]
    for it in recs["items"]:
        body = t("wt_body", lang, name=it["display_name"], n=it["n_total"], months=it["months"],
                 reasons=_sentence(it["reasons"]), amount=fmt_inr(amount))
        facts = {"shop_id": shop_id, "card_type": "who_to_trust", "allowed_amounts_paise": [amount],
                 "allowed_amounts_display": [fmt_inr(amount)],
                 "count_facts": {"payments": it["n_total"], "months": it["months"], "payments_last_90_days": it["n_pay_90d"],
                                 "udhaar_on_record": 0}}
        v = judge.judge_card(body, facts, try_rephrase=(lang == "en"), shop_id=shop_id, mode=mode)
        out.append({"card_id": f"trust:{it['payer_ref']}", "type": "who_to_trust", "lang": lang,
                    "title": t("wt_title", lang, name=it["display_name"]), "body": v["text"], "template_body": body,
                    "amount_paise": amount, "note": t("wt_consent", lang),
                    "actions": [{"id": "offer_yes", "label": t("btn_yes_offer", lang, amount=fmt_inr(amount)), "kind": "primary"},
                                {"id": "offer_no", "label": t("btn_no", lang), "kind": "secondary"}],
                    "judge": v, "score": it["score"], "reasons": it["reasons"], "features": it["features"],
                    "threshold": recs["threshold"]})
    return out


def forecast_card(conn: sqlite3.Connection, shop_id: str, lang: str = "en", mode: str | None = None) -> dict:
    fc = forecast.shop_forecast(conn, shop_id, now_iso())
    card = {"card_id": f"fc:{shop_id}", "type": "coming_back", "lang": lang, "title": t("cb_title", lang), "actions": [],
            "amount_paise": fc["expected_paise"], "forecast": fc}
    if fc["status"] == "nothing":
        card["body"] = t("cb_nothing", lang)
        return card
    amounts = [fc["expected_paise"], fc["total_paise"], fc["low_paise"], fc["high_paise"]]
    body = t("cb_body", lang, expected=fmt_inr(fc["expected_paise"]), total=fmt_inr(fc["total_paise"]),
             low=fmt_inr(fc["low_paise"]), high=fmt_inr(fc["high_paise"]))
    facts = {"shop_id": shop_id, "card_type": "coming_back", "allowed_amounts_paise": amounts,
             "allowed_amounts_display": [fmt_inr(a) for a in amounts], "count_facts": {"open_udhaar_entries": fc["n_open"]}}
    v = judge.judge_card(body, facts, try_rephrase=(lang == "en"), shop_id=shop_id, mode=mode)
    card.update(body=v["text"], template_body=body, judge=v,
                range={"total_paise": fc["total_paise"], "low_paise": fc["low_paise"], "high_paise": fc["high_paise"],
                       "n_open": fc["n_open"]})
    if fc["few"]:
        card["note"] = t("cb_few", lang)
    return card


def get_cards(conn: sqlite3.Connection, shop_id: str, lang: str = "en", mode: str | None = None) -> list[dict]:
    """Ordered: payments waiting for a tap, then who-to-trust, then coming-back. Full internal cards."""
    if shop_id not in config.ENABLED_MERCHANTS:
        return []
    out = cards.pending_cards(conn, shop_id, "who_paid")
    out += trust_cards(conn, shop_id, lang, mode)
    out.append(forecast_card(conn, shop_id, lang, mode))
    return out


def get_public_cards(conn: sqlite3.Connection, shop_id: str, lang: str = "en") -> list[dict]:
    return [cards.public(c) for c in get_cards(conn, shop_id, lang)]


# ------------------------------------------------------------------ decisions
def decide(conn: sqlite3.Connection, shop_id: str, card_id: str, decision: dict, flow: graph.PaymentFlow | None = None) -> dict:
    flow = flow or graph.get_flow()
    if card_id.startswith("pay:"):
        return flow.decide(shop_id, card_id[4:], decision)
    if card_id.startswith("trust:"):
        return decide_trust(conn, shop_id, card_id[6:], decision.get("action"))
    raise KeyError("this card has no actions")


def decide_trust(conn: sqlite3.Connection, shop_id: str, ref: str, action: str) -> dict:
    if action not in ("offer_yes", "offer_no"):
        raise ValueError("action must be offer_yes or offer_no")
    vpa = recommend.find_by_ref(conn, shop_id, ref)
    if not vpa:
        raise KeyError("unknown customer for this shop")
    recs = {i["payer_ref"]: i for i in recommend.hidden_regulars(conn, shop_id, now_iso())["items"]}
    item = recs.get(ref)
    if item is None:
        return {"status": "already_decided_or_not_eligible"}
    amount = ladder.STEPS[0]
    cid = None
    if action == "offer_yes":
        cid = ledger.add_customer(conn, shop_id, item["display_name"])
        conn.execute("INSERT OR REPLACE INTO vpa_map(shop_id,payer_vpa,customer_id,confirmed_at) VALUES (?,?,?,?)",
                     (shop_id, vpa, cid, now_iso()))
    conn.execute("INSERT INTO credit_offers(shop_id, customer_id, payer_vpa, amount_paise, step, offered_at, decision, decided_at, score) "
                 "VALUES (?,?,?,?,?,?,?,?,?)",
                 (shop_id, cid, vpa, amount, 1, now_iso(), "yes" if action == "offer_yes" else "no", now_iso(), item["score"]))
    conn.commit()
    # NOTE: a "No" is logged as a decision only. It is never a training label.
    db.log_event(conn, "trust_decision", {"payer_ref": ref, "decision": action, "amount_paise": amount,
                                          "ladder_step": 1, "customer_id": cid, "score": item["score"],
                                          "note": "decisions are never used as training labels"}, shop_id)
    return {"status": "done", "action": action, "customer_id": cid, "amount_paise": amount, "name": item["display_name"]}


# ------------------------------------------------------------------ events in
def ingest_payment(payment: dict, lang: str = "en", flow: graph.PaymentFlow | None = None) -> dict:
    flow = flow or graph.get_flow()
    return flow.ingest(payment, lang)


def ingest_khata(conn: sqlite3.Connection, e: dict) -> dict:
    """Khata sync: customer_ref is the khata app's own customer id (namespaced per merchant)."""
    shop = e["mid"]
    cid = f"{shop}-K-{e['customer_ref']}"
    if not ledger.get_customer(conn, shop, cid):
        ledger.add_customer(conn, shop, e["khata_name"], customer_id=cid, created_at=e["ts"])
    seen = conn.execute("SELECT 1 FROM events WHERE shop_id=? AND type='khata_entry' AND payload_json LIKE ?",
                        (shop, f'%"entry_id": "{e["entry_id"]}"%')).fetchone()
    if seen:
        return {"status": "duplicate"}
    if e["type"] == "udhaar":
        uid = ledger.add_udhaar(conn, shop, cid, e["amount_paise"], given_at=e["ts"])
        res = {"status": "recorded", "udhaar_id": uid}
    else:
        res = {"status": "recorded", **ledger.apply_cash(conn, shop, cid, e["amount_paise"], e["ts"])}
    db.log_event(conn, "khata_entry", {"entry_id": e["entry_id"], "type": e["type"], "customer_id": cid,
                                       "amount_paise": e["amount_paise"]}, shop)
    return res


def next_demo_payment(conn: sqlite3.Connection, shop_id: str, lang: str = "en", flow: graph.PaymentFlow | None = None) -> dict | None:
    r = conn.execute("SELECT * FROM demo_queue WHERE shop_id=? AND ingested=0 ORDER BY seq LIMIT 1", (shop_id,)).fetchone()
    if not r:
        return None
    p = json.loads(r["payload_json"])
    p["ts"] = iso(parse(config.DEMO_NOW) - timedelta(minutes=4 * (10 - int(r["seq"]))))   # 08:54 ... 09:22 on demo morning
    res = ingest_payment(p, lang, flow)
    conn.execute("UPDATE demo_queue SET ingested=1 WHERE seq=?", (r["seq"],))
    conn.commit()
    return {"label": r["label"], "payment": p, **res}


def demo_queue_left(conn: sqlite3.Connection, shop_id: str) -> int:
    return conn.execute("SELECT COUNT(*) FROM demo_queue WHERE shop_id=? AND ingested=0", (shop_id,)).fetchone()[0]


# ------------------------------------------------------------------ admin
def reset_demo() -> None:
    """Restore the DB and models to the seeded state (copies taken right after generate.py)."""
    graph.reset_flows()
    shutil.copyfile(config.DB_SEED_PATH, config.DB_PATH)
    if config.MODELS_SEED_DIR.exists():
        for f in config.MODELS_SEED_DIR.glob("*"):
            shutil.copyfile(f, config.MODELS_DIR / f.name)


def shop_summary(conn: sqlite3.Connection, shop_id: str) -> dict:
    s = conn.execute("SELECT * FROM shops WHERE id=?", (shop_id,)).fetchone()
    return {"shop_id": shop_id, "name": s["name"] if s else shop_id, "shop_type": s["shop_type"] if s else "",
            "owed_total_paise": ledger.open_total(conn, shop_id),
            "open_customers": len(ledger.customers_with_open_udhaar(conn, shop_id))}
