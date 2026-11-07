import numpy as np
import pandas as pd
import pytest

from idxquant import sectors
from idxquant.config import CONFIG


def steady(weekly_change: float, end: str = "2026-11-06", weeks: int = 30) -> pd.DataFrame:
    """Prices that move by the same share every week, one row per trading day."""
    days = pd.bdate_range(end=end, periods=weeks * 5)
    close = 1000 * (1 + weekly_change) ** (np.arange(len(days)) / 5)
    return pd.DataFrame({"close": close}, index=days)


def test_rising_sectors_come_first_and_falling_ones_last():
    frames = {"UP1": steady(0.02), "UP2": steady(0.02), "DOWN": steady(-0.02)}
    found = sectors.rotation(frames, {"UP1": "Coal", "UP2": "Coal", "DOWN": "Banks"})
    assert [row["sector"] for row in found["rows"]] == ["Coal", "Banks"]
    assert found["rows"][0]["total"] > 0 > found["rows"][1]["total"]


def test_each_week_is_the_sectors_average_stock():
    frames = {"FAST": steady(0.04), "SLOW": steady(0.0)}
    found = sectors.rotation(frames, {"FAST": "Coal", "SLOW": "Coal"})
    assert found["rows"][0]["returns"][-2] == pytest.approx(0.02, abs=0.002)
    assert found["rows"][0]["stocks"] == 2


def test_shows_the_configured_number_of_weeks():
    found = sectors.rotation({"AAAA": steady(0.01)}, {"AAAA": "Coal"})
    assert len(found["weeks"]) == CONFIG.rotation_weeks
    assert len(found["rows"][0]["returns"]) == CONFIG.rotation_weeks


def test_a_week_still_in_progress_is_marked():
    found = sectors.rotation({"AAAA": steady(0.01, end="2026-11-04")}, {"AAAA": "Coal"})
    assert found["weeks"][-1] == "2026-11-06"
    assert found["partial"] is True
    complete = sectors.rotation({"AAAA": steady(0.01, end="2026-11-06")}, {"AAAA": "Coal"})
    assert complete["partial"] is False


def test_every_stock_together_is_given_for_comparison():
    frames = {"UP": steady(0.02), "DOWN": steady(-0.02)}
    found = sectors.rotation(frames, {"UP": "Coal", "DOWN": "Banks"})
    assert found["all"]["stocks"] == 2
    assert found["all"]["returns"][-2] == pytest.approx(0.0, abs=0.002)


def test_too_little_history_gives_nothing():
    short = steady(0.01).iloc[-3:]
    assert sectors.rotation({"AAAA": short}, {"AAAA": "Coal"}) is None
