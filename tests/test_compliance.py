"""Indian compliance guardrails, checked in code (not just in the README).

- Nothing moves money, initiates payments or sends payment/collect requests (NPCI ended P2P collect requests on
  1 Oct 2025). The only writes are khata bookkeeping entries after the shopkeeper taps.
- The AI never sends messages to customers.
- Wording: never "loan", "lend", "credit line" or "offer credit" in anything the shopkeeper sees.
"""
import json
import re
from pathlib import Path

import config
from core import judge, llm

ROOT = Path(__file__).resolve().parents[1]
BANNED = ("loan", "lend", "credit line", "offer credit")


def test_api_has_no_money_or_messaging_routes():
    from api.main import app
    paths = {r.path for r in app.routes if hasattr(r, "methods")}
    expected = {"/health", "/v1/events/payment", "/v1/events/khata", "/v1/merchants/{mid}/cards", "/v1/merchants/{mid}/decisions",
                "/v1/admin/reset", "/v1/admin/retrain", "/v1/demo/config", "/v1/demo/i18n", "/v1/demo/{mid}/state",
                "/v1/demo/{mid}/simulate", "/v1/demo/{mid}/undo", "/v1/demo/{mid}/today", "/v1/demo/{mid}/khata", "/v1/demo/{mid}/payments", "/v1/demo/{mid}/trace/{txn_id}",
                "/v1/demo/{mid}/internals", "/v1/demo/{mid}/events", "/v1/demo/reports", "/v1/demo/reset", "/v1/demo/retrain",
                "/docs", "/docs/oauth2-redirect", "/redoc", "/openapi.json"}
    assert paths == expected, f"unexpected routes: {paths - expected}"
    for p in paths:
        assert not re.search(r"pay(out|ment_request)|collect|transfer|refund|sms|notify|message|send", p.replace("/v1/events/payment", ""))


def test_only_outbound_calls_are_the_llm_gateway():
    """No code outside core/llm.py talks to the network (no payment, SMS or messaging client)."""
    pat = re.compile(r"^\s*(import|from)\s+(requests|httpx|urllib|smtplib|twilio|aiohttp|groq|google\.genai)\b", re.M)
    offenders = []
    for f in list((ROOT / "core").glob("*.py")) + list((ROOT / "api").glob("*.py")):
        if f.name != "llm.py" and pat.search(f.read_text()):
            offenders.append(f.name)
    assert offenders == []
    assert llm.TASKS == {"match_name", "rephrase_card", "tone_check"}      # the LLM only matches names and checks text


def test_shopkeeper_strings_never_use_banned_wording():
    strings = json.loads(config.I18N_PATH.read_text(encoding="utf-8"))["en"]
    for k, v in strings.items():
        for b in BANNED:
            assert b not in v.lower(), (k, v)
    for f in (ROOT / "web" / "src").rglob("*.tsx"):
        visible = re.sub(r"[A-Z][A-Za-z]+(?=[\s,}/])", "", f.read_text())   # ignore identifiers like CalendarClock
        visible = re.sub(r'"[a-z0-9]+(?:_[a-z0-9]+)+"', "", visible)          # ignore snake_case keys like "owner_lending"
        for b in ("loan", "lending", "credit line", "offer credit", "starter credit"):
            assert b not in visible.lower(), (f.name, b)


def test_judge_blocks_banned_wording():
    facts = {"allowed_amounts_paise": [10_000]}
    for text in ("We can give Lakshmi a loan of ₹100", "Lend ₹100 to Lakshmi?", "Open a credit line of ₹100", "Offer credit of ₹100?"):
        assert not judge.stage1(text, facts)["ok"], text
    assert judge.stage1("Allow Lakshmi N udhaar up to ₹100?", facts)["ok"]


def test_ingesting_a_payment_never_writes_the_ledger(conn, tmp_path):
    from core import graph, ledger
    cid = ledger.add_customer(conn, "S1", "Ramesh dudh wala")
    ledger.add_udhaar(conn, "S1", cid, 45_000, given_at="2026-11-08T10:00:00+05:30")
    flow = graph.PaymentFlow(tmp_path / "test.db", mode="replay")
    flow.ingest({"txn_id": "T1", "shop_id": "S1", "payer_vpa": "9849012345@ybl", "payer_name": "RAMESH K",
                 "amount_paise": 45_000, "app": "PhonePe", "status": "SUCCESS", "ts": "2026-11-14T09:00:00+05:30"})
    assert conn.execute("SELECT COUNT(*) FROM allocations").fetchone()[0] == 0      # nothing until the tap
