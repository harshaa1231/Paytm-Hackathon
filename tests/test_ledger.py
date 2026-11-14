import pytest

from core import ledger
from tests.conftest import pay


def setup_customer(conn, amounts, shop="S1", name="Ramesh dudh wala"):
    cid = ledger.add_customer(conn, shop, name)
    ids = []
    for i, a in enumerate(amounts):
        ids.append(ledger.add_udhaar(conn, shop, cid, a, given_at=f"2026-11-0{i + 1}T10:00:00+05:30"))
    return cid, ids


def test_exact_payment_closes_and_writes_outcome(conn):
    cid, (u1,) = setup_customer(conn, [45_000])
    pay(conn, "T1", 45_000)
    res = ledger.apply_payment(conn, "S1", cid, "T1")
    assert res["applied"] == 45_000 and res["leftover"] == 0
    assert ledger.open_total(conn, "S1", cid) == 0
    o = conn.execute("SELECT * FROM outcomes WHERE udhaar_id=?", (u1,)).fetchone()
    assert o["repaid_on_time"] == 1  # given 1 Nov, paid 14 Nov 09:00 -> < 14 days


def test_partial_payment_fifo(conn):
    cid, (u1, u2) = setup_customer(conn, [30_000, 50_000])
    pay(conn, "T1", 40_000)
    ledger.apply_payment(conn, "S1", cid, "T1")
    assert ledger.remaining(conn, u1) == 0          # oldest cleared first
    assert ledger.remaining(conn, u2) == 40_000     # remainder stays open
    st = {r["id"]: r["status"] for r in conn.execute("SELECT id,status FROM udhaar")}
    assert st[u1] == "closed" and st[u2] == "partial"


def test_overpayment_leaves_leftover(conn):
    cid, _ = setup_customer(conn, [20_000])
    pay(conn, "T1", 50_000)
    res = ledger.apply_payment(conn, "S1", cid, "T1")
    assert res["applied"] == 20_000 and res["leftover"] == 30_000


def test_idempotent_on_txn_id(conn):
    cid, (u1,) = setup_customer(conn, [45_000])
    p = pay(conn, "T1", 20_000)
    assert ledger.record_payment(conn, p) is False                # duplicate event ignored
    ledger.apply_payment(conn, "S1", cid, "T1")
    res2 = ledger.apply_payment(conn, "S1", cid, "T1")            # applied twice
    assert res2["status"] == "already_applied"
    assert ledger.remaining(conn, u1) == 25_000


@pytest.mark.parametrize("status", ["FAILED", "PENDING", "REFUNDED"])
def test_non_success_ignored(conn, status):
    cid, (u1,) = setup_customer(conn, [45_000])
    pay(conn, "T1", 45_000, status=status)
    res = ledger.apply_payment(conn, "S1", cid, "T1")
    assert res["status"] == "ignored"
    assert ledger.remaining(conn, u1) == 45_000


def test_udhaar_after_payment_not_eligible(conn):
    cid = ledger.add_customer(conn, "S1", "Ramesh")
    u_late = ledger.add_udhaar(conn, "S1", cid, 10_000, given_at="2026-11-14T12:00:00+05:30")
    pay(conn, "T1", 10_000, ts="2026-11-14T09:00:00+05:30")
    res = ledger.apply_payment(conn, "S1", cid, "T1")
    assert res["applied"] == 0 and ledger.remaining(conn, u_late) == 10_000


def test_undo_restores_owed_and_keeps_history(conn):
    cid, (u1,) = setup_customer(conn, [45_000])
    pay(conn, "T1", 45_000)
    ledger.apply_payment(conn, "S1", cid, "T1")
    res = ledger.undo_payment(conn, "S1", "T1")
    assert res["restored"] == 45_000
    assert ledger.remaining(conn, u1) == 45_000
    kinds = [r["kind"] for r in conn.execute("SELECT kind FROM allocations WHERE txn_id='T1' ORDER BY id")]
    assert kinds == ["clear", "reversal"]                                # nothing deleted
    assert conn.execute("SELECT voided FROM outcomes WHERE udhaar_id=?", (u1,)).fetchone()[0] == 1
    # after undo the payment can be applied again (e.g. to the right customer)
    assert ledger.apply_payment(conn, "S1", cid, "T1")["status"] == "applied"


def test_shop_scoping(conn):
    cid, _ = setup_customer(conn, [45_000], shop="S1")
    pay(conn, "T1", 45_000, shop_id="S2")
    with pytest.raises(ledger.LedgerError):
        ledger.apply_payment(conn, "S2", cid, "T1")        # S1's customer can't be used from S2
    with pytest.raises(ledger.LedgerError):
        ledger.apply_payment(conn, "S1", cid, "T1")        # S2's payment isn't visible from S1
    assert ledger.open_udhaar(conn, "S2") == []


def test_amounts_must_be_positive_int(conn):
    cid = ledger.add_customer(conn, "S1", "X")
    with pytest.raises(ledger.LedgerError):
        ledger.add_udhaar(conn, "S1", cid, 0)
    with pytest.raises(ledger.LedgerError):
        ledger.add_udhaar(conn, "S1", cid, 100.0)
