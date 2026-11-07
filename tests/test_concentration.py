from dataclasses import replace

import numpy as np
import pandas as pd
import pytest

from idxquant import concentration
from idxquant.config import CONFIG

DAYS = 300


def closes(returns: np.ndarray) -> pd.DataFrame:
    close = 1000 * np.exp(np.cumsum(returns))
    return pd.DataFrame({"close": close}, index=pd.bdate_range(end="2026-11-06", periods=len(returns)))


def noise(seed: int, days: int = DAYS) -> np.ndarray:
    return np.random.default_rng(seed).normal(0, 0.02, days)


def picks(*tickers: str) -> list[dict]:
    return [{"ticker": ticker} for ticker in tickers]


def test_one_pick_has_nothing_to_compare():
    assert concentration.check(picks("AAAA"), {"AAAA": closes(noise(1))}, {"AAAA": "Coal"}) is None


def test_picks_moving_as_one_count_as_about_one_bet():
    shared = noise(1)
    frames = {t: closes(shared + noise(i, DAYS) * 0.05) for i, t in enumerate(["AAAA", "BBBB", "CCCC"], start=2)}
    result = concentration.check(picks("AAAA", "BBBB", "CCCC"), frames, dict.fromkeys(frames, "Coal"))
    assert result["effective_bets"] == pytest.approx(1, abs=0.1)
    assert any("move together" in warning for warning in result["warnings"])


def test_independent_picks_count_as_separate_bets():
    tickers = ["AAAA", "BBBB", "CCCC", "DDDD"]
    frames = {t: closes(noise(i)) for i, t in enumerate(tickers)}
    sectors = dict(zip(tickers, ["Coal", "Banks", "Retail", "Metals"]))
    result = concentration.check(picks(*tickers), frames, sectors)
    assert result["effective_bets"] > 3.5
    assert abs(result["avg_corr"]) < 0.15
    assert result["warnings"] == []


def test_many_picks_from_one_sector_are_flagged():
    tickers = ["AAAA", "BBBB", "CCCC", "DDDD", "EEEE"]
    frames = {t: closes(noise(i)) for i, t in enumerate(tickers)}
    sectors = dict(zip(tickers, ["Coal", "Coal", "Coal", "Banks", "Retail"]))
    result = concentration.check(picks(*tickers), frames, sectors)
    assert "3 of 5 picks are Coal stocks." in result["warnings"][0]
    assert result["sectors"][0] == {"sector": "Coal", "count": 3, "tickers": ["AAAA", "BBBB", "CCCC"]}


def test_heatmap_puts_stocks_that_move_together_next_to_each_other():
    first, second = noise(1), noise(2)
    frames = {
        "AAAA": closes(first + noise(10) * 0.1),
        "BBBB": closes(second + noise(11) * 0.1),
        "CCCC": closes(first + noise(12) * 0.1),
        "DDDD": closes(second + noise(13) * 0.1),
    }
    result = concentration.check(picks("AAAA", "BBBB", "CCCC", "DDDD"), frames, dict.fromkeys(frames, "Coal"))
    order = result["tickers"]
    assert abs(order.index("AAAA") - order.index("CCCC")) == 1
    assert abs(order.index("BBBB") - order.index("DDDD")) == 1
    matrix = np.array(result["matrix"])
    assert np.allclose(matrix, matrix.T)
    assert np.allclose(np.diag(matrix), 1)


def test_only_the_recent_window_counts():
    shared_then, today = noise(1, DAYS - 126), noise(2, 126)
    frames = {
        "AAAA": closes(np.concatenate([shared_then, today])),
        "BBBB": closes(np.concatenate([shared_then, noise(3, 126)])),
    }
    result = concentration.check(picks("AAAA", "BBBB"), frames, dict.fromkeys(frames, "Coal"))
    assert abs(result["avg_corr"]) < 0.25


def test_closest_pairs_are_listed_strongest_first():
    shared = noise(1)
    frames = {
        "AAAA": closes(shared + noise(2) * 0.2),
        "BBBB": closes(shared + noise(3) * 0.6),
        "CCCC": closes(shared + noise(4) * 0.2),
    }
    result = concentration.check(picks("AAAA", "BBBB", "CCCC"), frames, dict.fromkeys(frames, "Coal"))
    pairs = result["close_pairs"]
    assert pairs[0]["corr"] >= pairs[-1]["corr"]
    assert {pairs[0]["a"], pairs[0]["b"]} == {"AAAA", "CCCC"}


def test_a_stock_too_new_to_measure_is_left_out_of_the_heatmap():
    frames = {"AAAA": closes(noise(1)), "BBBB": closes(noise(2)), "NEWW": closes(noise(3, 20))}
    cfg = replace(CONFIG, conc_min_days=60)
    result = concentration.check(picks("AAAA", "BBBB", "NEWW"), frames, dict.fromkeys(frames, "Coal"), cfg)
    assert "NEWW" not in result["tickers"]
    assert result["unmeasured"] == ["NEWW"]
