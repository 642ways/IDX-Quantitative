from dataclasses import replace
from datetime import datetime, timedelta, timezone
import json

import numpy as np
import pandas as pd
import pytest

from idxquant.config import CONFIG
from idxquant.pipeline import drop_partial_bar, needs_refresh, run, track_record, tradable
from idxquant.store import Store

WIB = timezone(timedelta(hours=7))
FRIDAY_EVENING = datetime(2026, 10, 30, 18, 0, tzinfo=WIB)
DAYS = 600


def frame(seed, drift=-0.0005, breakout=False, volume=5_000_000.0):
    rng = np.random.default_rng(seed)
    close = 2000 * np.exp(np.cumsum(rng.normal(drift, 0.015, DAYS)))
    volumes = np.full(DAYS, volume)
    if breakout:
        close = np.linspace(1500, 2500, DAYS) * (1 + rng.normal(0, 0.002, DAYS))
        close[-1] = 2800
        volumes[-1] = volume * 3
    return pd.DataFrame(
        {
            "open": close,
            "high": close * 1.01,
            "low": close * 0.99,
            "close": close,
            "adj_close": close,
            "volume": volumes,
        },
        index=pd.bdate_range(end="2026-10-30", periods=DAYS),
    )


class FakeFetcher:
    def __init__(self, prices, fundamentals=None):
        self.prices = prices
        self.fundamentals = fundamentals or {}

    def fetch_prices(self, ticker, years=10):
        return self.prices.get(ticker, pd.DataFrame())

    def fetch_fundamentals(self, ticker):
        return self.fundamentals.get(ticker)

    def fetch_usdidr(self):
        return 16000.0

    def fetch_index(self):
        return frame(50)

    def fetch_usdidr_history(self):
        return frame(51)


def universe(tickers):
    return pd.DataFrame({"ticker": tickers, "name": tickers, "sector": ["Coal" if i % 2 else "Banks" for i in range(len(tickers))]})


def execute(tmp_path, fetcher, tickers, now=FRIDAY_EVENING, cfg=CONFIG):
    store = Store(tmp_path / "db.sqlite")
    return store, run(store, fetcher, now, cfg, universe(tickers))


def test_run_survives_ticker_failures(tmp_path):
    fetcher = FakeFetcher({"AAAA": frame(1), "BBBB": frame(2), "CCCC": frame(3)})
    _, snapshot = execute(tmp_path, fetcher, ["AAAA", "BBBB", "CCCC", "GONE"])
    assert "GONE" in [item["ticker"] for item in snapshot["skipped"]]
    assert "AAAA" in snapshot["stocks"]


class RaisingFetcher(FakeFetcher):
    def fetch_prices(self, ticker, years=10):
        if ticker == "BOOM":
            raise KeyError("Adj Close")
        return super().fetch_prices(ticker, years)

    def fetch_fundamentals(self, ticker):
        if ticker == "AAAA":
            raise KeyError("reportedValue")
        return super().fetch_fundamentals(ticker)


def test_one_ticker_raising_does_not_abort_the_run(tmp_path):
    prices = {"AAAA": frame(1), "BBBB": frame(2), "CCCC": frame(3)}
    _, snapshot = execute(tmp_path, RaisingFetcher(prices), ["AAAA", "BBBB", "CCCC", "BOOM"])
    assert "BOOM" in [item["ticker"] for item in snapshot["skipped"]]
    assert "AAAA" in snapshot["stocks"]


def test_nan_close_on_latest_bar_is_skipped_with_a_reason(tmp_path):
    broken = frame(1)
    broken.iloc[-1, broken.columns.get_loc("close")] = float("nan")
    _, snapshot = execute(tmp_path, FakeFetcher({"AAAA": broken, "BBBB": frame(2)}), ["AAAA", "BBBB"])
    assert "AAAA" not in snapshot["stocks"]
    assert "AAAA" in [item["ticker"] for item in snapshot["skipped"]]


def with_blank_last_close(prices):
    blanked = prices.copy()
    blanked.iloc[-1, blanked.columns.get_indexer(["open", "high", "low", "close", "adj_close"])] = float("nan")
    return blanked


