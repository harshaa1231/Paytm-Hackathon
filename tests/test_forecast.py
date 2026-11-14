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



def test_one_open_udhaar(conn):
    import pytest
    import config
    from core import ledger
    if not (config.MODELS_DIR / forecast.MODEL_FILE).exists():
        pytest.skip("models not trained")
    cid = ledger.add_customer(conn, "S1", "Ramesh")
    ledger.add_udhaar(conn, "S1", cid, 45_000, given_at="2026-11-10T10:00:00+05:30")
    out = forecast.shop_forecast(conn, "S1", "2026-11-14T09:30:00+05:30")
    assert out["status"] == "ok" and out["n_open"] == 1 and out["few"] is True and out["total_paise"] == 45_000
    assert 0 <= out["low_paise"] <= out["expected_paise"] <= out["high_paise"] <= 45_000
    assert {out["low_paise"], out["high_paise"]} <= {0, 45_000}     # one udhaar: either it comes back or it doesn't
