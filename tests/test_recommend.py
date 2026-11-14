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
    for v in ("lakshmi@ybl", "few@ybl", "gone@ybl", "credit@ybl"):                 # all consented here
        conn.execute("INSERT INTO consents VALUES ('S1', ?, 1, '2026-10-01')", (v,))
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


# ---------------------------------------------------------------- DPDP consent + per-shop scoring
def test_only_consented_customers_are_suggested(shop):
    weekly(shop, "noconsent@ybl", "MEENA R", 26, start=500)              # just as regular as Lakshmi, but no consent
    weekly(shop, "declined@ybl", "GEETA P", 26, start=600)
    shop.execute("INSERT INTO consents VALUES ('S1','declined@ybl',0,'2026-10-01')")
    shop.commit()
    names = [i["display_name"] for i in recommend.hidden_regulars(shop, "S1", NOW)["items"]]
    assert names == ["Lakshmi N"]
    shop.execute("INSERT OR REPLACE INTO consents VALUES ('S1','noconsent@ybl',1,'2026-10-01')")
    shop.commit()
    assert "Meena R" in [i["display_name"] for i in recommend.hidden_regulars(shop, "S1", NOW)["items"]]


def test_trust_card_wording_and_consent_line(shop):
    c = service.trust_cards(shop, "S1", mode="replay")[0]
    assert c["body"].endswith("Allow Lakshmi N udhaar up to ₹100?")
    assert c["note"] == "✓ Agreed to share their payment record with this shop"
    text = " ".join([c["title"], c["body"], c["note"]] + [a["label"] for a in c["actions"]]).lower()
    for banned in ("loan", "lend", "credit line", "offer credit"):
        assert banned not in text


def test_scores_use_only_this_shops_payments(shop):
    # the same person also pays at another shop, often; that must not leak into S1's score or reach S1 at all
    weekly(shop, "lakshmi@ybl", "LAKSHMI N", 40, shop="S2", every=1.0, last_ago=0.5, start=900)
    shop.execute("INSERT INTO consents VALUES ('S2','lakshmi@ybl',1,'2026-10-01')")
    weekly(shop, "s2only@ybl", "ONLY AT S2", 26, shop="S2", start=950)
    shop.execute("INSERT INTO consents VALUES ('S2','s2only@ybl',1,'2026-10-01')")
    shop.commit()
    X = recommend.scored_payers(shop, "S1", NOW)
    assert "s2only@ybl" not in X.index
    assert X.loc["lakshmi@ybl", "n_total"] == 26                         # only S1's 26 payments, not S2's 40
    s1 = recommend.hidden_regulars(shop, "S1", NOW)["items"]
    assert [i["n_total"] for i in s1 if i["display_name"] == "Lakshmi N"] == [26]


def test_consent_is_per_shop(shop):
    weekly(shop, "lakshmi@ybl", "LAKSHMI N", 26, shop="S2", start=700)     # consented at S1 only
    assert recommend.consented_vpas(shop, "S2") == set()
    assert recommend.scored_payers(shop, "S2", NOW).empty



def test_consent_withdrawn_removes_card_and_stops_scoring(shop):
    assert [c["title"] for c in service.trust_cards(shop, "S1", mode="replay")] == ["Lakshmi N pays you regularly"]
    shop.execute("UPDATE consents SET consent=0 WHERE shop_id='S1' AND payer_vpa='lakshmi@ybl'")
    shop.commit()
    assert service.trust_cards(shop, "S1", mode="replay") == []
    assert "lakshmi@ybl" not in recommend.scored_payers(shop, "S1", NOW).index      # not even scored
