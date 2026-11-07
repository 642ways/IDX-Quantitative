from dataclasses import replace

import numpy as np
import pandas as pd
import pytest

from idxquant import learn
from idxquant.backtest import walk
from idxquant.config import CONFIG

DAYS = 1400


def prices(seed, days=DAYS, drift=0.0003):
    rng = np.random.default_rng(seed)
    close = 1000 * np.exp(np.cumsum(rng.normal(drift, 0.02, days)))
    return pd.DataFrame(
        {
            "open": close * (1 + rng.normal(0, 0.003, days)),
            "high": close * 1.015,
            "low": close * 0.985,
            "close": close,
            "adj_close": close,
            "volume": rng.uniform(1e6, 3e6, days),
        },
        index=pd.bdate_range("2020-01-01", periods=days),
    )


def market(days=DAYS):
    return prices(99, days)["close"]


def test_features_only_look_backwards():
    frame = prices(1)
    changed = frame.copy()
    changed.iloc[900:] *= 1.5
    day = 899
    assert learn.features(frame, market()).iloc[day].equals(learn.features(changed, market()).iloc[day])


def test_features_have_every_measure():
    columns = list(learn.features(prices(1), market()).columns)
    assert columns == [key for key, _ in learn.FEATURES]


def test_features_without_the_index_leave_market_measures_blank():
    row = learn.features(prices(1), None).iloc[-1]
    assert np.isnan(row["ihsg_3m"]) and np.isnan(row["ihsg_vol"])
    assert not np.isnan(row["ret_3m"])


@pytest.mark.parametrize("seed", range(6))
def test_outcome_follows_the_backtest_rules(seed):
    frame = prices(seed, 400)
    arrays = [frame[key].to_numpy() for key in ("open", "high", "low")]
    for day in range(0, 380, 7):
        close = frame["close"].iloc[day]
        stop, target = close * 0.95, close * 1.08
        expected = walk(frame, day, stop, target, 15)[2]
        last = min(day + 1 + 15, len(frame)) - 1
        assert learn.outcome(*arrays, day + 1, last, stop, target) == expected


def test_long_samples_are_only_labelled_when_the_whole_holding_period_has_passed():
    frame = prices(2)
    found = learn.samples({"AAAA": frame}, market())
    hold = CONFIG.long_days * 5 // 7
    labelled = found.dropna(subset=["known"])
    for _, row in labelled.iterrows():
        day = frame.index.get_loc(row["date"])
        assert row["known"] == frame.index[day + hold + 1]
    unlabelled = found[found["known"].isna()]
    assert all(frame.index.get_loc(d) + hold + 1 >= len(frame) for d in unlabelled["date"])


def test_forward_returns_match_the_prices():
    frame = prices(3)
    found = learn.samples({"AAAA": frame}, market())
    row = found.dropna(subset=["fwd_3m"]).iloc[0]
    day = frame.index.get_loc(row["date"])
    assert row["fwd_3m"] == pytest.approx(frame["adj_close"].iloc[day + 63] / frame["adj_close"].iloc[day] - 1)


