from core import ladder
from core.ladder import LadderState, STEPS, classify, next_state, replay


def test_starts_at_100():
    assert LadderState().offer_paise == 10_000


def test_up_after_three_on_time():
    s = replay(["on_time", "on_time"])
    assert s.step == 0 and s.streak == 2
    s = next_state(s, "on_time")
    assert s.step == 1 and s.streak == 0 and s.offer_paise == 20_000


def test_late_drops_one_step():
    s = replay(["on_time"] * 6)            # -> step 2 (Rs400)
    assert s.offer_paise == 40_000
    s = next_state(s, "late")
    assert s.offer_paise == 20_000 and s.streak == 0
    assert next_state(LadderState(), "late").step == 0   # never below the first step


def test_slightly_late_resets_streak_only():
    s = replay(["on_time", "on_time", "slightly_late", "on_time"])
    assert s.step == 0 and s.streak == 1


def test_unpaid_30_freezes_until_cleared():
    s = next_state(replay(["on_time"] * 3), "unpaid_30")
    assert s.frozen and s.offer_paise is None
    assert next_state(s, "on_time").frozen            # no growth while frozen
    s = next_state(s, "cleared")
    assert not s.frozen and s.offer_paise == 20_000


def test_cap_at_1000():
    s = replay(["on_time"] * 30)
    assert s.offer_paise == 100_000 == STEPS[-1]


def test_switch_off():
    assert next_state(LadderState(), "switch_off").offer_paise is None


def test_classify():
    assert classify(10) == "on_time"
    assert classify(14) == "on_time"
    assert classify(18) == "slightly_late"
    assert classify(22) == "late"
    assert classify(None, days_open=31) == "unpaid_30"
    assert classify(None, days_open=5) == "open"
    assert ladder.config.LADDER_UP_AFTER_ONTIME == 3
