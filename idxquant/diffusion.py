"""Information diffusion: news reaches a sector's busiest stocks first and its quieter ones later.

Two tests of the idea, after Hong and Stein (1999) and Hou (2007):
- Lead-lag: when a sector's leaders move in a week and a follower hasn't caught up, does the follower
  catch up the next week? Tested on about ten years of weekly prices.
- News drift: when a stock's headlines turn positive or negative, does the price move that day, or keep
  drifting over the following days? This needs the news the app saves each day, so it waits until enough
  events have built up.
"""
import math

import numpy as np
import pandas as pd

from idxquant.config import CONFIG

PATH_WEEKS = 13  # About three months on the stock page
TODAY_DAYS = 5  # Today's gap is measured over the last week of trading days
MIN_FOLLOWERS = 8  # A week with fewer followers is too thin to rank


def weekly(frames: dict[str, pd.DataFrame], cfg=CONFIG) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Weekly returns, and each stock's average weekly traded value over the past weeks, up to that week."""
    closes = pd.DataFrame({ticker: frame["close"] for ticker, frame in frames.items()})
    values = pd.DataFrame({ticker: frame["close"] * frame["volume"] for ticker, frame in frames.items()})
    returns = closes.resample("W-FRI").last().pct_change(fill_method=None)
    traded = values.resample("W-FRI").sum(min_count=1).rolling(cfg.diff_value_weeks, min_periods=4).mean()
    return returns, traded


def leaders(traded: pd.Series, sector_of: dict[str, str], cfg=CONFIG) -> dict[str, list[str]]:
    """The busiest quarter of each sector, at least one stock, by traded value up to that week."""
    groups = {}
    for ticker, value in traded.dropna().items():
        groups.setdefault(sector_of.get(ticker), []).append((value, ticker))
    found = {}
    for sector, members in groups.items():
        if sector is None or len(members) < cfg.diff_min_sector:
            continue
        count = max(1, int(len(members) * cfg.diff_leader_share))
        found[sector] = [ticker for _, ticker in sorted(members, reverse=True)[:count]]
    return found


def panel(frames: dict[str, pd.DataFrame], sector_of: dict[str, str], cfg=CONFIG) -> pd.DataFrame:
    """One row per follower per week: its leaders' return, its own, the gap, and its return the next week."""
    returns, traded = weekly(frames, cfg)
    tickers = list(returns.columns)
    column = {ticker: i for i, ticker in enumerate(tickers)}
    now, after = returns.to_numpy(), returns.shift(-1).to_numpy()
    members = {}
    for ticker in tickers:
        members.setdefault(sector_of.get(ticker), []).append(ticker)
    parts = []
    for row, week in enumerate(returns.index):
        if row == 0:
            continue
        for sector, heads in leaders(traded.iloc[row], sector_of, cfg).items():
            moves = now[row, [column[t] for t in heads]]
            if np.isnan(moves).all():
                continue
            leaders_ret = float(np.nanmean(moves))
            followers = [t for t in members[sector] if t not in heads and not np.isnan(now[row, column[t]])]
            if not followers:
                continue
            cols = [column[t] for t in followers]
            own = now[row, cols]
            parts.append(
                pd.DataFrame(
                    {
                        "week": week,
                        "ticker": followers,
                        "sector": sector,
                        "leaders_ret": leaders_ret,
                        "own_ret": own,
                        "gap": leaders_ret - own,
                        "next_ret": after[row, cols],
                    }
                )
            )
    columns = ["week", "ticker", "sector", "leaders_ret", "own_ret", "gap", "next_ret"]
    return pd.concat(parts, ignore_index=True)[columns] if parts else pd.DataFrame(columns=columns)


def lagging(data: pd.DataFrame, direction: int, cfg=CONFIG) -> pd.Series:
    """Followers whose leaders moved strongly one way while they moved less than half as far that way.

    A follower that moved strongly the other way has news of its own, not a delayed reaction, so it's left out.
    """
    moved = data["leaders_ret"] * direction >= cfg.diff_move
    behind = data["own_ret"] * direction < data["leaders_ret"] * direction * cfg.diff_lag_share
    own_story = data["own_ret"] * direction <= -cfg.diff_move
    return moved & behind & ~own_story


