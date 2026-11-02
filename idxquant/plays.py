"""Turns signals into concrete playbooks and ranks them. Rounding never flatters a trade."""
from dataclasses import dataclass
import math

import pandas as pd

from idxquant.config import CONFIG
from idxquant.pairs import Pair, price_at_z, status
from idxquant.trading import net_return, round_tick

SHORT_TREND_DAYS = 50
SHORT_BREAKOUT_DAYS = 20


@dataclass
class Play:
    ticker: str
    kind: str  # "long", "short" or "pair"
    entry_low: int
    entry_high: int
    target: int
    stop: int
    days: int
    reason: str
    upside: float
    downside: float
    reward_risk: float
    pair_with: str | None


def _build(ticker, kind, entry_low, entry_high, target, stop, days, reason, min_upside, pair_with=None, cfg=CONFIG):
    """Applies the filters every play shares. Returns None when the trade isn't worth taking."""
    if stop < cfg.min_stop_price or not stop < entry_high < target:
        return None
    upside = net_return(entry_high, target, cfg)
    downside = -net_return(entry_high, stop, cfg)
    if upside < min_upside or downside <= 0:
        return None
    return Play(ticker, kind, entry_low, entry_high, target, stop, days, reason, upside, downside, upside / downside, pair_with)


def long_play(row: dict, sector_medians: dict, close: float, cfg=CONFIG) -> Play | None:
    needed = (row.get("pe"), row.get("pbv"), row.get("eps_idr"), row.get("book_value_per_share"))
    medians = (sector_medians.get("pe"), sector_medians.get("pbv"))
    if not row.get("top_composite") or row.get("stale") or None in needed or None in medians:
        return None

    fair = (medians[0] * row["eps_idr"] + medians[1] * row["book_value_per_share"]) / 2
    entry_high = round_tick(close, "up")
    return _build(
        row["ticker"],
        "long",
        round_tick(close * (1 - cfg.long_entry_band), "down"),
        entry_high,
        round_tick(min(fair, close * (1 + cfg.long_target_cap)), "down"),
        round_tick(entry_high * (1 - cfg.long_stop), "down"),
        cfg.long_days,
        "Strong factor score, priced below sector peers",
        cfg.min_up_long,
        cfg=cfg,
    )


def atr(ohlcv: pd.DataFrame, n: int = 14) -> float:
    previous = ohlcv["close"].shift(1)
    true_range = pd.concat(
        [ohlcv["high"] - ohlcv["low"], (ohlcv["high"] - previous).abs(), (ohlcv["low"] - previous).abs()],
        axis=1,
    ).max(axis=1)
    return float(true_range.iloc[-n:].mean())


def short_play(ohlcv: pd.DataFrame, *, ticker: str, cfg=CONFIG) -> Play | None:
    if len(ohlcv) < SHORT_TREND_DAYS + 1:
        return None
    close = float(ohlcv["close"].iloc[-1])
    earlier = ohlcv.iloc[-SHORT_BREAKOUT_DAYS - 1 : -1]
    in_trend = close > ohlcv["close"].iloc[-SHORT_TREND_DAYS:].mean()
    new_high = close > earlier["high"].max()
    heavy_volume = ohlcv["volume"].iloc[-1] > earlier["volume"].mean()
    if not (in_trend and new_high and heavy_volume):
        return None

    value = atr(ohlcv)
    return _build(
        ticker,
        "short",
        round_tick(close, "down"),
        round_tick(close * (1 + cfg.short_entry_band), "up"),
        round_tick(close + cfg.short_target_atr * value, "down"),
        round_tick(close - cfg.short_stop_atr * value, "down"),
        cfg.short_days,
        "New 20-day high on above-average volume",
        cfg.min_up_other,
        cfg=cfg,
    )


def pair_play(pair: Pair, close: float, other_close: float, ticker: str, cfg=CONFIG) -> Play | None:
    if status(pair.z, cfg) != "Active":
        return None
    return _build(
        ticker,
        "pair",
        round_tick(close, "down"),
        round_tick(close * (1 + cfg.pair_entry_band), "up"),
        round_tick(price_at_z(pair, cfg.z_exit, other_close), "down"),
        round_tick(price_at_z(pair, cfg.z_stop, other_close), "down"),
        math.ceil(cfg.pair_time_mult * pair.half_life),
        f"{abs(pair.z):.1f}σ cheap against {pair.b}",
        cfg.min_up_other,
        pair_with=pair.b,
        cfg=cfg,
    )


def rank(plays: list[Play], composites: dict[str, float]) -> list[Play]:
    def tie_break(ticker: str) -> float:
        value = composites.get(ticker)
        return -1.0 if value is None or math.isnan(value) else value

    ordered = sorted(plays, key=lambda p: (p.reward_risk, tie_break(p.ticker)), reverse=True)
    best = {}
    for play in ordered:
        best.setdefault(play.ticker, play)
    return list(best.values())
