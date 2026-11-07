"""A stock's recent prices and moving averages, for the chart on its page.

Built from the saved prices when a stock page is served or exported, so the daily results stay small.
"""
import pandas as pd

CHART_DAYS = 252  # About a year of trading days
AVERAGES = (50, 200)


def _rounded(values: pd.Series) -> list[float | None]:
    return [None if pd.isna(value) else round(float(value), 2) for value in values]


def price_history(frame: pd.DataFrame | None, until: str | None = None, days: int = CHART_DAYS) -> dict | None:
    if frame is None or frame.empty or "close" not in frame:
        return None
    closes = frame["close"].astype(float).dropna()
    if until:
        closes = closes[closes.index <= pd.Timestamp(until)]
    if closes.empty:
        return None
    # Averages are worked out on the full history first, so the chart's first days already have them
    averages = {f"ma{window}": closes.rolling(window).mean() for window in AVERAGES}
    shown = closes.index[-days:]
    return {
        "dates": [day.strftime("%Y-%m-%d") for day in shown],
        "close": _rounded(closes.loc[shown]),
        **{name: _rounded(series.loc[shown]) for name, series in averages.items()},
    }