def _slice(rows: pd.DataFrame) -> dict:
    """The next week's return above that week's average follower, averaged per week, with a t-stat across weeks."""
    per_week = rows.groupby("week")["excess"].mean()
    spread = per_week.std()
    return {
        "rows": len(rows),
        "weeks": len(per_week),
        "next_return": float(rows["next_ret"].mean()) if len(rows) else None,
        "excess": float(per_week.mean()) if len(per_week) else None,
        "t_stat": float(per_week.mean() / spread * math.sqrt(len(per_week))) if len(per_week) > 1 and spread > 0 else None,
    }


def check(data: pd.DataFrame, cfg=CONFIG) -> dict | None:
    """After leaders move, do the followers that haven't moved yet follow them the next week?

    The comparison is with the same week's average follower, so a market-wide rise or fall doesn't count.
    """
    usable = data.dropna(subset=["next_ret"])
    usable = usable.groupby("week").filter(lambda group: len(group) >= MIN_FOLLOWERS)
    if usable.empty:
        return None
    usable = usable.assign(excess=usable["next_ret"] - usable.groupby("week")["next_ret"].transform("mean"))
    up, down = _slice(usable[lagging(usable, 1, cfg)]), _slice(usable[lagging(usable, -1, cfg)])
    costs = cfg.buy_fee + cfg.sell_fee
    edge = up["excess"] is not None and up["excess"] > costs and (up["t_stat"] or 0) >= cfg.diff_min_t
    return {
        "weeks": int(usable["week"].nunique()),
        "years": [int(usable["week"].min().year), int(usable["week"].max().year)],
        "all_return": float(usable["next_ret"].mean()),
        "up": up,
        "down": down,
        "costs": costs,
        "move": cfg.diff_move,
        "edge": bool(edge),
    }


def _path(weekly_returns: pd.DataFrame, own: str, group: list[str]) -> dict:
    recent = weekly_returns.iloc[-PATH_WEEKS:]
    grow = lambda series: [round(float(value) - 1, 4) for value in (1 + series.fillna(0)).cumprod()]
    return {
        "weeks": [week.strftime("%Y-%m-%d") for week in recent.index],
        "stock": grow(recent[own]),
        "group": grow(recent[group].mean(axis=1)),
    }


def today(frames: dict[str, pd.DataFrame], sector_of: dict[str, str], cfg=CONFIG) -> dict:
    """Each stock's role in its sector, how far followers trail their leaders this week, and the widest gaps."""
    returns, traded = weekly(frames, cfg)
    if traded.empty:
        return {"stocks": {}, "candidates": []}
    heads_by_sector = leaders(traded.iloc[-1], sector_of, cfg)
    recent = {ticker: frame["close"].iloc[-1] / frame["close"].iloc[-TODAY_DAYS - 1] - 1 for ticker, frame in frames.items() if len(frame) > TODAY_DAYS}
    stocks, rows = {}, []
    for sector, heads in heads_by_sector.items():
        members = [t for t in frames if sector_of.get(t) == sector]
        followers = [t for t in members if t not in heads]
        leaders_ret = float(np.mean([recent[t] for t in heads if t in recent])) if any(t in recent for t in heads) else None
        for ticker in members:
            is_leader = ticker in heads
            own = recent.get(ticker)
            entry = {
                "role": "leader" if is_leader else "follower",
                "sector": sector,
                "leaders": heads,
                "leaders_ret": leaders_ret,
                "own_ret": None if own is None else float(own),
                "gap": None if is_leader or own is None or leaders_ret is None else float(leaders_ret - own),
                "path": _path(returns, ticker, followers if is_leader else heads)
                | {"group_label": "Sector followers" if is_leader else "Sector leaders"},
            }
            if entry["gap"] is not None:
                rows.append({"ticker": ticker, "sector": sector, "leaders": heads, "leaders_ret": leaders_ret, "own_ret": entry["own_ret"], "gap": entry["gap"]})
            stocks[ticker] = entry
    table = pd.DataFrame(rows, columns=["ticker", "sector", "leaders", "leaders_ret", "own_ret", "gap"])
    found = {}
    for name, direction in (("up", 1), ("down", -1)):
        picked = table[lagging(table, direction, cfg)] if len(table) else table
        picked = picked.assign(behind=picked["gap"] * direction).sort_values("behind", ascending=False)
        for ticker in picked["ticker"]:
            stocks[ticker]["status"] = "missed a rise" if direction > 0 else "missed a fall"
        found[name] = picked.drop(columns="behind").head(cfg.diff_candidates).to_dict("records")
    return {"stocks": stocks, "candidates": found["up"], "warnings": found["down"]}


