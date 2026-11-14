import numpy as np

from core import forecast


def test_seeded_and_deterministic():
    p, a = np.array([0.6, 0.3, 0.9, 0.5]), np.array([45_000, 120_000, 80_000, 60_000])
    r1, r2 = forecast.simulate(p, a), forecast.simulate(p, a)
    assert r1 == r2
    assert r1["expected"] == float(p @ a)
    assert r1["p10"] <= r1["expected"] <= r1["p90"]


def test_empty_is_zero():
    assert forecast.simulate(np.array([]), np.array([])) == {"expected": 0, "p10": 0, "p90": 0}


def test_shared_shock_widens_range():
    p, a = np.full(30, 0.5), np.full(30, 10_000)
    narrow = forecast.simulate(p, a, shock_sd=0.0)
    wide = forecast.simulate(p, a, shock_sd=1.0)
    assert (wide["p90"] - wide["p10"]) > (narrow["p90"] - narrow["p10"])


def test_shop_with_no_open_udhaar(conn):
    out = forecast.shop_forecast(conn, "S1", "2026-11-14T09:30:00+05:30")
    assert out["status"] == "nothing" and out["expected_paise"] == 0
