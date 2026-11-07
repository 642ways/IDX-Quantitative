import numpy as np
import pandas as pd
import pytest

from idxquant.history import CHART_DAYS, price_history


def prices(days: int, end: str = "2026-11-06") -> pd.DataFrame:
    close = np.linspace(1000, 2000, days)
    return pd.DataFrame({"close": close}, index=pd.bdate_range(end=end, periods=days))


def test_shows_the_last_year_of_trading_days():
    found = price_history(prices(600))
    assert len(found["dates"]) == len(found["close"]) == len(found["ma50"]) == len(found["ma200"]) == CHART_DAYS
    assert found["dates"][-1] == "2026-11-06"


def test_averages_use_the_days_before_the_chart_starts():
    found = price_history(prices(600))
    assert found["ma200"][0] is not None
    frame = prices(600)
    assert found["ma50"][-1] == pytest.approx(frame["close"].iloc[-50:].mean(), abs=0.01)


def test_an_average_is_blank_until_there_are_enough_days():
    found = price_history(prices(150))
    assert found["ma200"] == [None] * 150
    assert found["ma50"][48] is None and found["ma50"][49] is not None


def test_days_after_the_results_date_are_left_out():
    found = price_history(prices(600), until="2026-11-04")
    assert found["dates"][-1] == "2026-11-04"


def test_no_prices_give_no_chart():
    assert price_history(pd.DataFrame()) is None
    assert price_history(prices(10), until="2020-01-01") is None
