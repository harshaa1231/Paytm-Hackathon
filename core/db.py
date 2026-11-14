"""SQLite schema + connection helper. Every query uses ? parameters, never f-strings with input."""
from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import config
from core.timeutil import now_iso

SCHEMA = """
CREATE TABLE IF NOT EXISTS shops(
  id TEXT PRIMARY KEY, name TEXT NOT NULL, shop_type TEXT NOT NULL DEFAULT 'kirana', created_at TEXT);
CREATE TABLE IF NOT EXISTS customers(
  id TEXT PRIMARY KEY, shop_id TEXT NOT NULL, khata_name TEXT NOT NULL, created_at TEXT);
CREATE TABLE IF NOT EXISTS payments(
  txn_id TEXT PRIMARY KEY, shop_id TEXT NOT NULL, payer_vpa TEXT, payer_name TEXT,
  amount_paise INTEGER NOT NULL CHECK(amount_paise > 0), app TEXT, status TEXT NOT NULL, ts TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS udhaar(
  id TEXT PRIMARY KEY, shop_id TEXT NOT NULL, customer_id TEXT NOT NULL,
  amount_paise INTEGER NOT NULL CHECK(amount_paise > 0), given_at TEXT NOT NULL, due_at TEXT NOT NULL,
  status TEXT NOT NULL DEFAULT 'open', closed_at TEXT);
CREATE TABLE IF NOT EXISTS allocations(
  id INTEGER PRIMARY KEY AUTOINCREMENT, txn_id TEXT NOT NULL, udhaar_id TEXT NOT NULL,
  amount_paise INTEGER NOT NULL, kind TEXT NOT NULL DEFAULT 'clear', created_at TEXT);
CREATE TABLE IF NOT EXISTS advances(
  id INTEGER PRIMARY KEY AUTOINCREMENT, shop_id TEXT NOT NULL, customer_id TEXT NOT NULL,
  txn_id TEXT NOT NULL, amount_paise INTEGER NOT NULL, created_at TEXT);
CREATE TABLE IF NOT EXISTS vpa_map(
  shop_id TEXT NOT NULL, payer_vpa TEXT NOT NULL, customer_id TEXT NOT NULL, confirmed_at TEXT,
  PRIMARY KEY(shop_id, payer_vpa));
CREATE TABLE IF NOT EXISTS match_examples(
  id INTEGER PRIMARY KEY AUTOINCREMENT, shop_id TEXT NOT NULL, payer_name TEXT, khata_name TEXT,
  label TEXT NOT NULL CHECK(label IN ('match','not_match')), created_at TEXT);
CREATE TABLE IF NOT EXISTS credit_offers(
  id INTEGER PRIMARY KEY AUTOINCREMENT, shop_id TEXT NOT NULL, customer_id TEXT, payer_vpa TEXT,
  amount_paise INTEGER NOT NULL, step INTEGER NOT NULL, offered_at TEXT, decision TEXT, decided_at TEXT,
  score REAL);
CREATE TABLE IF NOT EXISTS outcomes(
  udhaar_id TEXT PRIMARY KEY, repaid_on_time INTEGER NOT NULL, days_to_repay REAL,
  observed_at TEXT, voided INTEGER NOT NULL DEFAULT 0);
CREATE TABLE IF NOT EXISTS events(
  id INTEGER PRIMARY KEY AUTOINCREMENT, ts TEXT NOT NULL, shop_id TEXT, type TEXT NOT NULL, payload_json TEXT);
CREATE TABLE IF NOT EXISTS cards(
  card_id TEXT PRIMARY KEY, shop_id TEXT NOT NULL, txn_id TEXT, type TEXT NOT NULL,
  payload_json TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'pending',
  created_at TEXT, decided_at TEXT, decision_json TEXT);
CREATE TABLE IF NOT EXISTS consents(
  shop_id TEXT NOT NULL, payer_vpa TEXT NOT NULL, consent INTEGER NOT NULL CHECK(consent IN (0,1)), recorded_at TEXT,
  PRIMARY KEY(shop_id, payer_vpa));
CREATE TABLE IF NOT EXISTS demo_queue(
  seq INTEGER PRIMARY KEY, shop_id TEXT NOT NULL, label TEXT, payload_json TEXT NOT NULL,
  ingested INTEGER NOT NULL DEFAULT 0);
CREATE INDEX IF NOT EXISTS ix_pay_shop_ts ON payments(shop_id, ts);
CREATE INDEX IF NOT EXISTS ix_udhaar_cust ON udhaar(shop_id, customer_id);
CREATE INDEX IF NOT EXISTS ix_alloc_txn ON allocations(txn_id);
CREATE INDEX IF NOT EXISTS ix_alloc_udhaar ON allocations(udhaar_id);
CREATE INDEX IF NOT EXISTS ix_cust_shop ON customers(shop_id);
"""


def connect(path: str | Path | None = None) -> sqlite3.Connection:
    conn = sqlite3.connect(str(path or config.DB_PATH), timeout=10, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def init_schema(conn: sqlite3.Connection) -> None:
    conn.executescript(SCHEMA)
    conn.commit()


def log_event(conn: sqlite3.Connection, type_: str, payload: dict, shop_id: str | None = None) -> None:
    """Audit log. Callers must pass already-masked VPAs (core.privacy.mask_vpa)."""
    conn.execute(
        "INSERT INTO events(ts, shop_id, type, payload_json) VALUES (?,?,?,?)",
        (now_iso(), shop_id, type_, json.dumps(payload, default=str, ensure_ascii=False)),
    )
    conn.commit()


def recent_events(conn: sqlite3.Connection, shop_id: str | None = None, limit: int = 50) -> list[dict]:
    if shop_id:
        rows = conn.execute(
            "SELECT * FROM events WHERE shop_id=? ORDER BY id DESC LIMIT ?", (shop_id, limit)).fetchall()
    else:
        rows = conn.execute("SELECT * FROM events ORDER BY id DESC LIMIT ?", (limit,)).fetchall()
    out = []
    for r in rows:
        d = dict(r)
        d["payload"] = json.loads(d.pop("payload_json") or "{}")
        out.append(d)
    return out
