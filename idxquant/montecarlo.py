"""Simulates how each play could end, and checks those odds against past data.

Past bars are resampled in blocks, which keeps volatile stretches together. The average
daily move is removed, because a past trend is not evidence of a future one, so the odds
reflect each stock's volatility rather than any edge in the signal.
"""
import math

import numpy as np
import pandas as pd

from idxquant.backtest import short_signals, walk
from idxquant.config import CONFIG
from idxquant.pairs import Pair
from idxquant.plays import Play, short_play
from idxquant.trading import net_return

BUCKET_EDGES = (0.0, 0.2, 0.4, 0.6, 0.8, 1.0)
CALIBRATION_SEED = 20261102


def trading_days(play: Play) -> int:
    """Pair limits are already trading days. The others are calendar days."""
    return play.days if play.kind == "pair" else play.days * 5 // 7


def block_indices(history: int, paths: int, days: int, block: int, rng: np.random.Generator) -> np.ndarray:
    blocks = math.ceil(days / block)
    starts = rng.integers(0, history - block + 1, size=(paths, blocks))
    runs = starts[:, :, None] + np.arange(block)
    return runs.reshape(paths, -1)[:, :days]


def _relative_bars(frame: pd.DataFrame, cfg) -> pd.DataFrame | None:
    """Each day's close, high and low as log moves from the previous close, with drift removed."""
    recent = frame[["high", "low", "close"]].dropna().iloc[-cfg.mc_lookback - 1 :]
    if len(recent) <= cfg.mc_block_days:
        return None
    logs = np.log(recent)
    previous = logs["close"].shift(1)
    moves = pd.DataFrame(
        {"close": logs["close"] - previous, "high": logs["high"] - previous, "low": logs["low"] - previous}
    ).dropna()
    return moves - moves["close"].mean()


def _chart(close, stopped, reached, exit_day, entry, stop, target, cfg) -> dict:
    """A thinned-out view for drawing: the spread of open and closed trades, plus a few sample paths."""
    paths, days = close.shape
    prices = np.exp(close)
    exit_level = np.where(stopped, stop, target)
    settled = np.where(np.arange(days)[None, :] >= exit_day[:, None], exit_level[:, None], prices)

    step = max(1, math.ceil(days / cfg.mc_chart_points))
    grid = np.arange(step - 1, days, step)
    if grid[-1] != days - 1:
        grid = np.append(grid, days - 1)
    p10, p50, p90 = np.percentile(settled[:, grid], [10, 50, 90], axis=0)

    def series(values) -> list[float]:
        return [round(float(entry), 2), *(round(float(value), 2) for value in values)]

    samples = []
    for path in range(min(cfg.mc_chart_paths, paths)):
        exit_at = int(exit_day[path])
        points = [[0, round(float(entry), 2)]]
        points += [[int(day) + 1, round(float(prices[path, day]), 2)] for day in grid[grid < exit_at]]
        if exit_at < days:
            points.append([exit_at + 1, round(float(exit_level[path]), 2)])
        outcome = "stop" if stopped[path] else "target" if reached[path] else "time"
        samples.append({"outcome": outcome, "points": points})

    return {
        "days": [0, *(int(day) + 1 for day in grid)],
        "p10": series(p10),
        "p50": series(p50),
        "p90": series(p90),
        "paths": samples,
    }


def _summary(high, low, close, entry, stop, target, cfg, with_chart=False) -> dict:
    """All inputs are log price paths. If a day hits both levels, assume the stop, as the backtest does."""
    paths, days = close.shape
    hit_stop, hit_target = low <= math.log(stop), high >= math.log(target)
    first_stop = np.where(hit_stop.any(axis=1), hit_stop.argmax(axis=1), days)
    first_target = np.where(hit_target.any(axis=1), hit_target.argmax(axis=1), days)
    stopped = (first_stop < days) & (first_stop <= first_target)
    reached = (first_target < days) & (first_target < first_stop)

    exits = np.exp(close[:, -1])
    exits[stopped] = stop
    exits[reached] = target
    returns = exits * (1 - cfg.sell_fee) / (entry * (1 + cfg.buy_fee)) - 1
    p10, p50, p90 = np.percentile(returns, [10, 50, 90])
    summary = {
        "paths": paths,
        "days": days,
        "target_prob": float(reached.mean()),
        "stop_prob": float(stopped.mean()),
        "neither_prob": float(1 - reached.mean() - stopped.mean()),
        "expected_return": float(returns.mean()),
        "return_p10": float(p10),
        "return_p50": float(p50),
        "return_p90": float(p90),
    }
    if with_chart:
        exit_day = np.where(stopped, first_stop, np.where(reached, first_target, days))
        summary["chart"] = _chart(close, stopped, reached, exit_day, entry, stop, target, cfg)
    return summary


def simulate_play(
    frame: pd.DataFrame,
    entry: float,
    stop: float,
    target: float,
    days: int,
    rng,
    paths: int | None = None,
    cfg=CONFIG,
    with_chart: bool = False,
) -> dict | None:
    moves = _relative_bars(frame, cfg)
    if moves is None:
        return None
    count = paths or cfg.mc_paths
    picks = block_indices(len(moves), count, days, cfg.mc_block_days, rng)
    close_moves = moves["close"].to_numpy()[picks]
    closes = math.log(entry) + np.cumsum(close_moves, axis=1)
    previous = closes - close_moves
    high = previous + moves["high"].to_numpy()[picks]
    low = previous + moves["low"].to_numpy()[picks]
    return _summary(high, low, closes, entry, stop, target, cfg, with_chart)


