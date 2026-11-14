"""Property test (Hypothesis): for ANY sequence of udhaar and payments, FIFO allocation never creates a negative
balance, a payment never allocates more than its amount, and the books always balance."""
import tempfile
from pathlib import Path

from hypothesis import given, settings
from hypothesis import strategies as st

from core import db, ledger

amounts = st.integers(min_value=1, max_value=500_000)


@settings(max_examples=60, deadline=None)
@given(udhaar=st.lists(amounts, min_size=1, max_size=5), payments=st.lists(amounts, min_size=1, max_size=6),
       partial=st.lists(st.booleans(), min_size=6, max_size=6))
def test_fifo_invariants(udhaar, payments, partial):
    conn = db.connect(Path(tempfile.mkdtemp()) / "p.db")
    db.init_schema(conn)
    ledger.add_shop(conn, "S1", "Prop shop")
    cid = ledger.add_customer(conn, "S1", "Customer", created_at="2026-10-01T09:00:00+05:30")
    uids = [ledger.add_udhaar(conn, "S1", cid, a, given_at=f"2026-11-0{i + 1}T10:00:00+05:30") for i, a in enumerate(udhaar)]
    applied_total = 0
    for i, amt in enumerate(payments):
        txn = f"T{i}"
        ledger.record_payment(conn, {"txn_id": txn, "shop_id": "S1", "payer_vpa": "x@ybl", "payer_name": "X",
                                     "amount_paise": amt, "app": "UPI", "status": "SUCCESS", "ts": "2026-11-14T09:00:00+05:30"})
        open_now = ledger.open_total(conn, "S1", cid)
        req = max(1, amt // 2) if partial[i] else None
        r = ledger.apply_payment(conn, "S1", cid, txn, req)
        asked = amt if req is None else req
        assert r["applied"] == min(asked, open_now)                    # takes what's owed, never more
        assert r["applied"] + r["leftover"] == amt                       # every paisa of the payment is accounted for
        assert ledger.net_applied(conn, txn) == r["applied"]            # allocations sum to what was applied
        applied_total += r["applied"]
    for u in uids:
        assert ledger.remaining(conn, u) >= 0                            # never a negative balance
    assert ledger.open_total(conn, "S1", cid) == sum(udhaar) - applied_total
    statuses = {r[0] for r in conn.execute("SELECT status FROM udhaar")}
    assert statuses <= {"open", "partial", "closed"}
    conn.close()
