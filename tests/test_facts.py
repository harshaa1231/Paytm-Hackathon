from facts import FACTS


def test_aidis_present_and_sourced():
    a = FACTS["aidis_2019"]
    assert "34% in rural India and 13% in urban India" in a
    assert a.endswith("https://www.mospi.gov.in/sites/default/files/press_release/press_note-AIDIS-240821.pdf")


def test_aidis_never_called_shopkeeper_credit():
    assert "shopkeeper" not in FACTS["aidis_2019"].lower()


def test_existing_facts_kept():
    for k in ("study", "in_group_favouritism", "random_borrowers", "revisits", "owner_lending", "paytm_merchants", "postpaid"):
        assert k in FACTS
