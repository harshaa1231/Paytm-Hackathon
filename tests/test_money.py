import pytest

from core.money import fmt_inr, round_to_hundred_rupees, rupees_to_paise


def test_lakh_grouping():
    assert fmt_inr(12_500_000) == "₹1,25,000"
    assert fmt_inr(3_800_000) == "₹38,000"
    assert fmt_inr(45_000) == "₹450"
    assert fmt_inr(100) == "₹1"
    assert fmt_inr(0) == "₹0"
    assert fmt_inr(1_000_000_000) == "₹1,00,00,000"


def test_paise_and_negative():
    assert fmt_inr(45_050) == "₹450.50"
    assert fmt_inr(-45_000) == "-₹450"
    assert fmt_inr(45_000, always_paise=True) == "₹450.00"


def test_rupees_to_paise_rejects_float():
    assert rupees_to_paise("450") == 45_000
    assert rupees_to_paise("12.5") == 1_250
    assert rupees_to_paise(100) == 10_000
    with pytest.raises(TypeError):
        rupees_to_paise(4.5)
    with pytest.raises(TypeError):
        fmt_inr(4.5)


def test_round_for_display():
    assert round_to_hundred_rupees(2_387_100) == 2_390_000
    assert round_to_hundred_rupees(2_384_999) == 2_380_000



def test_i18n_falls_back_to_english_per_key(monkeypatch):
    from core import i18n
    fake = {"en": {"btn_purchase": "Just a purchase", "btn_no": "No"}, "hi": {"btn_no": "नहीं"}}
    monkeypatch.setattr(i18n, "_strings", lambda: fake)
    assert i18n.t("btn_no", "hi") == "नहीं"                    # reviewed string used
    assert i18n.t("btn_purchase", "hi") == "Just a purchase"    # unreviewed key falls back to English
    assert i18n.t("btn_purchase", "te") == "Just a purchase"    # language with no strings at all
    assert i18n.coverage("hi") == (1, 2)
