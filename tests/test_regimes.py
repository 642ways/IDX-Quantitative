import json

import numpy as np
import pandas as pd
import pytest

from idxquant.config import CONFIG
from idxquant.regimes import RegimeFit, current_regime, filter_probs, fit_model, split_by_regime, stress_series


def closes(calm_a=800, stressed=120, calm_b=300, seed=1):
    rng = np.random.default_rng(seed)
    moves = np.concatenate(
        [rng.normal(0.0005, 0.005, calm_a), rng.normal(-0.003, 0.03, stressed), rng.normal(0.0005, 0.005, calm_b)]
    )
    index = pd.bdate_range("2020-01-01", periods=len(moves))
    return pd.Series(5000 * np.exp(np.cumsum(moves)), index=index)


def returns(series):
    return (np.log(series).diff().dropna()) * 100


FIT = RegimeFit(means=(0.05, -0.3), variances=(0.25, 9.0), stay=(0.98, 0.9))


def test_fit_puts_the_volatile_state_second():
    fit = fit_model(returns(closes()))
    assert fit.variances[1] > fit.variances[0] * 5
    assert fit.means[1] < fit.means[0]


def test_fit_handles_a_series_it_cannot_model():
    assert fit_model(pd.Series([1.0, 2.0, 3.0])) is None


def test_filter_flags_the_stressed_stretch():
    series = returns(closes())
    probs = filter_probs(series, FIT)
    assert probs.iloc[810:910].mean() > 0.8
    assert probs.iloc[200:700].mean() < 0.1
    assert probs.iloc[-100:].mean() < 0.1


def test_filter_probabilities_stay_valid():
    probs = filter_probs(returns(closes()), FIT)
    assert probs.between(0, 1).all()


def test_filter_survives_a_huge_move():
    series = returns(closes())
    series.iloc[500] = 500.0
    assert filter_probs(series, FIT).notna().all()


def test_stress_series_starts_after_enough_history():
    series = closes()
    stress = stress_series(series)
    assert stress.index[0] == series.index[CONFIG.regime_min_history + 1]
    assert stress.index[-1] == series.index[-1]


def test_stress_series_uses_only_earlier_data():
    series = closes()
    altered = series.copy()
    altered.iloc[1000:] *= np.exp(np.linspace(0, 2, len(altered) - 1000))
    first, second = stress_series(series), stress_series(altered)
    day = series.index[999]
    pd.testing.assert_series_equal(first.loc[:day], second.loc[:day])


def test_stress_series_is_empty_when_history_is_short():
    assert stress_series(closes(200, 20, 20)).empty


def test_current_regime_reports_the_latest_state():
    calm = current_regime(closes())
    assert calm["label"] == "Calm"
    assert calm["stress_prob"] < CONFIG.regime_threshold
    stressed = current_regime(closes(800, 120, 0))
    assert stressed["label"] == "Stressed"


def test_current_regime_is_none_with_short_history():
    assert current_regime(closes(200, 20, 20)) is None


def test_current_regime_says_how_different_the_states_are():
    regime = current_regime(closes())
    assert regime["stressed_vol"] > regime["calm_vol"]
    assert 0 < regime["stressed_share"] < 1
    assert regime["calm_days"] > 0 and regime["stressed_days"] > 0


def test_since_is_the_start_of_the_current_run():
    regime = current_regime(closes())
    stress = stress_series(closes())
    since = pd.Timestamp(regime["since"])
    assert (stress.loc[since:] <= CONFIG.regime_threshold).all()
    assert stress[stress.index < since].iloc[-1] > CONFIG.regime_threshold


def test_history_is_thinned_and_json_safe():
    regime = current_regime(closes())
    assert len(regime["history"]) <= len(closes()) / 4
    date, close, prob = regime["history"][-1]
    assert isinstance(date, str) and close > 0 and 0 <= prob <= 1
    json.dumps(regime, allow_nan=False)


def test_split_by_regime_uses_the_state_on_the_signal_day():
    index = pd.bdate_range("2026-01-01", periods=4)
    stress = pd.Series([0.1, 0.9, 0.9, 0.1], index=index)
    trades = [(index[0], 0.10), (index[1], -0.05), (index[2], -0.02), (index[3], 0.04)]
    result = split_by_regime(trades, stress)
    assert result["calm"]["trades"] == 2
    assert result["stressed"]["trades"] == 2
    assert result["stressed"]["avg_return"] == pytest.approx(-0.035)


def test_split_by_regime_ignores_trades_before_the_model_starts():
    index = pd.bdate_range("2026-01-05", periods=2)
    stress = pd.Series([0.1, 0.1], index=index)
    early = pd.Timestamp("2026-01-01")
    result = split_by_regime([(early, 0.5), (index[1], 0.1)], stress)
    assert result["calm"]["trades"] == 1
    assert result["stressed"]["trades"] == 0


def test_split_by_regime_handles_no_model():
    assert split_by_regime([(pd.Timestamp("2026-01-01"), 0.1)], pd.Series(dtype=float))["calm"]["trades"] == 0