def test_blank_latest_close_is_filled_from_saved_prices(tmp_path):
    good = frame(1)
    store, first = execute(tmp_path, FakeFetcher({"AAAA": good}), ["AAAA"])
    second = run(store, FakeFetcher({"AAAA": with_blank_last_close(good)}), FRIDAY_EVENING, CONFIG, universe(["AAAA"]))
    assert second["data_date"] == first["data_date"]
    assert second["stocks"]["AAAA"]["close"] == pytest.approx(float(good["close"].iloc[-1]))


def test_blank_latest_index_close_is_filled_from_saved_prices(tmp_path):
    class BlankIndex(FakeFetcher):
        def fetch_index(self):
            return with_blank_last_close(frame(50))

    store, _ = execute(tmp_path, FakeFetcher({"AAAA": frame(1)}), ["AAAA"])
    run(store, BlankIndex({"AAAA": frame(1)}), FRIDAY_EVENING, CONFIG, universe(["AAAA"]))
    assert store.load_prices("^JKSE")["close"].iloc[-1] == pytest.approx(float(frame(50)["close"].iloc[-1]))


def test_a_refresh_older_than_the_latest_result_is_not_saved(tmp_path):
    store, first = execute(tmp_path, FakeFetcher({"AAAA": frame(1)}), ["AAAA"])
    older = FakeFetcher({"AAAA": frame(1).iloc[:-1]})
    result = run(store, older, FRIDAY_EVENING, CONFIG, universe(["AAAA"]))
    assert result["warnings"]
    assert result["data_date"] == first["data_date"]
    assert len(store.all_snapshots()) == 1


def test_mostly_failed_refresh_keeps_the_good_snapshot(tmp_path):
    tickers = ["AAAA", "BBBB", "CCCC", "DDDD"]
    full = {t: frame(i) for i, t in enumerate(tickers)}
    store, first = execute(tmp_path, FakeFetcher(full), tickers)
    partial = FakeFetcher({"AAAA": full["AAAA"], "BBBB": full["BBBB"]})
    result = run(store, partial, FRIDAY_EVENING + timedelta(minutes=30), CONFIG, universe(tickers))
    assert result["warnings"]
    assert store.latest_snapshot()["stocks"].keys() == first["stocks"].keys()
    assert "CCCC" not in partial.prices


def test_missing_financials_raise_a_warning(tmp_path):
    _, snapshot = execute(tmp_path, FakeFetcher({"AAAA": frame(1)}), ["AAAA"])
    assert any("financial data" in warning for warning in snapshot["warnings"])


def test_all_fetches_failing_keeps_last_snapshot(tmp_path):
    funda = {"AAAA": {"as_of": "2025-12-31", "currency": "IDR", "eps": 100.0, "equity": 1e12, "shares": 1e9}}
    store, first = execute(tmp_path, FakeFetcher({"AAAA": frame(1)}, funda), ["AAAA"])
    later = FRIDAY_EVENING + timedelta(days=3)
    result = run(store, FakeFetcher({}), later, CONFIG, universe(["AAAA"]))
    assert result["warnings"]
    assert result["data_date"] == first["data_date"]
    assert store.latest_snapshot()["warnings"] == []


def test_all_fetches_failing_with_no_history(tmp_path):
    _, result = execute(tmp_path, FakeFetcher({}), ["AAAA"])
    assert result["warnings"]
    assert result["picks"] == []


def test_today_bar_dropped_before_17_wib():
    assert drop_partial_bar(frame(1), FRIDAY_EVENING.replace(hour=10)).index[-1] == pd.Timestamp("2026-10-29")


def test_today_bar_kept_after_17_wib():
    assert drop_partial_bar(frame(1), FRIDAY_EVENING).index[-1] == pd.Timestamp("2026-10-30")


def test_data_date_reflects_dropped_bar(tmp_path):
    _, snapshot = execute(tmp_path, FakeFetcher({"AAAA": frame(1)}), ["AAAA"], FRIDAY_EVENING.replace(hour=10))
    assert snapshot["data_date"] == "2026-10-29"


def snapshot_at(moment):
    return {"ran_at": moment.isoformat()}


def test_first_ever_open_needs_refresh():
    assert needs_refresh(FRIDAY_EVENING.replace(hour=9), None)


def test_after_17_on_weekday_without_todays_run_needs_refresh():
    assert needs_refresh(FRIDAY_EVENING, snapshot_at(FRIDAY_EVENING - timedelta(days=1)))


