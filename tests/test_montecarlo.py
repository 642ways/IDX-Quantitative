import json

import numpy as np
import pandas as pd
import pytest

from idxquant.config import CONFIG
from idxquant.montecarlo import (
    block_indices,
    calibrate_long,
    calibrate_short,
    calibration_buckets,
    simulate_pair,
    simulate_play,
    trading_days,
)
from idxquant.pairs import Pair
from idxquant.plays import Play
from idxquant.trading import net_return


def rng(seed=1):
    return np.random.default_rng(seed)


def bars(seed=1, days=600, sigma=0.015, drift=0.0, start=2000.0):
    random = rng(seed)
    close = start * np.exp(np.cumsum(random.normal(drift, sigma, days)))
    return pd.DataFrame(
        {
            "open": close,
            "high": close * (1 + sigma / 3),
            "low": close * (1 - sigma / 3),
            "close": close,
            "adj_close": close,
            "volume": 1e6,
        },
        index=pd.bdate_range("2024-01-01", periods=days),
    )


def play(kind="long", days=365):
    return Play("AAAA", kind, 1900, 2000, 2400, 1700, days, "why", 0.2, 0.15, 1.3, None)


def test_blocks_are_contiguous_runs_of_history():
    indices = block_indices(100, paths=50, days=20, block=5, rng=rng())
    assert indices.shape == (50, 20)
    assert (np.diff(indices[:, :5], axis=1) == 1).all()
    assert indices.min() >= 0 and indices.max() < 100


def test_probabilities_sum_to_one():
    result = simulate_play(bars(), 2000, 1700, 2400, 60, rng(), paths=2000)
    assert result["target_prob"] + result["stop_prob"] + result["neither_prob"] == pytest.approx(1.0)


def test_same_seed_gives_same_answer():
    first = simulate_play(bars(), 2000, 1700, 2400, 60, rng(7), paths=2000)
    second = simulate_play(bars(), 2000, 1700, 2400, 60, rng(7), paths=2000)
    assert first == second


def test_quiet_stock_hits_nothing_and_loses_only_fees():
    result = simulate_play(bars(sigma=0.0001), 2000, 1700, 2400, 20, rng(), paths=2000)
    assert result["neither_prob"] == 1.0
    assert result["expected_return"] == pytest.approx(net_return(2000, 2000), abs=0.002)


def test_unreachable_target_has_no_odds():
    result = simulate_play(bars(), 2000, 1700, 2_000_000, 20, rng(), paths=2000)
    assert result["target_prob"] == 0.0


def test_day_hitting_both_levels_counts_as_stop():
    index = pd.bdate_range("2024-01-01", periods=100)
    wide = pd.DataFrame({"high": 3000.0, "low": 1000.0, "close": 2000.0}, index=index)
    result = simulate_play(wide, 2000, 1700, 2400, 10, rng(), paths=500)
    assert result["stop_prob"] == 1.0


def test_past_trend_is_not_projected_forward():
    trending = bars(sigma=0.012, drift=0.004)
    result = simulate_play(trending, 2000, 1800, 2220, 250, rng(), paths=4000)
    assert result["target_prob"] == pytest.approx(result["stop_prob"], abs=0.08)


def test_more_volatile_stock_reaches_levels_more_often():
    quiet = simulate_play(bars(sigma=0.008), 2000, 1700, 2400, 60, rng(), paths=4000)
    wild = simulate_play(bars(sigma=0.03), 2000, 1700, 2400, 60, rng(), paths=4000)
    assert wild["neither_prob"] < quiet["neither_prob"]


def test_outcome_range_is_ordered_and_costed():
    result = simulate_play(bars(), 2000, 1700, 2400, 60, rng(), paths=4000)
    assert result["return_p10"] <= result["return_p50"] <= result["return_p90"]
    assert result["return_p90"] <= net_return(2000, 2400) + 1e-9
    assert result["return_p10"] >= net_return(2000, 1700) - 1e-9


def test_results_are_json_safe():
    json.dumps(simulate_play(bars(), 2000, 1700, 2400, 60, rng(), paths=500), allow_nan=False)


def chart_for(**overrides):
    args = {"entry": 2000, "stop": 1700, "target": 2400, "days": 120}
    result = simulate_play(bars(), *args.values(), rng(), paths=2000, with_chart=True, **overrides)
    return result["chart"]


def test_no_chart_unless_asked():
    assert "chart" not in simulate_play(bars(), 2000, 1700, 2400, 60, rng(), paths=500)


def test_chart_runs_from_entry_to_the_time_limit():
    chart = chart_for()
    assert chart["days"][0] == 0
    assert chart["days"][-1] == 120
    assert chart["p50"][0] == 2000
    assert len(chart["days"]) == len(chart["p10"]) == len(chart["p50"]) == len(chart["p90"])
    assert len(chart["days"]) <= 62


def test_chart_band_stays_between_stop_and_target_once_trades_exit():
    chart = chart_for()
    assert min(chart["p10"]) >= 1700
    assert max(chart["p90"]) <= 2400
    assert all(low <= mid <= high for low, mid, high in zip(chart["p10"], chart["p50"], chart["p90"]))


