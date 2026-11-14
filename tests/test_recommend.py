"""Hidden-regular rule: excludes people who already have credit, < 12 payments, inactive, or new shops."""
from datetime import timedelta

import pytest

import config
from core import ledger, recommend, service, trust_model
from core.timeutil import iso, parse

NOW = "2026-11-14T09:30:00+05:30"


def weekly(conn, vpa, name, n, shop="S1", every=7.0, last_ago=2.0, start=0):
    for k in range(n):
        ts = iso(parse(NOW) - timedelta(days=last_ago + k * every))
        ledger.record_payment(conn, {"txn_id": f"{vpa}-{start + k}", "shop_id": shop, "payer_vpa": vpa, "payer_name": name,
                                     "amount_paise": 25_000, "app": "PhonePe", "status": "SUCCESS", "ts": ts})


@pytest.fixture()
def shop(conn, monkeypatch):
    if not (config.MODELS_DIR / trust_model.MODEL_FILE).exists():
        pytest.skip("models not trained (run python data/generate.py)")
    monkeypatch.setattr(config, "trust_threshold", lambda: 0.0)     # isolate the rule from the model's threshold
    weekly(conn, "lakshmi@ybl", "LAKSHMI N", 26)                    # hidden regular
    weekly(conn, "few@ybl", "FEW PAYS", 8)                           # < 12 in 90 days
    weekly(conn, "gone@ybl", "GONE AWAY", 20, last_ago=30)           # inactive > 14 days
    weekly(conn, "credit@ybl", "HAS CREDIT", 26)                     # already a credit customer
    cid = ledger.add_customer(conn, "S1", "Has credit")
    ledger.add_udhaar(conn, "S1", cid, 10_000, given_at="2026-09-01T10:00:00+05:30")
    conn.execute("INSERT INTO vpa_map VALUES ('S1','credit@ybl',?, '2026-09-10')", (cid,))
    conn.commit()
    return conn


def test_rule_exclusions(shop):
    names = [i["display_name"] for i in recommend.hidden_regulars(shop, "S1", NOW)["items"]]
    assert names == ["Lakshmi N"]


def test_offer_yes_moves_to_ladder_and_no_snoozes(shop):
    ref = recommend.payer_ref("S1", "lakshmi@ybl")
    res = service.decide_trust(shop, "S1", ref, "offer_yes")
    assert res["amount_paise"] == 10_000
    assert recommend.hidden_regulars(shop, "S1", NOW)["items"] == []          # now on the ladder
    row = shop.execute("SELECT step, decision FROM credit_offers").fetchone()
    assert row["step"] == 1 and row["decision"] == "yes"


def test_no_is_logged_but_never_a_label(shop):
    ref = recommend.payer_ref("S1", "lakshmi@ybl")
    service.decide_trust(shop, "S1", ref, "offer_no")
    assert shop.execute("SELECT COUNT(*) FROM outcomes").fetchone()[0] == 0
    assert recommend.hidden_regulars(shop, "S1", NOW)["items"] == []          # snoozed for 30 days


def test_new_shop_needs_four_weeks(conn):
    weekly(conn, "new@ybl", "NEW", 3, shop="S2", every=3)
    assert recommend.hidden_regulars(conn, "S2", NOW)["status"] == "need_more_data"


def test_card_ids_never_expose_vpa(shop):
    for c in service.trust_cards(shop, "S1", mode="replay"):
        assert "@" not in c["card_id"] and "lakshmi@ybl" not in str({k: c[k] for k in ("title", "body", "card_id")})
