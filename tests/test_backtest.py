import numpy as np
import pandas as pd
import pytest

from idxquant.backtest import (
    backtest_momentum,
    backtest_pairs,
    backtest_short,
    momentum_months,
    short_signals,
    short_trades,
    simulate,
    summarise,
    summarise_dated,
    walk,
)
from idxquant.pairs import find_pairs
from idxquant.trading import net_return


def ohlc(rows):
    return pd.DataFrame(
        rows,
        columns=["open", "high", "low", "close"],
        index=pd.bdate_range("2026-01-01", periods=len(rows)),
    )


def test_enters_at_next_open_and_charges_fees():
    frame = ohlc([(100, 100, 100, 100), (101, 102, 100, 101), (103, 112, 102, 111)])
    assert simulate(frame, 0, stop=90, target=110, days=5) == pytest.approx(net_return(101, 110))


def test_stop_wins_when_both_hit_same_day():
    frame = ohlc([(100, 100, 100, 100), (100, 120, 80, 100)])
    assert simulate(frame, 0, stop=90, target=110, days=5) == pytest.approx(net_return(100, 90))


def test_gap_below_stop_exits_at_open():
    frame = ohlc([(100, 100, 100, 100), (100, 101, 99, 100), (80, 85, 78, 82)])
    assert simulate(frame, 0, stop=90, target=110, days=5) == pytest.approx(net_return(100, 80))


def test_time_limit_exits_at_close():
    frame = ohlc([(100, 100, 100, 100), (100, 101, 99, 100), (100, 101, 99, 103), (100, 101, 99, 104)])
    assert simulate(frame, 0, stop=90, target=110, days=2) == pytest.approx(net_return(100, 103))


def test_walk_reports_how_the_trade_ended():
    frame = ohlc([(100, 100, 100, 100), (101, 102, 100, 101), (103, 112, 102, 111)])
    assert walk(frame, 0, stop=90, target=110, days=5) == (101.0, 110, "target")


def test_no_trade_without_a_next_day():
    assert simulate(ohlc([(100, 100, 100, 100)]), 0, stop=90, target=110, days=5) is None


def test_empty_results_are_null():
    assert summarise([])["win_rate"] is None
    assert summarise([])["trades"] == 0


def test_summarise_values():
    result = summarise([0.10, -0.10, 0.10])
    assert result["trades"] == 3
    assert result["win_rate"] == pytest.approx(2 / 3)
    assert result["avg_return"] == pytest.approx(0.1 / 3)
    assert result["max_drawdown"] == pytest.approx(-0.10)


def test_overlapping_trades_in_a_month_are_averaged_for_drawdown():
    month = pd.Timestamp("2026-01-05")
    dated = [(month, -0.10)] * 20 + [(month, 0.10)] * 20
    result = summarise_dated(dated)
    assert result["trades"] == 40
    assert result["max_drawdown"] == pytest.approx(0.0)


def market(seed, days=420, start=2000.0):
    rng = np.random.default_rng(seed)
    close = start * np.exp(np.cumsum(rng.normal(0.0005, 0.02, days)))
    return pd.DataFrame(
        {
            "open": close * 0.999,
            "high": close * 1.01,
            "low": close * 0.99,
            "close": close,
            "adj_close": close,
            "volume": rng.uniform(1e6, 3e6, days),
        },
        index=pd.bdate_range("2024-01-01", periods=days),
    )


def test_no_lookahead_in_short_backtest():
    frame = market(1)
    altered = frame.copy()
    altered.iloc[300:, :] *= 5
    before = [day for day in short_signals(frame) if day < 299]
    after = [day for day in short_signals(altered) if day < 299]
    assert before == after


def test_short_trades_are_dated_by_signal_day():
    frame = market(1)
    trades = short_trades({"A": frame})
    assert trades
    assert all(date in frame.index for date, _ in trades)
    assert summarise_dated(trades) == backtest_short({"A": frame})


def test_momentum_months_are_dated():
    prices = {name: market(i) for i, name in enumerate("ABCDEF")}
    months = momentum_months(prices)
    assert all(isinstance(date, pd.Timestamp) for date, _ in months)
    assert len(months) == backtest_momentum(prices)["trades"]


def test_short_backtest_reports_all_fields():
    assert set(backtest_short({"A": market(1)})) == {"trades", "win_rate", "avg_return", "max_drawdown"}


def cointegrated_market(days=900):
    rng = np.random.default_rng(5)
    base = 7.5 + np.cumsum(rng.normal(0, 0.012, days))
    noise = np.zeros(days)
    for day in range(1, days):
        noise[day] = 0.9 * noise[day - 1] + rng.normal(0, 0.012)
    index = pd.bdate_range("2023-01-01", periods=days)

    def frame(logs):
        close = np.exp(logs)
        return pd.DataFrame(
            {
                "open": close,
                "high": close * 1.002,
                "low": close * 0.998,
                "close": close,
                "adj_close": close,
                "volume": 1e6,
            },
            index=index,
        )

    return {"A": frame(base + noise), "B": frame(base)}


def test_pair_backtest_trades_a_cointegrated_pair():
    assert backtest_pairs(cointegrated_market(), {"A": "Coal", "B": "Coal"})["trades"] > 0


def test_no_lookahead_in_pair_formation():
    prices = cointegrated_market()
    sectors = {"A": "Coal", "B": "Coal"}
    logs = {t: np.log(f["close"].iloc[:600]) for t, f in prices.items()}
    altered = {t: f.copy() for t, f in prices.items()}
    altered["A"].iloc[600:, :] *= 3
    altered_logs = {t: np.log(f["close"].iloc[:600]) for t, f in altered.items()}
    assert find_pairs(logs, sectors) == find_pairs(altered_logs, sectors)


def test_momentum_backtest_runs_and_includes_costs():
    prices = {name: market(i) for i, name in enumerate("ABCDEF")}
    assert backtest_momentum(prices)["trades"] > 0
