import json

import numpy as np
import pandas as pd
import pytest

from idxquant.clusters import (
    current_market_type,
    fit_groups,
    label_series,
    name_group,
    split_by_label,
    weekly_features,
)
from idxquant.config import CONFIG

COLUMNS = ["ret", "vol", "breadth", "rupiah", "corr"]
CALM = (0.02, 0.10, 0.6, 0.0, 0.2)
PANIC = (-0.15, 0.50, 0.1, 0.05, 0.7)
RALLY = (0.08, 0.15, 0.85, -0.02, 0.3)


def weeks(pattern, seed=1):
    rng = np.random.default_rng(seed)
    rows = []
    for centre, count in pattern:
        rows += [np.array(centre) + rng.normal(0, 0.008, 5) for _ in range(count)]
    index = pd.date_range("2018-01-05", periods=len(rows), freq="7D")
    return pd.DataFrame(rows, index=index, columns=COLUMNS)


def mixed():
    return weeks([(CALM, 50), (RALLY, 40), (PANIC, 30), (CALM, 40), (RALLY, 30), (PANIC, 12), (CALM, 40)])


@pytest.mark.parametrize(
    "centre, label",
    [
        ({"ret": -1.7, "vol": 2.4, "breadth": -1.2}, "Panic"),
        ({"ret": 0.5, "vol": 1.5, "breadth": 0.2}, "Rebound"),
        ({"ret": 0.8, "vol": 0.0, "breadth": 1.1}, "Rally"),
        ({"ret": -0.4, "vol": 0.1, "breadth": -0.8}, "Weakening"),
        ({"ret": 0.3, "vol": -0.6, "breadth": 0.3}, "Quiet"),
    ],
)
def test_groups_are_named_from_what_they_look_like(centre, label):
    assert name_group(pd.Series(centre)) == label


def test_fit_finds_the_groups_in_the_data():
    fit = fit_groups(mixed())
    assert "Panic" in fit.names
    assert "Rally" in fit.names


def test_fit_needs_enough_weeks():
    assert fit_groups(weeks([(CALM, 3)])) is None


def test_labels_start_after_enough_history():
    features = mixed()
    labels = label_series(features)
    assert labels.index[0] == features.index[CONFIG.cluster_min_weeks]
    assert labels.index[-1] == features.index[-1]


def test_labels_recognise_a_later_panic():
    features = mixed()
    labels = label_series(features)
    last_panic = features.index[190:202]
    assert (labels.loc[last_panic, "label"] == "Panic").mean() > 0.7


def test_confidence_is_a_probability():
    assert label_series(mixed())["confidence"].between(0, 1).all()


def test_labels_use_only_earlier_data():
    features = mixed()
    altered = features.copy()
    altered.iloc[180:] += 5.0
    day = features.index[179]
    pd.testing.assert_frame_equal(label_series(features).loc[:day], label_series(altered).loc[:day])


def test_short_history_gives_no_labels():
    assert label_series(weeks([(CALM, 40)])).empty


def test_same_data_gives_same_labels():
    pd.testing.assert_frame_equal(label_series(mixed()), label_series(mixed()))


def daily(days=400):
    index = pd.bdate_range("2025-01-01", periods=days)
    rng = np.random.default_rng(3)
    ihsg = pd.Series(7000 * np.exp(np.cumsum(rng.normal(0, 0.01, days))), index=index)
    closes = pd.DataFrame(
        {name: 1000 * np.exp(np.cumsum(rng.normal(0, 0.015, days))) for name in "ABCD"},
        index=index,
    )
    usdidr = pd.Series(16000 * np.exp(np.cumsum(rng.normal(0, 0.003, days))), index=index)
    return ihsg, closes, usdidr


def test_weekly_features_have_one_row_per_week_ending_on_the_latest_day():
    ihsg, closes, usdidr = daily()
    features = weekly_features(ihsg, closes, usdidr)
    assert list(features.columns) == COLUMNS
    assert features.index[-1] == ihsg.index[-1]
    assert features.index.to_period("W").is_unique
    assert not features.isna().any().any()


def test_return_and_breadth_are_correct():
    index = pd.bdate_range("2025-01-01", periods=120)
    ihsg = pd.Series(np.linspace(1000, 2000, 120), index=index)
    closes = pd.DataFrame({"UP": np.linspace(100, 200, 120), "DOWN": np.linspace(200, 100, 120)}, index=index)
    usdidr = pd.Series(16000.0, index=index)
    last = weekly_features(ihsg, closes, usdidr).iloc[-1]
    assert last["ret"] == pytest.approx(np.log(ihsg.iloc[-1] / ihsg.iloc[-22]))
    assert last["breadth"] == pytest.approx(0.5)
    assert last["rupiah"] == pytest.approx(0.0)


def test_exchange_rate_gaps_are_filled_from_earlier_days():
    ihsg, closes, usdidr = daily()
    features = weekly_features(ihsg, closes, usdidr.iloc[::3])
    assert not features.isna().any().any()


def test_a_single_stock_still_gives_features():
    ihsg, closes, usdidr = daily()
    assert not weekly_features(ihsg, closes[["A"]], usdidr).empty


def test_current_market_type_reports_the_latest_week():
    report = current_market_type(mixed())
    assert report["label"] == "Quiet"
    assert 0 <= report["confidence"] <= 1
    assert set(report["features"]) == set(COLUMNS)


def test_since_is_the_start_of_the_current_run():
    features = mixed()
    report = current_market_type(features)
    labels = label_series(features)["label"]
    since = pd.Timestamp(report["since"])
    assert (labels.loc[since:] == report["label"]).all()
    assert labels[labels.index < since].iloc[-1] != report["label"]


def test_report_describes_each_market_type():
    groups = current_market_type(mixed())["groups"]
    assert sum(group["share"] for group in groups) == pytest.approx(1.0)
    assert {"label", "weeks", "ret", "vol", "breadth", "rupiah", "corr"} <= set(groups[0])


def test_report_is_json_safe():
    json.dumps(current_market_type(mixed()), allow_nan=False)


def test_current_market_type_is_none_with_short_history():
    assert current_market_type(weeks([(CALM, 40)])) is None


def test_split_uses_the_label_known_on_the_signal_day():
    index = pd.date_range("2026-01-02", periods=3, freq="7D")
    labels = pd.DataFrame({"label": ["Quiet", "Panic", "Quiet"], "confidence": 0.9}, index=index)
    midweek = index[1] + pd.Timedelta(days=3)
    trades = [(index[0], 0.10), (midweek, -0.05), (index[2], 0.04)]
    result = split_by_label(trades, labels)
    assert result["Quiet"]["trades"] == 2
    assert result["Panic"]["trades"] == 1
    assert result["Panic"]["avg_return"] == pytest.approx(-0.05)


def test_split_ignores_trades_before_the_labels_start():
    index = pd.date_range("2026-01-09", periods=1, freq="7D")
    labels = pd.DataFrame({"label": ["Quiet"], "confidence": 0.9}, index=index)
    assert split_by_label([(pd.Timestamp("2026-01-01"), 0.5)], labels) == {}


def test_split_handles_no_labels():
    assert split_by_label([(pd.Timestamp("2026-01-01"), 0.1)], pd.DataFrame()) == {}