def test_after_todays_run_needs_no_refresh():
    assert not needs_refresh(FRIDAY_EVENING + timedelta(hours=1), snapshot_at(FRIDAY_EVENING))


def test_before_17_needs_no_refresh_after_yesterdays_run():
    thursday_evening = FRIDAY_EVENING - timedelta(days=1)
    assert not needs_refresh(FRIDAY_EVENING.replace(hour=10), snapshot_at(thursday_evening))


def test_weekend_needs_no_refresh_after_fridays_run():
    assert not needs_refresh(FRIDAY_EVENING + timedelta(days=1), snapshot_at(FRIDAY_EVENING))


def test_weekend_needs_refresh_if_friday_evening_was_missed():
    thursday_evening = FRIDAY_EVENING - timedelta(days=1)
    assert needs_refresh(FRIDAY_EVENING + timedelta(days=1), snapshot_at(thursday_evening))


def test_yahoo_lag_after_17_keeps_retrying_on_a_weekday():
    tuesday = datetime(2026, 11, 3, 17, 30, tzinfo=WIB)
    ran = {"ran_at": tuesday.replace(minute=5).isoformat(), "data_date": "2026-11-02"}
    assert needs_refresh(tuesday, ran)


def test_yahoo_lag_retries_stop_in_the_evening():
    tuesday = datetime(2026, 11, 3, 20, 30, tzinfo=WIB)
    ran = {"ran_at": tuesday.replace(hour=17).isoformat(), "data_date": "2026-11-02"}
    assert not needs_refresh(tuesday, ran)


def test_no_lag_retry_when_todays_data_arrived():
    tuesday = datetime(2026, 11, 3, 17, 30, tzinfo=WIB)
    ran = {"ran_at": tuesday.replace(minute=5).isoformat(), "data_date": "2026-11-03"}
    assert not needs_refresh(tuesday, ran)


def test_quiet_day_gives_empty_picks(tmp_path):
    _, snapshot = execute(tmp_path, FakeFetcher({"AAAA": frame(1), "BBBB": frame(2)}), ["AAAA", "BBBB"])
    assert snapshot["picks"] == []


def test_picks_capped_at_max_rows(tmp_path):
    tickers = ["AAAA", "BBBB", "CCCC", "DDDD"]
    fetcher = FakeFetcher({t: frame(i, breakout=True) for i, t in enumerate(tickers)})
    _, snapshot = execute(tmp_path, fetcher, tickers, cfg=replace(CONFIG, max_rows=2))
    assert len(snapshot["picks"]) == 2
    assert [pick["rank"] for pick in snapshot["picks"]] == [1, 2]


def test_every_play_carries_monte_carlo_odds(tmp_path):
    tickers = ["AAAA", "BBBB"]
    fetcher = FakeFetcher({t: frame(i, breakout=True) for i, t in enumerate(tickers)})
    _, snapshot = execute(tmp_path, fetcher, tickers)
    pick = snapshot["picks"][0]
    assert 0 <= pick["monte_carlo"]["target_prob"] <= 1
    assert snapshot["stocks"][pick["ticker"]]["plays"][0]["monte_carlo"]["paths"] == CONFIG.mc_paths
    json.dumps(snapshot, allow_nan=False)


def test_chart_is_on_the_stock_page_but_not_in_the_picks(tmp_path):
    tickers = ["AAAA", "BBBB"]
    fetcher = FakeFetcher({t: frame(i, breakout=True) for i, t in enumerate(tickers)})
    _, snapshot = execute(tmp_path, fetcher, tickers)
    pick = snapshot["picks"][0]
    assert "chart" not in pick["monte_carlo"]
    assert "chart" in snapshot["stocks"][pick["ticker"]]["plays"][0]["monte_carlo"]


def test_stock_page_carries_valuation_details(tmp_path):
    funda = {
        "AAAA": {
            "as_of": "2025-12-31",
            "currency": "IDR",
            "eps": 100.0,
            "equity": 1e12,
            "shares": 1e9,
            "history": [{"as_of": "2025-12-31", "eps": 100.0, "equity": 1e12, "shares": 1e9, "revenue": 5e11, "net_income": 1e11}],
        }
    }
    _, snapshot = execute(tmp_path, FakeFetcher({"AAAA": frame(1)}, funda), ["AAAA"])
    page = snapshot["stocks"]["AAAA"]
    assert page["valuation"]["net_margin"] == pytest.approx(0.2)
    assert page["years"][0]["year"] == "2025"
    assert "ps" in page["sector_medians"]


