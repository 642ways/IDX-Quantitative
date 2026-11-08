from dataclasses import replace

import numpy as np
import pandas as pd
import pytest

from idxquant import diffusion
from idxquant.config import CONFIG

DAYS = 1300


def frame(returns: np.ndarray, volume: float, end: str = "2026-11-06") -> pd.DataFrame:
    close = 1000 * np.exp(np.cumsum(returns))
    days = pd.bdate_range(end=end, periods=len(returns))
    return pd.DataFrame({"close": close, "volume": np.full(len(returns), volume)}, index=days)


def noise(seed: int, scale: float = 0.01, days: int = DAYS) -> np.ndarray:
    return np.random.default_rng(seed).normal(0, scale, days)


def market(lag_days: int = 5, sectors: int = 4, followers: int = 3, strength: float = 1.0):
    """Each sector has one heavily traded leader; its followers repeat the leader's move a week later."""
    frames, sector_of = {}, {}
    for s in range(sectors):
        lead = noise(100 + s, 0.02)
        frames[f"L{s}"] = frame(lead, volume=1e8)
        sector_of[f"L{s}"] = f"S{s}"
        for f in range(followers):
            echo = np.concatenate([np.zeros(lag_days), lead[:-lag_days]]) * strength
            frames[f"F{s}{f}"] = frame(echo + noise(200 + 10 * s + f, 0.01), volume=1e6)
            sector_of[f"F{s}{f}"] = f"S{s}"
    return frames, sector_of


def test_the_busiest_stocks_in_each_sector_lead():
    frames, sector_of = market()
    _, value = diffusion.weekly(frames)
    found = diffusion.leaders(value.iloc[-1], sector_of, CONFIG)
    assert found == {"S0": ["L0"], "S1": ["L1"], "S2": ["L2"], "S3": ["L3"]}


def test_a_sector_too_small_to_split_has_no_leaders():
    frames = {"A": frame(noise(1), 1e8), "B": frame(noise(2), 1e6)}
    _, value = diffusion.weekly(frames)
    assert diffusion.leaders(value.iloc[-1], {"A": "Coal", "B": "Coal"}, CONFIG) == {}


def test_leaders_are_chosen_from_past_trading_only():
    frames, sector_of = market()
    later = {t: f.copy() for t, f in frames.items()}
    later["F00"].loc[later["F00"].index[-100:], "volume"] = 1e10
    _, before = diffusion.weekly(frames)
    _, after = diffusion.weekly(later)
    week = before.index[-30]
    assert diffusion.leaders(before.loc[week], sector_of, CONFIG) == diffusion.leaders(after.loc[week], sector_of, CONFIG)


def test_the_gap_is_how_far_a_follower_trailed_its_leaders():
    frames, sector_of = market()
    found = diffusion.panel(frames, sector_of, CONFIG)
    row = found.dropna().iloc[-1]
    assert row["gap"] == pytest.approx(row["leaders_ret"] - row["own_ret"])
    assert row["ticker"].startswith("F")


def test_the_check_finds_followers_catching_up_and_down():
    frames, sector_of = market()
    check = diffusion.check(diffusion.panel(frames, sector_of, CONFIG), CONFIG)
    assert check["up"]["excess"] > 0.01
    assert check["down"]["excess"] < -0.01
    assert check["up"]["t_stat"] > 2
    assert check["edge"] is True


def test_the_check_reports_no_edge_when_followers_move_on_their_own():
    frames, sector_of = market(strength=0.0)
    check = diffusion.check(diffusion.panel(frames, sector_of, CONFIG), CONFIG)
    assert abs(check["up"]["excess"]) < 0.005
    assert check["edge"] is False


def test_lagging_means_leaders_moved_far_and_the_follower_less_than_half_as_far():
    rows = pd.DataFrame({"leaders_ret": [0.05, 0.05, 0.02, -0.05, -0.05], "own_ret": [0.01, 0.04, 0.0, -0.01, -0.06]})
    assert list(diffusion.lagging(rows, 1, CONFIG)) == [True, False, False, False, False]
    assert list(diffusion.lagging(rows, -1, CONFIG)) == [False, False, False, True, False]


