import shutil

import pytest
from fastapi.testclient import TestClient

import config
from core import graph


@pytest.fixture()
def client(tmp_path, monkeypatch):
    if not config.DB_SEED_PATH.exists():
        pytest.skip("seed DB missing (run python data/generate.py)")
    db_path = tmp_path / "api.db"
    shutil.copyfile(config.DB_SEED_PATH, db_path)
    monkeypatch.setattr(config, "DB_PATH", db_path)
    monkeypatch.setattr(config, "SHOP_KEYS", {"S001": "k1", "S002": "k2"})
    monkeypatch.setattr(config, "ADMIN_KEY", "adm")
    graph.reset_flows()
    from api import main
    main._hits.clear()
    with TestClient(main.app) as c:
        yield c
    graph.reset_flows()


H1 = {"X-Shop-Key": "k1"}
RAMESH = {"txn_id": "UPI-T-1", "mid": "S001", "payer_vpa": "9849012345@ybl", "payer_name": "RAMESH K",
          "amount_paise": 45000, "app": "PhonePe", "status": "SUCCESS", "ts": "2026-11-14T09:20:00+05:30"}


def test_health(client):
    r = client.get("/health")
    assert r.status_code == 200 and r.json()["status"] == "ok"
    assert r.headers["X-Content-Type-Options"] == "nosniff"


def test_payment_to_card_to_decision(client):
    r = client.post("/v1/events/payment", json=RAMESH, headers=H1)
    assert r.status_code == 200 and r.json()["status"] == "card_pending"
    card = r.json()["card"]
    assert card["card_id"] == "pay:UPI-T-1" and "₹450" in card["title"]
    cards = client.get("/v1/merchants/S001/cards", headers=H1).json()
    assert cards["bytes"] < 5_000                                  # small for low-end phones
    assert [c["type"] for c in cards["cards"]][:1] == ["who_paid"]
    assert {"who_to_trust", "coming_back"} <= {c["type"] for c in cards["cards"]}
    d = client.post("/v1/merchants/S001/decisions", json={"card_id": "pay:UPI-T-1", "action": "clear_full"}, headers=H1)
    assert d.status_code == 200 and d.json()["result"]["applied_paise"] == 45000
    again = client.post("/v1/merchants/S001/decisions", json={"card_id": "pay:UPI-T-1", "action": "clear_full"}, headers=H1)
    assert again.json()["status"] == "already_decided"


def test_duplicate_event_idempotent(client):
    client.post("/v1/events/payment", json=RAMESH, headers=H1)
    r = client.post("/v1/events/payment", json=RAMESH, headers=H1)
    assert r.json()["status"] == "duplicate"


def test_auth_and_scoping(client):
    assert client.get("/v1/merchants/S001/cards").status_code == 401
    assert client.get("/v1/merchants/S001/cards", headers={"X-Shop-Key": "k2"}).status_code == 401   # S002's key
    assert client.get("/v1/merchants/S999/cards", headers=H1).status_code == 403                     # not in pilot
    client.post("/v1/events/payment", json=RAMESH, headers=H1)
    # shop S002 can't see or decide S001's card
    r = client.post("/v1/merchants/S002/decisions", json={"card_id": "pay:UPI-T-1", "action": "clear_full"},
                    headers={"X-Shop-Key": "k2"})
    assert r.status_code == 404
    s2 = client.get("/v1/merchants/S002/cards", headers={"X-Shop-Key": "k2"}).json()
    assert all("Ramesh" not in c.get("title", "") for c in s2["cards"])


@pytest.mark.parametrize("bad", [
    {"amount_paise": 0}, {"amount_paise": -5}, {"amount_paise": 10**12}, {"payer_name": "x" * 200},
    {"txn_id": "a b c; DROP TABLE"}, {"mid": "../etc"}, {"status": "MAYBE"},
])
def test_input_validation(client, bad):
    assert client.post("/v1/events/payment", json={**RAMESH, **bad}, headers=H1).status_code == 422


def test_admin_routes_protected(client):
    assert client.post("/v1/admin/reset").status_code == 401
    assert client.post("/v1/admin/reset", headers={"X-Admin-Key": "adm"}).status_code == 200


def test_rate_limit(client):
    codes = [client.get("/v1/merchants/S001/cards", headers=H1).status_code for _ in range(config.RATE_LIMIT_PER_MIN + 2)]
    assert 429 in codes


def test_khata_event(client):
    e = {"entry_id": "K-1", "mid": "S001", "customer_ref": "c77", "khata_name": "Meena akka", "type": "udhaar",
         "amount_paise": 30000, "ts": "2026-11-14T08:00:00+05:30"}
    assert client.post("/v1/events/khata", json=e, headers=H1).json()["status"] == "recorded"
    assert client.post("/v1/events/khata", json=e, headers=H1).json()["status"] == "duplicate"


def test_cors_only_streamlit_origin(client):
    ok = client.options("/health", headers={"Origin": "http://localhost:8501", "Access-Control-Request-Method": "GET"})
    bad = client.options("/health", headers={"Origin": "https://evil.example", "Access-Control-Request-Method": "GET"})
    assert ok.headers.get("access-control-allow-origin") == "http://localhost:8501"
    assert bad.headers.get("access-control-allow-origin") is None
