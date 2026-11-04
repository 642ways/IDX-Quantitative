"""Walk-forward tests. Decisions use only earlier data, entries are at the next open, fees included."""
from dataclasses import replace

import numpy as np
import pandas as pd

from idxquant.config import CONFIG
from idxquant.factors import TRADING_DAYS_PER_MONTH, momentum_12_1
from idxquant.pairs import analyse_pair, find_pairs
from idxquant.plays import SHORT_BREAKOUT_DAYS, SHORT_TREND_DAYS, pair_play, short_play
from idxquant.trading import net_return

REFORM_EVERY_DAYS = 63
SIGNAL_WINDOW_DAYS = 80  # Enough history for short_play's averages without slicing the whole frame


def summarise(trades: list[float]) -> dict:
    """Trades are compounded one after another for the drawdown, in the order given."""
    if not trades:
        return {"trades": 0, "win_rate": None, "avg_return": None, "max_drawdown": None}
    returns = np.array(trades)
    equity = np.cumprod(1 + returns)
    peak = np.maximum.accumulate(np.concatenate([[1.0], equity]))[1:]
    return {
        "trades": len(trades),
        "win_rate": float((returns > 0).mean()),
        "avg_return": float(returns.mean()),
        "max_drawdown": float((equity / peak - 1).min()),
    }


def summarise_dated(trades: list[tuple[pd.Timestamp, float]]) -> dict:
    """Trades overlap across stocks, so drawdown uses each month's average trade, compounded."""
    if not trades:
        return summarise([])
    frame = pd.DataFrame(trades, columns=["date", "result"]).sort_values("date")
    months = frame.groupby(frame["date"].dt.to_period("M"))["result"].mean()
    return summarise(frame["result"].tolist()) | {"max_drawdown": summarise(months.tolist())["max_drawdown"]}


def equity_curve(trades: list[tuple[pd.Timestamp, float]]) -> list[list]:
    """Growth of 1 when each month's average trade is compounded, as [month, value at the end of that month]."""
    if not trades:
        return []
    frame = pd.DataFrame(trades, columns=["date", "result"]).sort_values("date")
    months = frame.groupby(frame["date"].dt.to_period("M"))["result"].mean()
    equity = (1 + months).cumprod()
    return [[str(month), round(float(value), 4)] for month, value in equity.items()]


def walk(ohlc: pd.DataFrame, signal_day: int, stop: float, target: float, days: int) -> tuple | None:
    """Follows a trade from the next open. Returns entry, exit and how it ended ("stop", "target" or "time")."""
    first = signal_day + 1
    if first >= len(ohlc):
        return None
    entry = float(ohlc["open"].iloc[first])
    last = min(first + days, len(ohlc)) - 1
    for day in range(first, last + 1):
        bar = ohlc.iloc[day]
        if bar["open"] <= stop:
            return entry, float(bar["open"]), "stop"
        if bar["low"] <= stop:
            return entry, stop, "stop"
        if bar["high"] >= target:
            return entry, target, "target"
    return entry, float(ohlc["close"].iloc[last]), "time"


def simulate(ohlc: pd.DataFrame, signal_day: int, stop: float, target: float, days: int, cfg=CONFIG) -> float | None:
    """Net return of a trade entered at the next open. If a day hits both levels, assume the stop."""
    result = walk(ohlc, signal_day, stop, target, days)
    return None if result is None else net_return(result[0], result[1], cfg)


def short_signals(frame: pd.DataFrame) -> list[int]:
    """Days meeting short_play's entry conditions. Rolling windows only ever look backwards."""
    close, volume = frame["close"], frame["volume"]
    trend = close.rolling(SHORT_TREND_DAYS).mean()
    prior_high = frame["high"].shift(1).rolling(SHORT_BREAKOUT_DAYS).max()
    prior_volume = volume.shift(1).rolling(SHORT_BREAKOUT_DAYS).mean()
    mask = (close > trend) & (close > prior_high) & (volume > prior_volume)
    return [int(day) for day in np.flatnonzero(mask.to_numpy()) if day >= SHORT_TREND_DAYS]


def short_trades(prices: dict[str, pd.DataFrame], cfg=CONFIG) -> list[tuple[pd.Timestamp, float]]:
    hold_days = cfg.short_days * 5 // 7  # short_days is calendar days
    trades = []
    for ticker, frame in prices.items():
        free_from = 0
        for day in short_signals(frame):
            if day < free_from:
                continue
            window = frame.iloc[max(0, day - SIGNAL_WINDOW_DAYS) : day + 1]
            play = short_play(window, ticker=ticker, cfg=cfg)
            if play is None:
                continue
            result = simulate(frame, day, play.stop, play.target, hold_days, cfg)
            if result is not None:
                trades.append((frame.index[day], result))
                free_from = day + hold_days + 1
    return trades


