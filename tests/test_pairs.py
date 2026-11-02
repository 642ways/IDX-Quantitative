import numpy as np
import pandas as pd
import pytest

from idxquant.pairs import analyse_pair, find_pairs, price_at_z, status

DAYS = 504


def walk(seed, start=7.0):
    rng = np.random.default_rng(seed)
    index = pd.bdate_range("2024-01-01", periods=DAYS)
    return pd.Series(start + np.cumsum(rng.normal(0, 0.012, DAYS)), index=index)


def mean_reverting_noise(seed, half_life=8):
    rng = np.random.default_rng(seed)
    phi = 0.5 ** (1 / half_life)
    noise = np.zeros(DAYS)
    for day in range(1, DAYS):
        noise[day] = phi * noise[day - 1] + rng.normal(0, 0.01)
    return noise


def cointegrated(seed=1):
    base = walk(seed)
    return base + mean_reverting_noise(seed + 100), base


def test_finds_known_cointegrated_pair():
    a, b = cointegrated()
    found = find_pairs({"A": a, "B": b}, {"A": "Coal", "B": "Coal"})
    assert len(found) == 1
    assert {found[0].a, found[0].b} == {"A", "B"}
    assert 3 <= found[0].half_life <= 30


def test_rejects_independent_random_walks():
    assert find_pairs({"A": walk(2), "B": walk(3)}, {"A": "Coal", "B": "Coal"}) == []


def test_only_tests_same_sector():
    a, b = cointegrated()
    assert find_pairs({"A": a, "B": b}, {"A": "Coal", "B": "Banks"}) == []


def test_flat_series_never_pairs():
    flat = pd.Series(7.0, index=walk(4).index)
    assert find_pairs({"A": walk(4), "B": flat}, {"A": "Coal", "B": "Coal"}) == []


def test_short_overlap_is_skipped():
    a, b = cointegrated()
    assert analyse_pair(a.iloc[:100], b.iloc[-100:]) is None


def test_each_pair_appears_once():
    a, b = cointegrated()
    found = find_pairs({"A": a, "B": b}, {"A": "Coal", "B": "Coal"})
    assert len({frozenset((p.a, p.b)) for p in found}) == len(found)


def test_status_bands():
    zs = (-2.5, -2.0, -1.5, -1.0, -0.5, 1.0)
    assert [status(z) for z in zs] == ["Active", "Active", "Watch", "Watch", "None", "None"]


def test_price_at_z_round_trip():
    a, b = cointegrated()
    pair = analyse_pair(a, b)
    price = price_at_z(pair, pair.z, np.exp(b.iloc[-1]))
    assert price == pytest.approx(np.exp(a.iloc[-1]))


def test_price_at_higher_z_is_higher():
    a, b = cointegrated()
    pair = analyse_pair(a, b)
    other = np.exp(b.iloc[-1])
    assert price_at_z(pair, -0.5, other) > price_at_z(pair, -3.5, other)
