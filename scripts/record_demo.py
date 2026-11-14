"""Play the demo story once (same order as DEMO.md, same card refreshes as the app) on a TEMP copy of the seeded DB.

    DEMO_MODE=record .venv/bin/python scripts/record_demo.py   # calls Groq/Gemini, saves answers to cache/llm_cache.json
    DEMO_MODE=replay .venv/bin/python scripts/record_demo.py   # must answer from the cache only (no network)

Prints which provider answered each LLM call (from the audit log).
"""
from __future__ import annotations

import os
import shutil
import sys
import tempfile
import time
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
TMP = Path(tempfile.mkdtemp()) / "record.db"
os.environ["PAKKA_DB"] = str(TMP)
os.environ.setdefault("PAKKA_FAKE_NOW", "2026-11-14T09:30:00+05:30")

import config  # noqa: E402

shutil.copyfile(config.DB_SEED_PATH, TMP)

from core import db, graph, service  # noqa: E402

PAUSE = float(os.getenv("RECORD_PAUSE_S", "6" if config.DEMO_MODE != "replay" else "0"))
S = config.DEMO_SHOP_ID


def step(label: str, fn):
    out = fn()
    print(f"- {label}")
    time.sleep(PAUSE)
    return out


def main() -> None:
    print(f"mode={config.DEMO_MODE}  db={TMP}")
    conn = db.connect()
    flow = graph.PaymentFlow(TMP)
    refresh = lambda: service.get_cards(conn, S, "en")  # noqa: E731  (what the app does after every tap)

    step("open app", refresh)
    step("Ramesh pays", lambda: service.next_demo_payment(conn, S, "en", flow)); step("refresh", refresh)
    step("tap Clear ₹450", lambda: service.decide(conn, S, "pay:UPI-DEMO-0001", {"action": "clear_full"}, flow)); step("refresh", refresh)
    trust = [c for c in service.get_cards(conn, S, "en") if c["type"] == "who_to_trust" and not c.get("info")]
    if trust:
        step("tap Yes, allow ₹100", lambda: service.decide(conn, S, trust[0]["card_id"], {"action": "offer_yes"}, flow)); step("refresh", refresh)
    taps = {"UPI-DEMO-0003": {"action": "clear_part", "amount_paise": 30_000},
            "UPI-DEMO-0004": {"action": "clear_full"},
            "UPI-DEMO-0005": {"action": "clear_full", "extra": "advance"}}
    while service.demo_queue_left(conn, S):
        r = step("next payment", lambda: service.next_demo_payment(conn, S, "en", flow)); step("refresh", refresh)
        txn = r["payment"]["txn_id"]
        if r["status"] == "card_pending" and txn in taps:
            step(f"tap on {txn}", lambda: service.decide(conn, S, f"pay:{txn}", taps[txn], flow)); step("refresh", refresh)
    step("switch to medical shop", lambda: service.get_cards(conn, config.DEMO_SHOP2_ID, "en"))

    calls = [e["payload"] for e in reversed(db.recent_events(conn, None, 1000)) if e["type"] == "llm_call"]
    print("\nLLM calls by task and provider:")
    for (task, prov), n in sorted(Counter((c["task"], c["provider"]) for c in calls).items()):
        print(f"  {task:14} {prov:7} x{n}")
    errs = [c["error"] for c in calls if c.get("error") and c["provider"] not in ("groq", "gemini", "cache")]
    if errs:
        print("fallback reasons (first 3):", errs[:3])
    match = next((e["payload"] for e in db.recent_events(conn, S, 1000) if e["type"] == "match"
                  and e["payload"].get("txn_id") == "UPI-DEMO-0001"), {})
    card = service.cards.get_card(conn, S, "pay:UPI-DEMO-0001") or {}
    print("\nRamesh (ambiguous) match answered by:", (match.get("llm") or {}).get("provider"),
          "| judge check 2 by:", card.get("judge", {}).get("stage2", {}).get("provider"),
          "| shown text:", card.get("judge", {}).get("source"))


if __name__ == "__main__":
    main()
