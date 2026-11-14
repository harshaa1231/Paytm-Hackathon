"""Indian name matching (first validation task). A false match costs a shopkeeper money, so precision > recall.
Part A: ~60 labelled same_person / different_person pairs. Part B: shops where near-identical names must stay ambiguous."""
import json
from pathlib import Path

import pytest

from experiments import matcher_eval

PAIRS = json.loads((Path(__file__).parent / "data" / "name_pairs.json").read_text())["pairs"]


@pytest.fixture(scope="module")
def res():
    return matcher_eval.run(write=False)


def test_pair_set_covers_indian_variation():
    assert 55 <= len(PAIRS) <= 70
    assert {p["label"] for p in PAIRS} == {"same_person", "different_person"}
    types = " ".join(p["type"] for p in PAIRS)
    for needed in ("transliteration", "v<->b", "initial", "reordered", "honorific", "descriptor", "blank", "hard negative"):
        assert needed in types, needed


def test_precision_first_on_pairs(res):
    a = res["part_a_labelled_pairs"]
    assert a["precision_at_auto_match"] >= 0.95
    assert a["false_match_rate"] <= 0.10


def test_blank_and_injection_never_auto_matched(res):
    for r in res["part_a_labelled_pairs"]["pairs"]:
        if "blank" in r["type"] or r["type"] == "injection text":
            assert not r["auto"], r["upi"]


def test_near_identical_names_in_one_shop_stay_ambiguous(res):
    b = res["part_b_shop_level"]
    two_people = [c for c in b["cases"] if "two people" in c["type"]]
    assert two_people and not any(c["auto"] for c in two_people)
    assert b["precision_auto"] >= 0.95