def backtest_short(prices: dict[str, pd.DataFrame], cfg=CONFIG) -> dict:
    return summarise_dated(short_trades(prices, cfg))


def _pair_trades(pair, prices, logs, start, end, busy_until, cfg):
    """Trades for one fixed pair across dates[start:end], with the gap re-measured each day."""
    frame, other = prices[pair.a], prices[pair.b]
    spread = (logs[pair.a] - (pair.alpha + pair.beta * logs[pair.b])).dropna()
    mean = spread.rolling(cfg.z_window).mean()
    std = spread.rolling(cfg.z_window).std()
    zs = (spread - mean) / std
    trades = []
    for date in zs.loc[start:end].index:
        z = zs.loc[date]
        if pd.isna(z) or date <= busy_until.get(pair.a, pd.Timestamp.min):
            continue
        today = replace(pair, z=float(z), spread_mean=float(mean.loc[date]), spread_std=float(std.loc[date]))
        close = float(frame["close"].loc[date])
        play = pair_play(today, close, float(other["close"].loc[date]), pair.a, cfg)
        if play is None:
            continue
        day = frame.index.get_loc(date)
        result = simulate(frame, day, play.stop, play.target, play.days, cfg)
        if result is not None:
            trades.append((date, result))
            exit_day = min(day + play.days, len(frame) - 1)
            busy_until[pair.a] = frame.index[exit_day]
    return trades


def pair_trades(prices: dict[str, pd.DataFrame], sectors: dict[str, str], cfg=CONFIG) -> list:
    """Buys the cheap stock only. Pairs are re-chosen every quarter from earlier data."""
    logs = {ticker: np.log(frame["close"]).dropna() for ticker, frame in prices.items()}
    dates = sorted(set().union(*(series.index for series in logs.values())))
    trades, busy_until = [], {}
    for start in range(cfg.pair_lookback, len(dates) - 1, REFORM_EVERY_DAYS):
        formed = dates[start]
        history = {ticker: series.loc[:formed].iloc[-cfg.pair_lookback :] for ticker, series in logs.items()}
        history = {ticker: series for ticker, series in history.items() if len(series) >= cfg.z_window}
        window_end = dates[min(start + REFORM_EVERY_DAYS, len(dates) - 1)]
        trade_start = dates[start + 1]
        for pair in find_pairs(history, sectors, cfg):
            flipped = analyse_pair(history[pair.b], history[pair.a], (pair.b, pair.a), cfg)
            for leg in filter(None, (pair, flipped)):
                trades += _pair_trades(leg, prices, logs, trade_start, window_end, busy_until, cfg)
    return trades


def backtest_pairs(prices: dict[str, pd.DataFrame], sectors: dict[str, str], cfg=CONFIG) -> dict:
    return summarise_dated(pair_trades(prices, sectors, cfg))


def momentum_months(prices: dict[str, pd.DataFrame], cfg=CONFIG) -> list[tuple[pd.Timestamp, float]]:
    """Holds the top 20% by 12-1 momentum, re-picked monthly. Each row is one month of the portfolio."""
    closes = pd.DataFrame({ticker: frame["adj_close"] for ticker, frame in prices.items()})
    months = []
    for day in range(253, len(closes) - TRADING_DAYS_PER_MONTH - 1, TRADING_DAYS_PER_MONTH):
        history = closes.iloc[: day + 1]
        scores = {ticker: momentum_12_1(history[ticker].dropna()) for ticker in closes}
        ranked = pd.Series({t: s for t, s in scores.items() if s is not None}).sort_values(ascending=False)
        if ranked.empty:
            continue
        chosen = ranked.index[: max(1, int(len(ranked) * cfg.factor_top_pct))]
        start, end = closes.iloc[day + 1], closes.iloc[day + 1 + TRADING_DAYS_PER_MONTH]
        returns = [net_return(start[t], end[t], cfg) for t in chosen if pd.notna(start[t]) and pd.notna(end[t])]
        if returns:
            months.append((closes.index[day], float(np.mean(returns))))
    return months


def backtest_momentum(prices: dict[str, pd.DataFrame], cfg=CONFIG) -> dict:
    return summarise([result for _, result in momentum_months(prices, cfg)])
