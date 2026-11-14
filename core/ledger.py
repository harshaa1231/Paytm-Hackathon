"""Udhaar ledger: entries, FIFO repayment allocation, idempotency, undo, outcomes.

Rules (plan sections 6/P0 and 8):
- money is integer paise
- every query is scoped by shop_id
- a payment is applied at most once (idempotent on txn_id); only status SUCCESS counts
- payments clear the customer's OLDEST open udhaar first (FIFO); udhaar given after the payment is not eligible
- undo never deletes history: it writes compensating 'reversal' allocations
- when an udhaar closes, an `outcomes` row is written -> the ONLY training label for trust
"""
from __future__ import annotations

import sqlite3
import uuid
from datetime import timedelta

import config
from core.db import log_event
from core.privacy import mask_vpa
from core.timeutil import days_between, iso, normalize_ts, now_iso, parse


class LedgerError(ValueError):
    pass


# ------------------------------------------------------------------ shops / customers
def add_shop(conn: sqlite3.Connection, shop_id: str, name: str, shop_type: str = "kirana") -> None:
    conn.execute("INSERT OR IGNORE INTO shops(id, name, shop_type, created_at) VALUES (?,?,?,?)",
                 (shop_id, name, shop_type, now_iso()))
    conn.commit()


def add_customer(conn: sqlite3.Connection, shop_id: str, khata_name: str,
                 customer_id: str | None = None, created_at: str | None = None) -> str:
    cid = customer_id or f"C{uuid.uuid4().hex[:10]}"
    conn.execute("INSERT INTO customers(id, shop_id, khata_name, created_at) VALUES (?,?,?,?)",
                 (cid, shop_id, khata_name.strip()[: config.MAX_NAME_LEN], normalize_ts(created_at or now_iso())))
    conn.commit()
    return cid


def get_customer(conn: sqlite3.Connection, shop_id: str, customer_id: str) -> dict | None:
    r = conn.execute("SELECT * FROM customers WHERE shop_id=? AND id=?", (shop_id, customer_id)).fetchone()
    return dict(r) if r else None


# ------------------------------------------------------------------ udhaar
def add_udhaar(conn: sqlite3.Connection, shop_id: str, customer_id: str, amount_paise: int,
               given_at: str | None = None, due_days: int = config.ONTIME_DAYS,
               udhaar_id: str | None = None) -> str:
    if not isinstance(amount_paise, int) or amount_paise <= 0:
        raise LedgerError("udhaar amount must be a positive integer number of paise")
    if not get_customer(conn, shop_id, customer_id):
        raise LedgerError("customer not in this shop")
    given = normalize_ts(given_at or now_iso())
    due = iso(parse(given) + timedelta(days=due_days))
    uid = udhaar_id or f"U{uuid.uuid4().hex[:10]}"
    conn.execute(
        "INSERT INTO udhaar(id, shop_id, customer_id, amount_paise, given_at, due_at, status) VALUES (?,?,?,?,?,?, 'open')",
        (uid, shop_id, customer_id, amount_paise, given, due))
    conn.commit()
    return uid


def _allocated(conn: sqlite3.Connection, udhaar_id: str) -> int:
    r = conn.execute("SELECT COALESCE(SUM(amount_paise),0) FROM allocations WHERE udhaar_id=?", (udhaar_id,)).fetchone()
    return int(r[0])


def remaining(conn: sqlite3.Connection, udhaar_id: str) -> int:
    r = conn.execute("SELECT amount_paise FROM udhaar WHERE id=?", (udhaar_id,)).fetchone()
    if not r:
        raise LedgerError("unknown udhaar")
    return int(r[0]) - _allocated(conn, udhaar_id)


def open_udhaar(conn: sqlite3.Connection, shop_id: str, customer_id: str | None = None,
                as_of: str | None = None) -> list[dict]:
    """Open/partial udhaar with remaining amount, oldest first. as_of excludes udhaar given later."""
    q = ("SELECT u.*, u.amount_paise - COALESCE((SELECT SUM(a.amount_paise) FROM allocations a WHERE a.udhaar_id=u.id),0) AS remaining_paise "
         "FROM udhaar u WHERE u.shop_id=? AND u.status IN ('open','partial')")
    args: list = [shop_id]
    if customer_id:
        q += " AND u.customer_id=?"
        args.append(customer_id)
    if as_of:
        q += " AND u.given_at<=?"
        args.append(normalize_ts(as_of))
    q += " ORDER BY u.given_at, u.id"
    return [dict(r) for r in conn.execute(q, args).fetchall() if r["remaining_paise"] > 0]


def open_total(conn: sqlite3.Connection, shop_id: str, customer_id: str | None = None,
               as_of: str | None = None) -> int:
    return sum(u["remaining_paise"] for u in open_udhaar(conn, shop_id, customer_id, as_of))


