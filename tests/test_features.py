import numpy as np
import pandas as pd
import pytest

from core.features import FEATURES, build, credit_features, payment_features

CUT = pd.Timestamp("2026-11-14T00:00:00+05:30")


def pays(key, days_ago, amount=20_000):
    return pd.DataFrame({"payer_key": key, "ts": [CUT - pd.Timedelta(days=d) for d in days_ago], "amount_paise": amount})


def test_hand_built_weekly_customer():
    df = pays("lakshmi", [3, 10, 17, 24, 31, 38, 45, 52, 59, 66, 73, 80, 87, 94])
    f = payment_features(df, CUT).loc["lakshmi"]
    assert f["n_pay_90d"] == 13
    assert f["recency_days"] == pytest.approx(3)
    assert f["tenure_days"] == pytest.approx(94)
    assert f["gap_std_days"] == pytest.approx(0)
    assert f["max_gap_days"] == pytest.approx(7)
    assert f["active_weeks_share"] == pytest.approx(1.0)
    assert f["median_ticket_paise"] == 20_000


def test_no_future_leakage():
    past = pays("a", [5, 12, 19])
    future = pays("a", [-1, -3, -10], amount=99_999)      # after the cutoff
    f1 = build(past, CUT)
    f2 = build(pd.concat([past, future]), CUT)
    pd.testing.assert_frame_equal(f1, f2)
    # credit outcomes whose due date is after the cutoff are not used either
    credit = pd.DataFrame({"payer_key": ["a", "a"],
                           "given_at": [CUT - pd.Timedelta(days=40), CUT - pd.Timedelta(days=3)],
                           "due_at": [CUT - pd.Timedelta(days=26), CUT + pd.Timedelta(days=11)],
                           "repaid_at": [CUT - pd.Timedelta(days=30), CUT + pd.Timedelta(days=1)]})
    cf = credit_features(credit, CUT)
    assert cf.loc["a", "n_prior_credit"] == 1 and cf.loc["a", "prior_ontime_rate"] == 1.0


def test_never_had_credit_is_nan():
    f = build(pays("b", [1, 2, 3]), CUT)
    assert np.isnan(f.loc["b", "prior_ontime_rate"])


def test_feature_list_has_no_personal_attributes():
    banned = {"name", "group", "grp", "gender", "location", "community", "religion", "caste", "khata_name", "payer_name"}
    assert not banned & {f.lower() for f in FEATURES}