def test_sample_paths_end_at_their_outcome():
    paths = chart_for()["paths"]
    assert len(paths) == CONFIG.mc_chart_paths
    assert {path["outcome"] for path in paths} == {"target", "stop", "time"}
    for path in paths:
        assert path["points"][0] == [0, 2000]
        day, price = path["points"][-1]
        if path["outcome"] == "target":
            assert price == 2400
        elif path["outcome"] == "stop":
            assert price == 1700
        else:
            assert day == 120


def test_sample_path_days_only_move_forward():
    for path in chart_for()["paths"]:
        days = [point[0] for point in path["points"]]
        assert days == sorted(set(days))


def test_short_play_chart_keeps_every_day():
    result = simulate_play(bars(), 2000, 1700, 2400, 10, rng(), paths=500, with_chart=True)
    assert result["chart"]["days"] == list(range(11))


def test_chart_is_json_safe():
    json.dumps(chart_for(), allow_nan=False)


def test_pair_can_draw_a_chart():
    a, b, pair, other, _ = active_pair(8.0)
    entry, stop, target = levels(pair, other)
    result = simulate_pair(a, b, pair, entry, stop, target, 16, other, rng(), paths=500, with_chart=True)
    assert len(result["chart"]["paths"]) == CONFIG.mc_chart_paths


def test_time_limits_become_trading_days():
    assert trading_days(play("long", 365)) == 260
    assert trading_days(play("short", 14)) == 10
    assert trading_days(play("pair", 18)) == 18


def pair_data(half_life, days=504):
    random = rng(3)
    other = 7.5 + np.cumsum(random.normal(0, 0.01, days))
    phi = 0.5 ** (1 / half_life)
    noise = np.zeros(days)
    for day in range(1, days):
        noise[day] = phi * noise[day - 1] + random.normal(0, 0.01)
    index = pd.bdate_range("2024-01-01", periods=days)
    return pd.Series(other + noise, index=index), pd.Series(other, index=index), float(noise.std())


def active_pair(half_life):
    a, b, std = pair_data(half_life)
    pair = Pair("AAAA", "BBBB", 1.0, 0.0, 0.01, half_life, -2.2, 0.0, std)
    other = float(np.exp(b.iloc[-1]))
    return a, b, pair, other, std


def levels(pair, other):
    fair = other
    entry = fair * np.exp(-2.2 * pair.spread_std)
    return entry, fair * np.exp(-3.5 * pair.spread_std), fair * np.exp(-0.5 * pair.spread_std)


def test_fast_reverting_pair_mostly_hits_target():
    a, b, pair, other, _ = active_pair(5.0)
    entry, stop, target = levels(pair, other)
    result = simulate_pair(a, b, pair, entry, stop, target, 20, other, rng(), paths=4000)
    assert result["target_prob"] > result["stop_prob"]


def test_slower_reversion_gives_lower_odds():
    a, b, pair, other, _ = active_pair(5.0)
    entry, stop, target = levels(pair, other)
    fast = simulate_pair(a, b, pair, entry, stop, target, 20, other, rng(), paths=4000)
    slow_pair = Pair("AAAA", "BBBB", 1.0, 0.0, 0.01, 200.0, -2.2, 0.0, pair.spread_std)
    slow = simulate_pair(a, b, slow_pair, entry, stop, target, 20, other, rng(), paths=4000)
    assert slow["target_prob"] < fast["target_prob"]


def test_pair_probabilities_sum_to_one():
    a, b, pair, other, _ = active_pair(8.0)
    entry, stop, target = levels(pair, other)
    result = simulate_pair(a, b, pair, entry, stop, target, 16, other, rng(), paths=1000)
    assert result["target_prob"] + result["stop_prob"] + result["neither_prob"] == pytest.approx(1.0)


def test_buckets_compare_prediction_with_reality():
    rows = [(0.1, True), (0.1, False), (0.5, True), (0.9, True)]
    buckets = calibration_buckets(rows)
    assert [b["count"] for b in buckets] == [2, 1, 1]
    assert buckets[0]["predicted"] == pytest.approx(0.1)
    assert buckets[0]["actual"] == pytest.approx(0.5)


def test_prediction_of_one_lands_in_the_top_bucket():
    assert calibration_buckets([(1.0, True)])[0]["count"] == 1


def test_no_rows_gives_no_buckets():
    assert calibration_buckets([]) == []


def test_calibration_is_honest_on_a_true_random_walk():
    prices = {name: bars(seed=i + 10, days=1400) for i, name in enumerate("ABCDEFGH")}
    result = calibrate_long(prices, paths=300)
    assert result["samples"] > 30
    assert result["mean_predicted"] == pytest.approx(result["mean_actual"], abs=0.1)


def test_calibration_uses_only_earlier_data():
    frame = bars(seed=2, days=900)
    altered = frame.copy()
    altered.iloc[-10:, :] *= 3
    first = calibrate_long({"A": frame}, paths=200)
    second = calibrate_long({"A": altered}, paths=200)
    assert first["mean_predicted"] == second["mean_predicted"]


def test_short_calibration_reports_samples():
    assert calibrate_short({"A": bars(seed=4, days=700)}, paths=200)["samples"] >= 0
