import math

import numpy as np
import pandas as pd
import pytest

from idxquant.pairs import Pair, price_at_z
from idxquant.plays import Play, atr, long_play, pair_play, rank, short_play
from idxquant.trading import round_tick, tick_size

MEDIANS = {"pe": 15.0, "pbv": 3.0}


def row(**overrides):
    base = {
        "ticker": "AAAA",
        "top_composite": True,
        "pe": 10.0,
        "pbv": 2.0,
        "eps_idr": 100.0,
        "book_value_per_share": 500.0,
        "stale": False,
    }
    return base | overrides


def test_long_play_target_is_sector_fair_value():
    play = long_play(row(), {"pe": 12.0, "pbv": 2.4}, 1000.0)
    assert play.target == round_tick((12 * 100 + 2.4 * 500) / 2, "down")


def test_long_play_target_cap():
    play = long_play(row(), {"pe": 20.0, "pbv": 4.0}, 1000.0)
    assert play.target == round_tick(1000 * 1.35, "down")


def test_long_play_entry_stop_and_days():
    play = long_play(row(), MEDIANS, 1000.0)
    assert play.entry_high == 1000
    assert play.entry_low == round_tick(980, "down")
    assert play.stop == round_tick(750, "down")
    assert play.days == 365


def test_long_play_needs_fresh_data():
    assert long_play(row(stale=True), MEDIANS, 1000.0) is None


def test_long_play_needs_earnings():
    assert long_play(row(pe=None), MEDIANS, 1000.0) is None


def test_long_play_needs_top_composite():
    assert long_play(row(top_composite=False), MEDIANS, 1000.0) is None


def test_long_play_needs_sector_medians():
    assert long_play(row(), {"pe": None, "pbv": 3.0}, 1000.0) is None


def test_long_play_dropped_under_10_percent_upside():
    assert long_play(row(), {"pe": 10.5, "pbv": 2.1}, 1000.0) is None


def test_long_play_stop_under_50_drops_pick():
    assert long_play(row(eps_idr=5.0, book_value_per_share=25.0), MEDIANS, 55.0) is None


def breakout(**overrides):
    """100 days of a gentle uptrend, then a jump above the 20-day high on heavy volume."""
    days = 100
    close = np.linspace(2000, 2600, days)
    close[-1] = 2800
    volume = np.full(days, 1_000_000.0)
    volume[-1] = 3_000_000.0
    frame = pd.DataFrame(
        {"open": close, "high": close + 20, "low": close - 20, "close": close, "volume": volume},
        index=pd.bdate_range("2026-01-01", periods=days),
    )
    frame["adj_close"] = frame["close"]
    return frame


def test_short_play_on_breakout():
    assert short_play(breakout(), ticker="AAAA").kind == "short"


def test_short_play_needs_trend():
    frame = breakout()
    frame.iloc[:-20, frame.columns.get_loc("close")] = 5000.0
    frame.iloc[:-20, frame.columns.get_loc("high")] = 5020.0
    frame.iloc[:-20, frame.columns.get_loc("low")] = 4980.0
    frame.iloc[-1, frame.columns.get_loc("close")] = 2700.0
    frame.iloc[-1, frame.columns.get_loc("high")] = 2720.0
    assert short_play(frame, ticker="AAAA") is None


def test_short_play_needs_new_high():
    frame = breakout()
    frame.iloc[-1, frame.columns.get_loc("close")] = 2500.0
    assert short_play(frame, ticker="AAAA") is None


def test_short_play_needs_volume():
    frame = breakout()
    frame.iloc[-1, frame.columns.get_loc("volume")] = 500_000.0
    assert short_play(frame, ticker="AAAA") is None


def test_short_play_needs_50_days():
    assert short_play(breakout().iloc[-30:], ticker="AAAA") is None


def test_short_play_targets_use_atr():
    frame = breakout()
    play = short_play(frame, ticker="AAAA")
    value = atr(frame)
    assert play.target == round_tick(2800 + 3 * value, "down")
    assert play.stop == round_tick(2800 - 1.5 * value, "down")
    assert play.entry_high == round_tick(2800 * 1.01, "up")
    assert play.days == 14


def test_atr_on_constant_range():
    frame = pd.DataFrame({"high": [110.0] * 20, "low": [100.0] * 20, "close": [105.0] * 20})
    assert atr(frame) == pytest.approx(10.0)


def pair(z=-2.2, half_life=9.0):
    return Pair("AAAA", "BBBB", 1.0, 0.0, 0.01, half_life, z, 0.0, 0.05)


def closes(z):
    other = 2500.0
    return price_at_z(pair(z), z, other), other


def test_pair_play_only_when_active():
    close, other = closes(-1.5)
    assert pair_play(pair(z=-1.5), close, other, "AAAA") is None


def test_pair_play_not_when_broken():
    close, other = closes(-3.6)
    assert pair_play(pair(z=-3.6), close, other, "AAAA") is None


def test_pair_play_time_limit_two_half_lives():
    close, other = closes(-2.2)
    assert pair_play(pair(z=-2.2, half_life=9), close, other, "AAAA").days == 18


def test_pair_play_uses_gap_prices():
    close, other = closes(-2.2)
    play = pair_play(pair(z=-2.2), close, other, "AAAA")
    assert play.target == round_tick(price_at_z(pair(), -0.5, other), "down")
    assert play.stop == round_tick(price_at_z(pair(), -3.5, other), "down")
    assert play.pair_with == "BBBB"


def test_pair_play_dropped_under_3_percent_upside():
    tight = Pair("AAAA", "BBBB", 1.0, 0.0, 0.01, 9.0, -2.2, 0.0, 0.005)
    other = 2500.0
    assert pair_play(tight, price_at_z(tight, -2.2, other), other, "AAAA") is None


def test_prices_land_on_valid_ticks_near_band():
    play = long_play(row(eps_idr=50.0, book_value_per_share=250.0), {"pe": 13.0, "pbv": 2.6}, 505.0)
    for price in (play.entry_low, play.entry_high, play.target, play.stop):
        assert price % tick_size(price) == 0


def make(ticker, reward_risk):
    return Play(ticker, "short", 100, 101, 110, 95, 14, "why", 0.1, 0.05, reward_risk, None)


def test_rank_orders_by_reward_risk():
    ranked = rank([make("A", 1.0), make("B", 3.0), make("C", 2.0)], {})
    assert [p.ticker for p in ranked] == ["B", "C", "A"]


def test_rank_keeps_best_play_per_stock():
    ranked = rank([make("A", 1.0), make("A", 3.0)], {})
    assert len(ranked) == 1
    assert ranked[0].reward_risk == 3.0


def test_rank_breaks_ties_by_composite():
    ranked = rank([make("A", 2.0), make("B", 2.0), make("C", 2.0)], {"A": 50.0, "B": 90.0, "C": math.nan})
    assert [p.ticker for p in ranked] == ["B", "A", "C"]
