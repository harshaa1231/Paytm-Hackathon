"""Matcher on hand-authored Indian name-variation cases. A false match costs a shopkeeper money, so precision > recall."""
import pytest

from experiments import matcher_eval


@pytest.fixture(scope="module")
def res():
    return matcher_eval.run(write=False)


def test_enough_cases(res):
    assert res["n_pairs"] >= 60 and res["n_should_not_auto_match"] >= 10


def test_precision_first(res):
    assert res["precision_auto"] >= 0.95
    assert res["false_match_rate"] <= 0.05


def test_same_name_different_people_never_auto_matched(res):
    two_people = [c for c in res["cases"] if "two people" in c["type"]]
    assert two_people and not any(c["auto"] for c in two_people)


def test_blank_and_injection_never_auto_matched(res):
    for c in res["cases"]:
        if c["type"] in ("blank name", "injection text"):
            assert not c["auto"]