def test_snapshot_carries_the_market_regime(tmp_path):
    _, snapshot = execute(tmp_path, FakeFetcher({"AAAA": frame(1)}), ["AAAA"])
    assert snapshot["regime"]["label"] in ("Calm", "Stressed")
    assert set(snapshot["backtest"]["regimes"]) == {"short", "pair", "momentum"}


def test_snapshot_carries_the_market_type(tmp_path):
    _, snapshot = execute(tmp_path, FakeFetcher({"AAAA": frame(1)}), ["AAAA"])
    assert snapshot["market_type"]["label"]
    assert set(snapshot["backtest"]["market_types"]) == {"short", "pair", "momentum"}


class NoRateHistoryFetcher(FakeFetcher):
    def fetch_usdidr_history(self):
        raise RuntimeError("Yahoo is down")


def test_missing_rate_history_warns_and_still_gives_the_regime(tmp_path):
    _, snapshot = execute(tmp_path, NoRateHistoryFetcher({"AAAA": frame(1)}), ["AAAA"])
    assert snapshot["market_type"] is None
    assert any("market type" in warning for warning in snapshot["warnings"])
    assert snapshot["regime"] is not None


def test_old_backtest_without_market_types_is_recomputed(tmp_path):
    store, first = execute(tmp_path, FakeFetcher({"AAAA": frame(1)}), ["AAAA"])
    del first["backtest"]["market_types"]
    store.save_snapshot(first["data_date"], first)
    second = run(store, FakeFetcher({"AAAA": frame(1)}), FRIDAY_EVENING + timedelta(days=3), CONFIG, universe(["AAAA"]))
    assert "market_types" in second["backtest"]


class NoIndexFetcher(FakeFetcher):
    def fetch_index(self):
        raise RuntimeError("Yahoo is down")


def test_missing_index_warns_and_still_gives_picks(tmp_path):
    _, snapshot = execute(tmp_path, NoIndexFetcher({"AAAA": frame(1)}), ["AAAA"])
    assert snapshot["regime"] is None
    assert any("regime" in warning for warning in snapshot["warnings"])
    assert "AAAA" in snapshot["stocks"]


def test_regime_ignores_todays_partial_bar(tmp_path):
    store, _ = execute(tmp_path, FakeFetcher({"AAAA": frame(1)}), ["AAAA"], FRIDAY_EVENING.replace(hour=10))
    assert store.load_prices("^JKSE").index[-1] == pd.Timestamp("2026-10-29")


def test_snapshot_carries_calibration(tmp_path):
    _, snapshot = execute(tmp_path, FakeFetcher({"AAAA": frame(1)}), ["AAAA"])
    assert set(snapshot["backtest"]["calibration"]) == {"long", "short"}


def test_old_backtest_without_calibration_is_recomputed(tmp_path):
    store, first = execute(tmp_path, FakeFetcher({"AAAA": frame(1)}), ["AAAA"])
    del first["backtest"]["calibration"]
    store.save_snapshot(first["data_date"], first)
    second = run(store, FakeFetcher({"AAAA": frame(1)}), FRIDAY_EVENING + timedelta(days=3), CONFIG, universe(["AAAA"]))
    assert "calibration" in second["backtest"]


def test_accuracy_check_reruns_when_the_stop_changes(tmp_path):
    store, first = execute(tmp_path, FakeFetcher({"AAAA": frame(1)}), ["AAAA"])
    first["backtest"]["calibration"]["long"]["stop"] = 0.15
    first["backtest"]["short"]["trades"] = 999
    store.save_snapshot(first["data_date"], first)
    second = run(store, FakeFetcher({"AAAA": frame(1)}), FRIDAY_EVENING + timedelta(days=3), CONFIG, universe(["AAAA"]))
    assert second["backtest"]["calibration"]["long"]["stop"] == CONFIG.long_stop
    assert second["backtest"]["short"]["trades"] != 999


def test_tradable_needs_liquidity():
    assert tradable(frame(1))
    assert not tradable(frame(1, volume=1000.0))


