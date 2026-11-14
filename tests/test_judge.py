from core import judge, ledger, llm
from core.schemas import RephraseAnswer, ToneVerdict

FACTS = {"allowed_amounts_paise": [45_000], "card_type": "who_paid", "shop_id": "S1"}


def test_amount_parsing():
    assert judge.amounts_in("Clear ₹450 of ₹1,25,000 and ₹12.50") == [45_000, 12_500_000, 1_250]


def test_stage1_passes_good_text():
    assert judge.stage1("Ramesh paid ₹450. Clear the ₹450 udhaar?", FACTS)["ok"]


def test_stage1_catches_wrong_amount():
    r = judge.stage1("Ramesh paid ₹540.", FACTS)
    assert not r["ok"] and "not a ledger value" in r["problems"][0]


def test_stage1_catches_phone_and_vpa():
    assert not judge.stage1("Call 9849012345", FACTS)["ok"]
    assert not judge.stage1("UPI 9849012345@ybl", FACTS)["ok"]
    assert judge.stage1("UPI 98******45@ybl", FACTS)["ok"]


def test_stage1_blocklist():
    assert not judge.stage1("Ramesh is a cheat", FACTS)["ok"]
    assert not judge.stage1("Muslim customer paid", FACTS)["ok"]


def test_stage1_requires_open_udhaar(conn):
    cid = ledger.add_customer(conn, "S1", "Ramesh")
    facts = {**FACTS, "requires_open_udhaar": True, "customer_id": cid}
    assert not judge.stage1("Clear ₹450?", facts, conn)["ok"]
    ledger.add_udhaar(conn, "S1", cid, 45_000)
    assert judge.stage1("Clear ₹450?", facts, conn)["ok"]


def test_bad_rephrase_falls_back_to_template(monkeypatch):
    def fake(task, prompt, schema, **k):
        if task == "rephrase_card":
            return RephraseAnswer(text="Ramesh ne ₹540 diye, clear karo"), {"provider": "groq", "error": None, "latency_ms": 1}
        return ToneVerdict(numbers_match=False, fair_and_polite=True, reason="540 wrong"), {"provider": "groq", "error": None, "latency_ms": 1}
    monkeypatch.setattr(llm, "call", fake)
    out = judge.judge_card("Ramesh paid ₹450.", FACTS, try_rephrase=True)
    assert out["source"] == "template" and out["text"] == "Ramesh paid ₹450."
    assert not out["stage1"]["ok"]


def test_good_rephrase_is_shown(monkeypatch):
    def fake(task, prompt, schema, **k):
        if task == "rephrase_card":
            return RephraseAnswer(text="Ramesh ne ₹450 diye. Udhaar clear karein?"), {"provider": "groq", "error": None, "latency_ms": 1}
        return ToneVerdict(numbers_match=True, fair_and_polite=True, reason="ok"), {"provider": "groq", "error": None, "latency_ms": 1}
    monkeypatch.setattr(llm, "call", fake)
    out = judge.judge_card("Ramesh paid ₹450.", FACTS, try_rephrase=True)
    assert out["source"] == "llm_rephrase" and "₹450" in out["text"]


def test_judge_unavailable_shows_template():
    out = judge.judge_card("Ramesh paid ₹450.", FACTS, try_rephrase=True, mode="replay")
    assert out["source"] == "template" and out["stage2"]["available"] is False


def test_rephrase_that_drops_the_question_or_an_amount_is_rejected(monkeypatch):
    template = "Lakshmi N paid you 26 times. Allow Lakshmi N udhaar up to ₹100?"
    facts = {"allowed_amounts_paise": [10_000], "card_type": "who_to_trust", "shop_id": "S1"}
    for bad in ("Lakshmi N ne 26 baar payment kiya, koi udhaar nahi hai.",          # question dropped, amount dropped
                "Lakshmi N ko ₹100 udhaar de do."):                                    # decides for the shopkeeper
        def fake(task, prompt, schema, _bad=bad, **k):
            if task == "rephrase_card":
                return RephraseAnswer(text=_bad), {"provider": "groq", "error": None, "latency_ms": 1}
            return ToneVerdict(numbers_match=True, fair_and_polite=True, reason="ok"), {"provider": "groq", "error": None, "latency_ms": 1}
        monkeypatch.setattr(llm, "call", fake)
        out = judge.judge_card(template, facts, try_rephrase=True)
        assert out["source"] == "template" and out["text"] == template


def test_keeps_meaning_checks():
    t = "About ₹20,300 of the ₹38,000 udhaar should come back (likely ₹11,500 to ₹28,300)."
    assert judge.keeps_meaning(t, "₹20,300 ka ₹38,000 wapas aayega") == ["rephrase dropped amount(s): ₹11500, ₹28300"]
    assert judge.keeps_meaning(t, "Lagbhag ₹20,300 / ₹38,000 aayega (shayad ₹11,500 se ₹28,300).") == []
