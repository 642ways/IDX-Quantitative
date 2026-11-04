"""Statistical arbitrage: find cointegrated same-sector pairs and measure how far apart they are."""
from dataclasses import dataclass, field
from itertools import combinations
import math

import numpy as np
import pandas as pd
from statsmodels.stats.multitest import multipletests
from statsmodels.tsa.stattools import coint

from idxquant.config import CONFIG

MIN_OVERLAP_DAYS = 252
MIN_MOVING_SHARE = 0.2  # A stock whose price changed on fewer days than this was stuck, not trading


@dataclass
class Pair:
    """Stock `a` is regressed on `b`. A negative z means `a` is cheap against `b`."""

    a: str
    b: str
    beta: float
    alpha: float
    pvalue: float
    half_life: float
    z: float
    spread_mean: float
    spread_std: float
    recent_z: tuple = field(default=())  # The gap on each of the last z_window days, ending with z


def _half_life(spread: pd.Series) -> float | None:
    lagged = spread.shift(1).dropna()
    change = spread.diff().dropna()
    speed = np.polyfit(lagged.to_numpy(), change.to_numpy(), 1)[0]
    return math.log(2) / -speed if speed < 0 else None


def analyse_pair(a: pd.Series, b: pd.Series, names: tuple[str, str] = ("a", "b"), cfg=CONFIG) -> Pair | None:
    """Both inputs are log prices."""
    try:
        return _analyse(a, b, names, cfg)
    except np.linalg.LinAlgError:
        return None  # A price stuck near flat for years can leave the fit unsolvable, and that's no pair either


def _analyse(a: pd.Series, b: pd.Series, names: tuple[str, str], cfg) -> Pair | None:
    joined = pd.concat([a, b], axis=1, join="inner").dropna().iloc[-cfg.pair_lookback :]
    if len(joined) < MIN_OVERLAP_DAYS:
        return None
    y, x = joined.iloc[:, 0], joined.iloc[:, 1]
    if min((y.diff() != 0).mean(), (x.diff() != 0).mean()) < MIN_MOVING_SHARE:
        return None

    beta, alpha = np.polyfit(x.to_numpy(), y.to_numpy(), 1)
    if beta <= 0:
        return None
    spread = y - (alpha + beta * x)
    half_life = _half_life(spread)
    recent = spread.iloc[-cfg.z_window :]
    if half_life is None or recent.std() == 0:
        return None

    pvalue = coint(y, x, trend="c", maxlag=1, autolag=None)[1]
    gaps = (recent - recent.mean()) / recent.std()
    z = gaps.iloc[-1]
    return Pair(
        a=names[0],
        b=names[1],
        beta=float(beta),
        alpha=float(alpha),
        pvalue=float(pvalue),
        half_life=float(half_life),
        z=float(z),
        spread_mean=float(recent.mean()),
        spread_std=float(recent.std()),
        recent_z=tuple(round(float(gap), 2) for gap in gaps),
    )


def find_pairs(prices: dict[str, pd.Series], sectors: dict[str, str], cfg=CONFIG) -> list[Pair]:
    """Log prices in, surviving pairs out. Each pair is oriented so `a` is the cheaper stock."""
    tested = []
    for first, second in combinations(sorted(prices), 2):
        if sectors.get(first) != sectors.get(second):
            continue
        pair = analyse_pair(prices[first], prices[second], (first, second), cfg)
        if pair is not None:
            tested.append(pair)
    if not tested:
        return []

    keep = multipletests([p.pvalue for p in tested], alpha=cfg.pair_pvalue, method="fdr_bh")[0]
    found = []
    for pair, passed in zip(tested, keep):
        if not passed or not cfg.pair_hl_min <= pair.half_life <= cfg.pair_hl_max:
            continue
        if pair.z > 0:
            flipped = analyse_pair(prices[pair.b], prices[pair.a], (pair.b, pair.a), cfg)
            pair = flipped or pair
        found.append(pair)
    return found


def status(z: float, cfg=CONFIG) -> str:
    if z <= cfg.z_stop:
        return "Broken"
    if z <= cfg.z_active:
        return "Active"
    if z <= cfg.z_watch:
        return "Watch"
    return "None"


def price_at_z(pair: Pair, z: float, other_price: float) -> float:
    """The price of stock `a` at which the gap would equal `z`, given stock `b`'s price."""
    fair = pair.alpha + pair.beta * math.log(other_price)
    return math.exp(fair + pair.spread_mean + z * pair.spread_std)