def test_a_follower_moving_hard_the_other_way_has_its_own_story():
    rows = pd.DataFrame({"leaders_ret": [0.05, 0.05, -0.05], "own_ret": [-0.02, -0.17, 0.08]})
    assert list(diffusion.lagging(rows, 1, CONFIG)) == [True, False, False]
    assert list(diffusion.lagging(rows, -1, CONFIG)) == [False, False, False]


def test_today_lists_lagging_followers_furthest_behind_first():
    frames, sector_of = market()
    found = diffusion.today(frames, sector_of, CONFIG)
    gaps = [row["gap"] for row in found["candidates"]]
    assert gaps == sorted(gaps, reverse=True)
    assert all(row["ticker"].startswith("F") and row["leaders_ret"] >= CONFIG.diff_move for row in found["candidates"])
    assert all(row["leaders_ret"] <= -CONFIG.diff_move for row in found["warnings"])
    assert len(found["candidates"]) <= CONFIG.diff_candidates
    assert found["stocks"]["L0"]["role"] == "leader"
    assert found["stocks"]["F00"]["role"] == "follower"
    assert found["stocks"]["F00"]["leaders"] == ["L0"]
    path = found["stocks"]["F00"]["path"]
    assert len(path["stock"]) == len(path["group"]) == len(path["weeks"])
    assert found["stocks"]["L0"]["path"]["group_label"] == "Sector followers"


def snapshots(days, tones):
    """One saved result per day, with a news tone per stock."""
    return [
        {"data_date": day.strftime("%Y-%m-%d"), "stocks": {t: {"news": None if tone is None else {"tone": tone, "count": 3}} for t, tone in row.items()}}
        for day, row in zip(days, tones)
    ]


def test_news_drift_waits_for_enough_events():
    frames, sector_of = market()
    days = frames["F00"].index[-20:]
    found = diffusion.news_drift(snapshots(days, [{"F00": 0.0}] + [{"F00": 0.6}] * 19), frames, sector_of, CONFIG)
    assert found["status"] == "collecting"
    assert found["days"] == 20
    assert found["events"] == {"positive": 1, "negative": 0}


def test_a_stocks_first_saved_day_is_not_a_turn():
    tones = [{"A": 0.6, "B": None}, {"A": 0.6, "B": -0.5}]
    events = diffusion.news_events(snapshots(pd.bdate_range("2026-01-05", periods=2), tones))
    assert list(zip(events["ticker"], events["direction"])) == [("B", -1)]


def test_a_news_event_is_counted_when_the_tone_turns():
    tones = [{"A": None}, {"A": 0.5}, {"A": 0.6}, {"A": 0.0}, {"A": -0.5}]
    events = diffusion.news_events(snapshots(pd.bdate_range("2026-01-05", periods=5), tones))
    assert list(zip(events["ticker"], events["direction"])) == [("A", 1), ("A", -1)]


def test_news_drift_measures_how_much_of_the_move_comes_after_the_news():
    rng = np.random.default_rng(0)
    days = pd.bdate_range(end="2026-11-06", periods=400)
    tickers = [f"T{i}" for i in range(20)]
    returns = {t: rng.normal(0, 0.005, len(days)) for t in tickers}
    rows = [dict.fromkeys(tickers, 0.0) for _ in days]
    for i, t in enumerate(tickers):
        for start in range(20 + i, len(days) - 20, 25):
            direction = 1 if (start // 25) % 2 else -1
            rows[start][t] = 0.6 * direction
            returns[t][start + 1 : start + 6] += 0.004 * direction  # The price keeps moving for a week after
    frames = {t: frame(r, 1e6, end="2026-11-06") for t, r in returns.items()}
    found = diffusion.news_drift(snapshots(days, rows), frames, dict.fromkeys(tickers, "Coal"), replace(CONFIG, news_drift_min_events=30))
    assert found["status"] == "measured"
    assert found["positive"]["after"] > 0.01 > -0.01 > found["negative"]["after"]
    assert found["positive"]["share_after"] > 0.5