def simulate_pair(
    a_log: pd.Series,
    b_log: pd.Series,
    pair: Pair,
    entry: float,
    stop: float,
    target: float,
    days: int,
    other_close: float,
    rng,
    paths: int | None = None,
    cfg=CONFIG,
    with_chart: bool = False,
) -> dict | None:
    """Simulates the other stock and the gap separately, so the cheap stock still carries market risk."""
    joined = pd.concat([a_log, b_log], axis=1, join="inner").dropna().iloc[-cfg.mc_lookback - 1 :]
    if len(joined) <= cfg.mc_block_days + 1:
        return None
    y, x = joined.iloc[:, 0].to_numpy(), joined.iloc[:, 1].to_numpy()
    spread = y - (pair.alpha + pair.beta * x)
    phi = 0.5 ** (1 / pair.half_life)
    shocks = spread[1:] - pair.spread_mean - phi * (spread[:-1] - pair.spread_mean)
    other_moves = np.diff(x)
    shocks, other_moves = shocks - shocks.mean(), other_moves - other_moves.mean()

    count = paths or cfg.mc_paths
    picks = block_indices(len(shocks), count, days, cfg.mc_block_days, rng)
    other_paths = math.log(other_close) + np.cumsum(other_moves[picks], axis=1)

    fair_now = pair.alpha + pair.beta * math.log(other_close)
    gap = np.full(count, math.log(entry) - fair_now - pair.spread_mean)
    gaps = np.empty((count, days))
    for day in range(days):
        gap = phi * gap + shocks[picks[:, day]]
        gaps[:, day] = gap

    closes = pair.alpha + pair.beta * other_paths + pair.spread_mean + gaps
    return _summary(closes, closes, closes, entry, stop, target, cfg, with_chart)


def calibration_buckets(rows: list[tuple[float, bool]]) -> list[dict]:
    """Groups (predicted odds, did it happen) rows, so predictions can be compared with reality."""
    buckets = []
    for low, high in zip(BUCKET_EDGES, BUCKET_EDGES[1:]):
        inside = [row for row in rows if low <= row[0] < high or (high == 1.0 and row[0] == 1.0)]
        if inside:
            buckets.append(
                {
                    "low": low,
                    "high": high,
                    "count": len(inside),
                    "predicted": float(np.mean([row[0] for row in inside])),
                    "actual": float(np.mean([row[1] for row in inside])),
                }
            )
    return buckets


def _calibration(rows: list[tuple[float, bool]]) -> dict:
    return {
        "samples": len(rows),
        "mean_predicted": float(np.mean([row[0] for row in rows])) if rows else None,
        "mean_actual": float(np.mean([row[1] for row in rows])) if rows else None,
        "buckets": calibration_buckets(rows),
    }


def calibrate_short(prices: dict[str, pd.DataFrame], paths: int | None = None, cfg=CONFIG) -> dict:
    """At each past short-term signal, compares the target odds using only earlier data with what happened."""
    rng = np.random.default_rng(CALIBRATION_SEED)
    count = paths or cfg.mc_calibration_paths
    hold_days = cfg.short_days * 5 // 7
    rows = []
    for ticker, frame in prices.items():
        free_from = 0
        for day in short_signals(frame):
            if day < free_from or day < cfg.mc_min_history:
                continue
            history = frame.iloc[: day + 1]
            play = short_play(history.iloc[-80:], ticker=ticker, cfg=cfg)
            if play is None:
                continue
            result = walk(frame, day, play.stop, play.target, hold_days)
            if result is None:
                continue
            odds = simulate_play(history, play.entry_high, play.stop, play.target, hold_days, rng, count, cfg)
            if odds:
                rows.append((odds["target_prob"], result[2] == "target"))
                free_from = day + hold_days + 1
    return _calibration(rows)


def calibrate_long(prices: dict[str, pd.DataFrame], paths: int | None = None, cfg=CONFIG) -> dict:
    """Tests the long-term price levels each quarter. It can't test the factor score that picks the stocks."""
    rng = np.random.default_rng(CALIBRATION_SEED)
    count = paths or cfg.mc_calibration_paths
    hold_days = cfg.long_days * 5 // 7
    rows = []
    for frame in prices.values():
        for day in range(cfg.mc_min_history, len(frame) - hold_days - 1, cfg.mc_calibration_step):
            close = float(frame["close"].iloc[day])
            stop, target = close * (1 - cfg.long_stop), close * (1 + cfg.long_target_cap)
            result = walk(frame, day, stop, target, hold_days)
            odds = simulate_play(frame.iloc[: day + 1], close, stop, target, hold_days, rng, count, cfg)
            if result and odds:
                rows.append((odds["target_prob"], result[2] == "target"))
    return _calibration(rows) | {"stop": cfg.long_stop, "target": cfg.long_target_cap}
