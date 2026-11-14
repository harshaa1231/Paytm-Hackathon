import pytest

from core import bias_experiment, learning, world
from data.generate import make_training_world


@pytest.fixture(scope="module")
def small_world(tmp_path_factory):
    p = tmp_path_factory.mktemp("w") / "small.db"
    make_training_world(seed=7, path=p, overrides={"n_shops": 40, "test_shops": 12, "cust_min": 40, "cust_max": 60},
                        quiet=True)
    w = world.load_world(str(p))
    yield w
    world.load_world.cache_clear()


def test_runs_end_to_end_and_returns_both_metrics(small_world):
    r = bias_experiment.run(small_world)
    for m in ("model_a", "model_b", "shopkeeper"):
        assert set(r[m]) >= {"A", "B", "gap_A_minus_B"}
        assert 0 <= r[m]["A"]["rec_rate"] <= 1
    assert 0.5 <= r["repayment_auc"]["model_b"] <= 1
    assert 0.5 <= r["repayment_auc"]["model_a"] <= 1
    assert r["caption"]


def test_group_is_never_a_feature(small_world):
    r = bias_experiment.run(small_world)
    assert "grp" not in r["setup"]["features"] and "group" not in r["setup"]["features"]
    assert "prior_ontime_rate" not in r["setup"]["features"]       # would leak the shopkeeper's decision


def test_world_repayment_independent_of_group(small_world):
    c = small_world["customers"]
    rates = c.groupby("grp")["f_ontime"].mean()
    assert abs(rates["A"] - rates["B"]) < 0.03          # repayment does not depend on group


def test_split_is_by_shop(small_world):
    c = small_world["customers"]
    train_shops = set(c.loc[c["is_test"] == 0, "shop_id"])
    test_shops = set(c.loc[c["is_test"] == 1, "shop_id"])
    assert train_shops and test_shops and not (train_shops & test_shops)


def test_matcher_replay_has_no_false_auto_matches():
    r = learning.replay_matcher(weeks=2, n_customers=30)
    assert len(r["weeks"]) == 2
    assert all(w["false_auto"] == 0 for w in r["weeks"])
    assert r["weeks"][1]["vpa_memory"] > 0                     # memory starts working in week 2