def customers_with_open_udhaar(conn: sqlite3.Connection, shop_id: str, as_of: str | None = None) -> dict[str, list[dict]]:
    out: dict[str, list[dict]] = {}
    for u in open_udhaar(conn, shop_id, as_of=as_of):
        out.setdefault(u["customer_id"], []).append(u)
    return out


# ------------------------------------------------------------------ payments
def record_payment(conn: sqlite3.Connection, p: dict) -> bool:
    """Insert a UPI payment event. Returns False if txn_id was already seen (idempotent)."""
    amt = p["amount_paise"]
    if not isinstance(amt, int) or amt <= 0:
        raise LedgerError("amount_paise must be a positive int")
    try:
        conn.execute(
            "INSERT INTO payments(txn_id, shop_id, payer_vpa, payer_name, amount_paise, app, status, ts) VALUES (?,?,?,?,?,?,?,?)",
            (p["txn_id"], p["shop_id"], p.get("payer_vpa") or "", (p.get("payer_name") or "")[: config.MAX_NAME_LEN],
             amt, p.get("app") or "", (p.get("status") or "SUCCESS").upper(), normalize_ts(p["ts"])))
        conn.commit()
        return True
    except sqlite3.IntegrityError:
        return False


def get_payment(conn: sqlite3.Connection, shop_id: str, txn_id: str) -> dict | None:
    r = conn.execute("SELECT * FROM payments WHERE shop_id=? AND txn_id=?", (shop_id, txn_id)).fetchone()
    return dict(r) if r else None


def net_applied(conn: sqlite3.Connection, txn_id: str) -> int:
    r = conn.execute("SELECT COALESCE(SUM(amount_paise),0) FROM allocations WHERE txn_id=?", (txn_id,)).fetchone()
    return int(r[0])


def _refresh_status(conn: sqlite3.Connection, udhaar_id: str, at_ts: str) -> None:
    u = conn.execute("SELECT * FROM udhaar WHERE id=?", (udhaar_id,)).fetchone()
    rem = int(u["amount_paise"]) - _allocated(conn, udhaar_id)
    if rem <= 0:
        if u["status"] != "closed":
            conn.execute("UPDATE udhaar SET status='closed', closed_at=? WHERE id=?", (at_ts, udhaar_id))
            days = days_between(u["given_at"], at_ts)
            conn.execute(
                "INSERT OR REPLACE INTO outcomes(udhaar_id, repaid_on_time, days_to_repay, observed_at, voided) VALUES (?,?,?,?,0)",
                (udhaar_id, int(days <= config.ONTIME_DAYS), round(days, 2), now_iso()))
    else:
        new = "open" if rem == int(u["amount_paise"]) else "partial"
        if u["status"] == "closed":
            # undo of a clearance: the outcome label is no longer valid (kept, but voided)
            conn.execute("UPDATE outcomes SET voided=1 WHERE udhaar_id=?", (udhaar_id,))
        conn.execute("UPDATE udhaar SET status=?, closed_at=NULL WHERE id=?", (new, udhaar_id))


def apply_payment(conn: sqlite3.Connection, shop_id: str, customer_id: str, txn_id: str,
                  amount_paise: int | None = None) -> dict:
    """Allocate (part of) a SUCCESS payment to the customer's open udhaar, oldest first.

    Returns {"applied": int, "leftover": int, "allocations": [...], "status": "applied"|"already_applied"|"ignored"}.
    leftover = payment amount not used (overpayment or the part the shopkeeper treats as a purchase).
    """
    pay = get_payment(conn, shop_id, txn_id)
    if not pay:
        raise LedgerError("payment not found for this shop")
    if pay["status"] != "SUCCESS":
        return {"status": "ignored", "reason": f"status {pay['status']}", "applied": 0, "leftover": 0, "allocations": []}
    if not get_customer(conn, shop_id, customer_id):
        raise LedgerError("customer not in this shop")
    if net_applied(conn, txn_id) > 0:
        return {"status": "already_applied", "applied": net_applied(conn, txn_id), "leftover": 0, "allocations": []}
    to_apply = pay["amount_paise"] if amount_paise is None else amount_paise
    if not isinstance(to_apply, int) or to_apply <= 0 or to_apply > pay["amount_paise"]:
        raise LedgerError("amount to apply must be > 0 and <= the payment amount")

    allocs = []
    left = to_apply
    with conn:
        for u in open_udhaar(conn, shop_id, customer_id, as_of=pay["ts"]):
            if left <= 0:
                break
            take = min(left, u["remaining_paise"])
            conn.execute("INSERT INTO allocations(txn_id, udhaar_id, amount_paise, kind, created_at) VALUES (?,?,?, 'clear', ?)",
                         (txn_id, u["id"], take, now_iso()))
            allocs.append({"udhaar_id": u["id"], "amount_paise": take})
            left -= take
            _refresh_status(conn, u["id"], pay["ts"])
    applied = to_apply - left
    leftover = pay["amount_paise"] - applied
    log_event(conn, "ledger_apply", {"txn_id": txn_id, "customer_id": customer_id, "applied_paise": applied,
                                     "leftover_paise": leftover, "allocations": allocs}, shop_id)
    return {"status": "applied", "applied": applied, "leftover": leftover, "allocations": allocs}