def synthetic(rows=6000, seed=0, signal=True):
    """Past setups where a high 1-month return really does lead to the target more often."""
    rng = np.random.default_rng(seed)
    dates = pd.bdate_range("2015-01-01", periods=rows // 4).repeat(4)[:rows]
    data = {key: rng.normal(0, 1, rows) for key, _ in learn.FEATURES}
    chance = 1 / (1 + np.exp(-2 * data["ret_1m"])) if signal else np.full(rows, 0.4)
    frame = pd.DataFrame(data | {"ticker": [f"T{i % 40}" for i in range(rows)], "date": dates})
    frame["hit"] = rng.uniform(size=rows) < chance
    frame["known"] = frame["date"] + pd.Timedelta(days=380)
    frame["fwd_3m"] = data["ret_1m"] * 0.05 + rng.normal(0, 0.05, rows) if signal else rng.normal(0, 0.05, rows)
    frame["known_3m"] = frame["date"] + pd.Timedelta(days=95)
    frame["fwd_12m"] = rng.normal(0, 0.2, rows)
    return frame


def test_folds_never_train_on_outcomes_known_after_the_test_year_starts():
    data = synthetic()
    folds = list(learn.folds(data, "known", CONFIG))
    assert folds
    for year, train, test in folds:
        start = pd.Timestamp(year=year, month=1, day=1)
        assert data.loc[train, "known"].max() < start
        assert (data.loc[test, "date"].dt.year == year).all()


def test_odds_check_finds_a_real_signal():
    check = learn.odds_check(synthetic(), CONFIG)
    assert check["auc"] > 0.7
    assert check["brier"] < check["brier_base"]
    assert check["top_rate"] > check["overall_rate"] > check["bottom_rate"]
    assert check["importance"][0]["feature"] == "ret_1m"


def test_odds_check_reports_no_edge_when_there_is_none():
    check = learn.odds_check(synthetic(signal=False), CONFIG)
    assert 0.4 < check["auc"] < 0.6


def test_too_few_samples_give_no_model():
    assert learn.fit(synthetic(rows=200), CONFIG) is None
    assert learn.odds_check(synthetic(rows=200), CONFIG) is None


def test_odds_explain_which_measures_moved_them():
    data = synthetic()
    model = learn.fit(data, CONFIG)
    row = data[[key for key, _ in learn.FEATURES]].median() + 0.0
    row["ret_1m"] = 2.0
    odds = learn.odds(model, data, row)
    assert odds["prob"] > odds["base_rate"]
    assert odds["drivers"][0]["feature"] == "ret_1m"
    assert odds["drivers"][0]["effect"] > 0
    assert 0.9 < odds["drivers"][0]["percentile"] <= 1


def test_similar_setups_leave_out_the_same_stock_recently():
    data = synthetic()
    finder = learn.Similar(data, CONFIG)
    row = data[[key for key, _ in learn.FEATURES]].iloc[-1]
    today = data["date"].max()
    found = finder.query(row, "T1", today)
    assert found["count"] == CONFIG.ml_neighbours
    recent = [e for e in found["examples"] if e["ticker"] == "T1" and pd.Timestamp(e["date"]) > today - pd.Timedelta(days=365)]
    assert recent == []
    assert set(found["baseline"]) == {"median_3m", "up_3m", "median_12m", "up_12m"}


def test_similar_check_finds_a_real_signal():
    check = learn.similar_check(synthetic(), CONFIG)
    assert check["rank_ic"] > 0.1
    assert check["top_return"] > check["bottom_return"]


def test_models_are_repeatable():
    data = synthetic()
    first = learn.odds_check(data, CONFIG)
    second = learn.odds_check(data, CONFIG)
    assert first == second


def test_run_gives_insights_for_each_stock_with_enough_history():
    cfg = replace(CONFIG, ml_min_train=300)
    frames = {f"S{i}": prices(i, 2300) for i in range(8)}
    evaluation, insights = learn.run(frames, market(2300), {"S1"}, cfg)
    assert set(insights) == set(frames)
    assert 0 < insights["S0"]["long_odds"]["prob"] < 1
    assert insights["S0"]["short_odds"] is None
    assert insights["S0"]["similar"]["count"] == cfg.ml_neighbours
    assert evaluation["long"]["samples"] > 0


def test_run_with_short_history_gives_nothing_and_does_not_fail():
    evaluation, insights = learn.run({"S0": prices(0, 300)}, market(300), set(), CONFIG)
    assert insights["S0"] == {"long_odds": None, "short_odds": None, "similar": None}
    assert evaluation["long"] is None


def test_grades_say_whether_a_model_beat_the_baseline():
    assert learn.grade(learn.odds_check(synthetic(), CONFIG))["edge"] is True
    assert learn.grade(learn.odds_check(synthetic(signal=False), CONFIG))["edge"] is False
    assert learn.grade(learn.similar_check(synthetic(), CONFIG))["edge"] is True
    assert learn.grade(None) is None


def test_each_stock_carries_its_models_grade():
    cfg = replace(CONFIG, ml_min_train=300)
    frames = {f"S{i}": prices(i, 2300) for i in range(8)}
    _, insights = learn.run(frames, market(2300), set(), cfg)
    assert set(insights["S0"]["long_odds"]["check"]) == {"auc", "top_rate", "bottom_rate", "edge"}
    assert "edge" in insights["S0"]["similar"]["check"]


def test_similar_setups_match_the_stocks_own_pattern_not_the_market():
    data = synthetic()
    finder = learn.Similar(data, CONFIG)
    row = data[[key for key, _ in learn.FEATURES]].iloc[-1].copy()
    other_market = row.copy()
    other_market["ihsg_3m"], other_market["ihsg_vol"] = 5.0, -5.0
    today = data["date"].max()
    assert finder.query(row, "T1", today)["examples"] == finder.query(other_market, "T1", today)["examples"]
