import pytest

from core import graph, ledger


@pytest.fixture()
def shop(conn, tmp_path):
    r1 = ledger.add_customer(conn, "S1", "Ramesh dudh wala")
    ledger.add_udhaar(conn, "S1", r1, 45_000, given_at="2026-11-08T10:00:00+05:30")
    r2 = ledger.add_customer(conn, "S1", "Ramesh K. Rao")
    ledger.add_udhaar(conn, "S1", r2, 120_000, given_at="2026-11-04T10:00:00+05:30")
    flow = graph.PaymentFlow(tmp_path / "test.db", mode="replay")
    return flow, r1, r2


def p(txn="T1", amount=45_000, name="RAMESH K", status="SUCCESS"):
    return {"txn_id": txn, "shop_id": "S1", "payer_vpa": "9849012345@ybl", "payer_name": name,
            "amount_paise": amount, "app": "PhonePe", "status": status, "ts": "2026-11-14T09:00:00+05:30"}


def test_interrupt_then_resume_clears(conn, shop):
    flow, r1, _ = shop
    out = flow.ingest(p())
    assert out["status"] == "card_pending" and out["card"]["customer_id"] == r1
    assert flow.state("S1", "T1")["next"] == ["ask_shopkeeper"]           # paused for the tap
    assert ledger.open_total(conn, "S1", r1) == 45_000                   # nothing written before the tap
    res = flow.decide("S1", "T1", {"action": "clear_full"})
    assert res["status"] == "done" and ledger.open_total(conn, "S1", r1) == 0


def test_resume_twice_no_double_write(conn, shop):
    flow, r1, _ = shop
    flow.ingest(p(amount=20_000, name="RAMESH DUDH"))
    flow.decide("S1", "T1", {"action": "clear_part", "customer_id": r1, "amount_paise": 20_000})
    again = flow.decide("S1", "T1", {"action": "clear_part", "customer_id": r1, "amount_paise": 20_000})
    assert again["status"] == "already_decided"
    assert ledger.open_total(conn, "S1", r1) == 25_000
    n = conn.execute("SELECT COUNT(*) FROM allocations WHERE txn_id='T1'").fetchone()[0]
    assert n == 1


def test_duplicate_event_does_not_disturb_paused_card(conn, shop):
    flow, r1, _ = shop
    flow.ingest(p())
    dup = flow.ingest(p())
    assert dup["status"] == "duplicate"
    assert flow.state("S1", "T1")["next"] == ["ask_shopkeeper"]
    assert flow.decide("S1", "T1", {"action": "clear_full"})["status"] == "done"


def test_failed_status_ignored(conn, shop):
    flow, *_ = shop
    assert flow.ingest(p(status="FAILED"))["status"] == "ignored"


def test_purchase_no_card(conn, shop):
    flow, *_ = shop
    assert flow.ingest(p(name="VENKAT S", amount=12_000))["status"] == "purchase_no_card"


def test_not_him_stores_negative_example_and_no_ledger_change(conn, shop):
    flow, r1, _ = shop
    flow.ingest(p())
    flow.decide("S1", "T1", {"action": "not_him"})
    assert ledger.open_total(conn, "S1", r1) == 45_000
    row = conn.execute("SELECT label, khata_name FROM match_examples").fetchone()
    assert row["label"] == "not_match" and row["khata_name"] == "Ramesh dudh wala"


def test_confirm_learns_vpa_and_example(conn, shop):
    flow, r1, _ = shop
    flow.ingest(p())
    flow.decide("S1", "T1", {"action": "clear_full"})
    assert conn.execute("SELECT customer_id FROM vpa_map WHERE payer_vpa='9849012345@ybl'").fetchone()[0] == r1
    assert conn.execute("SELECT label FROM match_examples").fetchone()[0] == "match"
    # learning never writes trust labels: the only outcome row is the one the ledger wrote on closing
    assert conn.execute("SELECT COUNT(*) FROM outcomes").fetchone()[0] == 1


def test_pick_other_customer_records_not_match_for_proposed(conn, shop):
    flow, r1, r2 = shop
    flow.ingest(p())
    flow.decide("S1", "T1", {"action": "clear_part", "customer_id": r2, "amount_paise": 45_000})
    assert ledger.open_total(conn, "S1", r2) == 75_000
    labels = sorted(r[0] for r in conn.execute("SELECT label FROM match_examples"))
    assert labels == ["match", "not_match"]


def test_invalid_amount_rejected_then_valid_tap_works(conn, shop):
    flow, r1, _ = shop
    flow.ingest(p())
    bad = flow.decide("S1", "T1", {"action": "clear_part", "amount_paise": 99_999_999})
    assert bad["status"] == "rejected" and ledger.open_total(conn, "S1", r1) == 45_000
    assert flow.decide("S1", "T1", {"action": "clear_full"})["status"] == "done"


def test_recovers_after_restart(conn, shop, tmp_path):
    flow, r1, _ = shop
    flow.ingest(p())
    fresh = graph.PaymentFlow(tmp_path / "test.db", mode="replay")       # InMemorySaver lost
    assert fresh.decide("S1", "T1", {"action": "clear_full"})["status"] == "done"
    assert ledger.open_total(conn, "S1", r1) == 0
