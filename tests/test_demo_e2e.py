"""The full 8-payment demo morning, end to end, against the seeded DB and the committed LLM cache (replay: offline).
A snapshot: if any of these numbers change, the speaker notes in DEMO.md must change too."""
import shutil

import pytest

import config
from core import db, forecast, graph, service
from core.timeutil import now_iso

TAPS = {"UPI-DEMO-0001": {"action": "clear_full"}, "UPI-DEMO-0003": {"action": "clear_part", "amount_paise": 30_000},
        "UPI-DEMO-0004": {"action": "clear_full"}, "UPI-DEMO-0005": {"action": "clear_full", "extra": "advance"}}
EXPECTED = [  # txn, status, matcher stage, card title, applied on tap
    ("UPI-DEMO-0001", "card_pending", "llm", "Ramesh dudh wala paid ₹450", 45_000),
    ("UPI-DEMO-0002", "purchase_no_card", "no_match", None, None),
    ("UPI-DEMO-0003", "card_pending", "fuzzy_confident", "Suneeta tailor paid ₹300", 30_000),
    ("UPI-DEMO-0004", "card_pending", "vpa_memory", "Raju auto paid ₹600", 60_000),
    ("UPI-DEMO-0005", "card_pending", "llm", "Irfan bhai paid ₹500", 20_000),
    ("UPI-DEMO-0001", "duplicate", None, None, None),
    ("UPI-DEMO-0006", "ignored", None, None, None),
    ("UPI-DEMO-0007", "purchase_no_card", "no_match", None, None),
]


@pytest.fixture()
def demo(tmp_path, monkeypatch):
    if not config.DB_SEED_PATH.exists():
        pytest.skip("seed DB missing (run python data/generate.py)")
    p = tmp_path / "demo.db"
    shutil.copyfile(config.DB_SEED_PATH, p)
    monkeypatch.setattr(config, "DB_PATH", p)
    c = db.connect(p)
    yield c, graph.PaymentFlow(p, mode="replay")
    c.close()


def test_full_demo_morning_snapshot(demo):
    c, flow = demo
    assert service.shop_summary(c, "S001")["owed_total_paise"] == 3_845_000
    seen = []
    while service.demo_queue_left(c, "S001"):
        r = service.next_demo_payment(c, "S001", "en", flow)
        t = r["payment"]["txn_id"]
        applied = None
        if r["status"] == "card_pending" and t in TAPS:
            d = service.decide(c, "S001", f"pay:{t}", TAPS[t], flow)
            assert d["status"] == "done"
            applied = d["result"]["applied_paise"]
        seen.append((t, r["status"], (r.get("match") or {}).get("stage"), (r.get("card") or {}).get("title"), applied))
        if t == "UPI-DEMO-0001" and r["status"] == "card_pending":
            assert service.shop_summary(c, "S001")["owed_total_paise"] == 3_800_000      # the on-stage moment
    assert seen == EXPECTED

    trust = [x for x in service.get_cards(c, "S001") if x["type"] == "who_to_trust" and not x.get("info")]
    assert [x["title"] for x in trust] == ["Lakshmi N pays you regularly"]
    assert "₹100" in trust[0]["body"] and "?" in trust[0]["body"]
    assert service.decide(c, "S001", trust[0]["card_id"], {"action": "offer_yes"}, flow)["status"] == "done"

    assert service.shop_summary(c, "S001")["owed_total_paise"] == 3_690_000
    assert c.execute("SELECT SUM(amount_paise) FROM advances").fetchone()[0] == 30_000
    fc = forecast.shop_forecast(c, "S001", now_iso())
    assert {k: fc[k] for k in ("total_paise", "expected_paise", "low_paise", "high_paise", "n_open")} == \
        {"total_paise": 3_690_000, "expected_paise": 1_980_000, "low_paise": 1_140_000, "high_paise": 2_740_000, "n_open": 17}