def test_tradable_needs_history():
    assert not tradable(frame(1).iloc[-300:])


def test_suspended_stock_not_tradable():
    suspended = frame(1)
    suspended.iloc[-30:, suspended.columns.get_loc("volume")] = 0.0
    assert not tradable(suspended)


@pytest.mark.parametrize("days", [1, 5, 9])
def test_recently_suspended_stock_not_tradable(days):
    suspended = frame(1)
    suspended.iloc[-days:, suspended.columns.get_loc("volume")] = 0.0
    assert not tradable(suspended)


def test_illiquid_stock_is_skipped_with_a_reason(tmp_path):
    fetcher = FakeFetcher({"AAAA": frame(1), "BBBB": frame(2, volume=1000.0)})
    _, snapshot = execute(tmp_path, fetcher, ["AAAA", "BBBB"])
    assert "BBBB" not in snapshot["stocks"]
    assert [item["ticker"] for item in snapshot["skipped"]] == ["BBBB"]


def test_snapshot_is_json_serialisable_with_nulls(tmp_path):
    _, snapshot = execute(tmp_path, FakeFetcher({"AAAA": frame(1)}), ["AAAA"])
    json.dumps(snapshot, allow_nan=False)
    assert snapshot["stocks"]["AAAA"]["valuation"]["pe"] is None


def test_backtest_reused_while_fresh(tmp_path):
    store, first = execute(tmp_path, FakeFetcher({"AAAA": frame(1)}), ["AAAA"])
    first["backtest"]["short"]["trades"] = 999
    store.save_snapshot(first["data_date"], first)
    second = run(store, FakeFetcher({"AAAA": frame(1)}), FRIDAY_EVENING + timedelta(days=3), CONFIG, universe(["AAAA"]))
    assert second["backtest"]["short"]["trades"] == 999


def test_track_record_compares_pick_with_later_price():
    pick = {"ticker": "AAAA", "kind": "short", "entry_high": 1000, "target": 1100, "stop": 950, "rank": 1}
    prices = pd.DataFrame(
        {"high": [1010.0, 1050.0], "low": [990.0, 1000.0], "close": [1000.0, 1040.0]},
        index=pd.to_datetime(["2026-10-30", "2026-11-02"]),
    )
    record = track_record([{"data_date": "2026-10-29", "picks": [pick]}], {"AAAA": prices})
    assert record[0]["outcome"] == "Open"
    assert record[0]["latest_close"] == 1040.0
    assert record[0]["return"] == pytest.approx((1040 * 0.9975) / (1000 * 1.0015) - 1)


def test_track_record_survives_a_later_stock_split():
    pick = {"ticker": "AAAA", "kind": "long", "close": 1000.0, "entry_high": 1000, "target": 1300, "stop": 850, "rank": 1}
    prices = pd.DataFrame(
        {"high": [200.0, 202.0], "low": [200.0, 198.0], "close": [200.0, 200.0]},
        index=pd.to_datetime(["2026-10-29", "2026-10-30"]),
    )
    record = track_record([{"data_date": "2026-10-29", "picks": [pick]}], {"AAAA": prices})
    assert record[0]["outcome"] == "Open"
    assert record[0]["return"] == pytest.approx((1000 * 0.9975) / (1000 * 1.0015) - 1)


def test_pair_time_limit_counts_trading_days():
    pick = {"ticker": "AAAA", "kind": "pair", "entry_high": 1000, "target": 1100, "stop": 900, "days": 5, "rank": 1}
    dates = pd.bdate_range("2026-10-30", periods=6)
    prices = pd.DataFrame({"high": 1010.0, "low": 990.0, "close": 1000.0}, index=dates)
    record = track_record([{"data_date": "2026-10-29", "picks": [pick]}], {"AAAA": prices})
    assert record[0]["outcome"] == "Time limit"
    calendar = pick | {"days": 7}
    open_record = track_record([{"data_date": "2026-10-29", "picks": [calendar]}], {"AAAA": prices})
    assert open_record[0]["outcome"] == "Open"