# ---- News drift


def _tone_class(news: dict | None, lean: float) -> int | None:
    if not news:
        return None
    return 1 if news["tone"] >= lean else -1 if news["tone"] <= -lean else 0


def news_events(snapshots: list[dict], cfg=CONFIG) -> pd.DataFrame:
    """A stock's news turning positive or negative, counted on the day it turns, not every day it stays.

    A stock's first saved day isn't a turn, since there's no earlier day to turn from.
    """
    rows, previous = [], {}
    for snapshot in sorted(snapshots, key=lambda s: s.get("data_date") or ""):
        day = snapshot.get("data_date")
        if not day:
            continue
        for ticker, page in (snapshot.get("stocks") or {}).items():
            current = _tone_class((page or {}).get("news"), cfg.news_lean)
            if current in (1, -1) and ticker in previous and previous[ticker] != current:
                rows.append({"date": pd.Timestamp(day), "ticker": ticker, "direction": current})
            previous[ticker] = current
    return pd.DataFrame(rows, columns=["date", "ticker", "direction"])


def news_drift(snapshots: list[dict], frames: dict[str, pd.DataFrame], sector_of: dict[str, str], cfg=CONFIG) -> dict:
    """How much of the price move came on the news day, and how much in the days after, against the sector."""
    events = news_events(snapshots, cfg)
    days = sum(1 for s in snapshots if any((page or {}).get("news") for page in (s.get("stocks") or {}).values()))
    counts = {"positive": int((events["direction"] == 1).sum()), "negative": int((events["direction"] == -1).sum())}
    closes = pd.DataFrame({ticker: frame["close"] for ticker, frame in frames.items()})
    daily = closes.pct_change(fill_method=None)
    # Each sector's total and count per day, so a stock's peers are its sector without itself
    sector_sum, sector_count = {}, {}
    for sector in {sector_of.get(t) for t in daily.columns}:
        members = [t for t in daily.columns if sector_of.get(t) == sector]
        sector_sum[sector] = daily[members].sum(axis=1, min_count=1)
        sector_count[sector] = daily[members].notna().sum(axis=1)
    measured = []
    for event in events.itertuples():
        if event.ticker not in closes or event.date not in closes.index:
            continue
        at = closes.index.get_loc(event.date)
        if at < 1 or at + cfg.news_drift_days >= len(closes):
            continue
        sector = sector_of.get(event.ticker)
        own = daily[event.ticker]
        window = slice(at, at + cfg.news_drift_days + 1)
        peers = (sector_sum[sector].iloc[window] - own.iloc[window]) / (sector_count[sector].iloc[window] - 1)
        abnormal = own.iloc[window] - peers
        if abnormal.isna().any() or np.isinf(abnormal).any():
            continue
        measured.append({"direction": event.direction, "day0": float(abnormal.iloc[0]), "after": float(abnormal.iloc[1:].sum())})
    table = pd.DataFrame(measured, columns=["direction", "day0", "after"])
    ready = {name: int((table["direction"] == sign).sum()) for name, sign in (("positive", 1), ("negative", -1))}
    status = {"days": days, "events": counts, "measured": ready, "needed": cfg.news_drift_min_events, "horizon": cfg.news_drift_days}
    if min(ready.values()) < cfg.news_drift_min_events:
        return status | {"status": "collecting"}
    result = status | {"status": "measured"}
    for name, sign in (("positive", 1), ("negative", -1)):
        group = table[table["direction"] == sign]
        day0, after = group["day0"].mean(), group["after"].mean()
        total = day0 + after
        result[name] = {
            "events": len(group),
            "day0": float(day0),
            "after": float(after),
            "share_after": float(after / total) if total and np.sign(total) == np.sign(after) else None,
        }
    return result
