"""Sector rotation: each sector's average weekly return over recent weeks, to show where money is moving."""
import numpy as np
import pandas as pd

from idxquant.config import CONFIG

RECENT_WEEKS = 4


def _row(name: str, weekly: pd.DataFrame) -> dict:
    """Each week's return of the sector's average stock: every stock counts the same, whatever its size."""
    average = weekly.mean(axis=1, skipna=True)
    compounded = lambda values: float(np.prod(1 + values.fillna(0)) - 1)
    return {
        "sector": name,
        "stocks": weekly.shape[1],
        "returns": [None if pd.isna(value) else round(float(value), 4) for value in average],
        "total": compounded(average),
        "recent": compounded(average.iloc[-RECENT_WEEKS:]),
    }


def rotation(frames: dict[str, pd.DataFrame], sector_of: dict[str, str], cfg=CONFIG) -> dict | None:
    closes = pd.DataFrame({ticker: frame["close"] for ticker, frame in frames.items()})
    if closes.empty:
        return None
    weekly = closes.resample("W-FRI").last().pct_change(fill_method=None)
    weekly = weekly.iloc[1:].iloc[-cfg.rotation_weeks :]
    if len(weekly) < cfg.rotation_weeks:
        return None
    groups = {}
    for ticker in weekly.columns:
        groups.setdefault(sector_of.get(ticker, "Other"), []).append(ticker)
    rows = sorted((_row(name, weekly[members]) for name, members in groups.items()), key=lambda row: -row["total"])
    last_day = closes.index.max()
    return {
        "weeks": [week.strftime("%Y-%m-%d") for week in weekly.index],
        "partial": bool(last_day < weekly.index[-1]),
        "last_day": last_day.strftime("%Y-%m-%d"),
        "rows": rows,
        "all": _row("All stocks", weekly),
    }