def apply_cash(conn: sqlite3.Connection, shop_id: str, customer_id: str, amount_paise: int, ts: str) -> dict:
    """Shopkeeper records a cash repayment (no UPI payment row). Same FIFO rules."""
    if not isinstance(amount_paise, int) or amount_paise <= 0:
        raise LedgerError("amount must be a positive int")
    if not get_customer(conn, shop_id, customer_id):
        raise LedgerError("customer not in this shop")
    ts = normalize_ts(ts)
    txn_id = f"CASH-{uuid.uuid4().hex[:10]}"
    left, allocs = amount_paise, []
    with conn:
        for u in open_udhaar(conn, shop_id, customer_id, as_of=ts):
            if left <= 0:
                break
            take = min(left, u["remaining_paise"])
            conn.execute("INSERT INTO allocations(txn_id, udhaar_id, amount_paise, kind, created_at) VALUES (?,?,?, 'clear', ?)",
                         (txn_id, u["id"], take, ts))
            allocs.append({"udhaar_id": u["id"], "amount_paise": take})
            left -= take
            _refresh_status(conn, u["id"], ts)
    return {"txn_id": txn_id, "applied": amount_paise - left, "allocations": allocs}


def write_off(conn: sqlite3.Connection, shop_id: str, udhaar_id: str, ts: str) -> None:
    u = conn.execute("SELECT * FROM udhaar WHERE shop_id=? AND id=?", (shop_id, udhaar_id)).fetchone()
    if not u:
        raise LedgerError("unknown udhaar for this shop")
    with conn:
        conn.execute("UPDATE udhaar SET status='written_off', closed_at=? WHERE id=?", (normalize_ts(ts), udhaar_id))
        conn.execute("INSERT OR REPLACE INTO outcomes(udhaar_id, repaid_on_time, days_to_repay, observed_at, voided) VALUES (?,0,NULL,?,0)",
                     (udhaar_id, now_iso()))


def undo_payment(conn: sqlite3.Connection, shop_id: str, txn_id: str) -> dict:
    """Shopkeeper tapped by mistake: compensating entries restore the amount owed. History is kept."""
    pay = get_payment(conn, shop_id, txn_id)
    if not pay:
        raise LedgerError("payment not found for this shop")
    rows = conn.execute(
        "SELECT udhaar_id, SUM(amount_paise) AS net FROM allocations WHERE txn_id=? GROUP BY udhaar_id HAVING net>0",
        (txn_id,)).fetchall()
    if not rows:
        return {"status": "nothing_to_undo", "restored": 0}
    restored = 0
    with conn:
        for r in rows:
            conn.execute("INSERT INTO allocations(txn_id, udhaar_id, amount_paise, kind, created_at) VALUES (?,?,?, 'reversal', ?)",
                         (txn_id, r["udhaar_id"], -int(r["net"]), now_iso()))
            restored += int(r["net"])
            _refresh_status(conn, r["udhaar_id"], pay["ts"])
        conn.execute("DELETE FROM advances WHERE shop_id=? AND txn_id=?", (shop_id, txn_id))
    log_event(conn, "ledger_undo", {"txn_id": txn_id, "restored_paise": restored}, shop_id)
    return {"status": "undone", "restored": restored}


def record_advance(conn: sqlite3.Connection, shop_id: str, customer_id: str, txn_id: str, amount_paise: int) -> None:
    if amount_paise <= 0:
        return
    conn.execute("INSERT INTO advances(shop_id, customer_id, txn_id, amount_paise, created_at) VALUES (?,?,?,?,?)",
                 (shop_id, customer_id, txn_id, amount_paise, now_iso()))
    conn.commit()
    log_event(conn, "advance_recorded", {"txn_id": txn_id, "customer_id": customer_id, "amount_paise": amount_paise}, shop_id)


def payment_summary_for_log(p: dict) -> dict:
    """Payment dict safe for the audit log (masked VPA)."""
    return {"txn_id": p.get("txn_id"), "payer_name": p.get("payer_name"), "payer_vpa": mask_vpa(p.get("payer_vpa")),
            "amount_paise": p.get("amount_paise"), "app": p.get("app"), "status": p.get("status"), "ts": p.get("ts")}