def test_track_record_stops_at_first_level_hit():
    pick = {"ticker": "AAAA", "kind": "short", "entry_high": 1000, "target": 1100, "stop": 950, "rank": 1}
    prices = pd.DataFrame(
        {"high": [1110.0, 1200.0], "low": [990.0, 1100.0], "close": [1100.0, 1190.0]},
        index=pd.to_datetime(["2026-10-30", "2026-11-02"]),
    )
    record = track_record([{"data_date": "2026-10-29", "picks": [pick]}], {"AAAA": prices})
    assert record[0]["outcome"] == "Target hit"
    assert record[0]["return"] == pytest.approx((1100 * 0.9975) / (1000 * 1.0015) - 1)


def test_snapshot_carries_backtest_equity_curves(tmp_path):
    _, snapshot = execute(tmp_path, FakeFetcher({"AAAA": frame(1)}), ["AAAA"])
    assert set(snapshot["backtest"]["equity"]) == {"short", "pair", "momentum"}


def test_old_backtest_without_equity_curves_is_recomputed(tmp_path):
    store, first = execute(tmp_path, FakeFetcher({"AAAA": frame(1)}), ["AAAA"])
    del first["backtest"]["equity"]
    store.save_snapshot(first["data_date"], first)
    second = run(store, FakeFetcher({"AAAA": frame(1)}), FRIDAY_EVENING + timedelta(days=3), CONFIG, universe(["AAAA"]))
    assert "equity" in second["backtest"]


def test_pair_rows_flip_the_gap_history_for_the_rich_side():
    from idxquant.pairs import Pair
    from idxquant.pipeline import _pair_rows

    pair = Pair("AAAA", "BBBB", 1.0, 0.0, 0.01, 8.0, -2.2, 0.0, 0.05, recent_z=(-1.0, -2.2))
    assert _pair_rows([pair], "AAAA")[0]["gap_history"] == [-1.0, -2.2]
    assert _pair_rows([pair], "BBBB")[0]["gap_history"] == [1.0, 2.2]


def test_snapshot_carries_the_model_checks_and_each_stocks_insights(tmp_path):
    _, snapshot = execute(tmp_path, FakeFetcher({"AAAA": frame(1), "BBBB": frame(2)}), ["AAAA", "BBBB"])
    assert set(snapshot["models"]) == {"long", "short", "similar", "features", "grades"}
    assert all("insights" in page for page in snapshot["stocks"].values())


class BrokenModels(Exception):
    pass


def test_a_model_failure_warns_and_keeps_the_picks(tmp_path, monkeypatch):
    def broken(*args, **kwargs):
        raise BrokenModels("no convergence")

    monkeypatch.setattr("idxquant.learn.run", broken)
    _, snapshot = execute(tmp_path, FakeFetcher({"AAAA": frame(1)}), ["AAAA"])
    assert snapshot["models"] is None
    assert snapshot["stocks"]["AAAA"]["insights"] is None
    assert any("machine learning" in warning for warning in snapshot["warnings"])


def test_snapshot_checks_how_much_the_picks_overlap(tmp_path):
    tickers = ["AAAA", "BBBB", "CCCC"]
    fetcher = FakeFetcher({t: frame(i, breakout=True) for i, t in enumerate(tickers)})
    _, snapshot = execute(tmp_path, fetcher, tickers)
    found = snapshot["concentration"]
    assert set(found["tickers"]) == {pick["ticker"] for pick in snapshot["picks"]}
    assert len(found["matrix"]) == len(found["tickers"])


class EventFetcher(FakeFetcher):
    def fetch_events(self, ticker):
        return {"earnings": ["2026-11-05"], "dividends": [["2026-06-22", 50.0]], "splits": []}


def test_stock_pages_and_picks_carry_upcoming_events(tmp_path):
    tickers = ["AAAA", "BBBB"]
    fetcher = EventFetcher({t: frame(i, breakout=True) for i, t in enumerate(tickers)})
    _, snapshot = execute(tmp_path, fetcher, tickers)
    page = snapshot["stocks"]["AAAA"]
    assert page["events"]["earnings"]["next"] == "2026-11-05"
    assert page["events"]["dividend"]["last"]["amount"] == 50.0
    assert snapshot["picks"][0]["event"] == "Earnings report in 6 days"


def test_events_missing_from_yahoo_leave_the_page_without_them(tmp_path):
    _, snapshot = execute(tmp_path, FakeFetcher({"AAAA": frame(1)}), ["AAAA"])
    assert snapshot["stocks"]["AAAA"]["events"] is None
