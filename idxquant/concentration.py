"""How much today's picks overlap: by sector, and by how closely their prices move together.

Buying five stocks that rise and fall together is close to one large bet. This measures that from the
last few months of daily returns, so the reader can spread their money on purpose.
"""
from itertools import combinations

import numpy as np
import pandas as pd
from scipy.cluster.hierarchy import leaves_list, linkage
from scipy.spatial.distance import squareform

from idxquant.config import CONFIG

TOP_PAIRS = 5


def _order(corr: pd.DataFrame) -> list[str]:
    """Stocks that move together sit next to each other, so the heatmap shows them as blocks."""
    if len(corr) < 3:
        return list(corr.index)
    distance = (1 - corr.fillna(0).clip(-1, 1)).to_numpy(copy=True)
    np.fill_diagonal(distance, 0)
    tree = linkage(squareform(distance, checks=False), method="average")
    return [corr.index[i] for i in leaves_list(tree)]


def _groups(corr: pd.DataFrame, threshold: float) -> list[list[str]]:
    """Stocks linked by a chain of strong correlations, largest group first."""
    seen, groups = set(), []
    for start in corr.index:
        if start in seen:
            continue
        group, waiting = [], [start]
        while waiting:
            ticker = waiting.pop()
            if ticker in seen:
                continue
            seen.add(ticker)
            group.append(ticker)
            waiting += [other for other in corr.index if other not in seen and corr.loc[ticker, other] >= threshold]
        groups.append(group)
    return sorted((g for g in groups if len(g) > 1), key=len, reverse=True)


def _names(tickers: list[str]) -> str:
    return tickers[0] if len(tickers) == 1 else f"{', '.join(tickers[:-1])} and {tickers[-1]}"


def check(picks: list[dict], frames: dict[str, pd.DataFrame], sectors: dict[str, str], cfg=CONFIG) -> dict | None:
    tickers = list(dict.fromkeys(pick["ticker"] for pick in picks if pick["ticker"] in frames))
    if len(tickers) < 2:
        return None
    returns = pd.DataFrame({ticker: np.log(frames[ticker]["close"]).diff() for ticker in tickers}).iloc[-cfg.conc_window_days :]
    measured = [ticker for ticker in tickers if returns[ticker].count() >= cfg.conc_min_days]
    unmeasured = [ticker for ticker in tickers if ticker not in measured]
    if len(measured) < 2:
        return None
    corr = returns[measured].corr(min_periods=cfg.conc_min_days)
    filled = corr.fillna(0).to_numpy(copy=True)
    np.fill_diagonal(filled, 1)
    count = len(measured)
    # The participation ratio of the correlation matrix: n identical stocks give 1, n unrelated ones give n
    effective = float(count**2 / (filled**2).sum())
    off_diagonal = filled[~np.eye(count, dtype=bool)]

    pairs = sorted(
        ({"a": a, "b": b, "corr": float(corr.loc[a, b])} for a, b in combinations(measured, 2) if corr.loc[a, b] >= cfg.conc_pair_corr),
        key=lambda pair: -pair["corr"],
    )[:TOP_PAIRS]

    by_sector = {}
    for ticker in tickers:
        by_sector.setdefault(sectors.get(ticker, "Other"), []).append(ticker)
    sector_rows = sorted(
        ({"sector": sector, "count": len(members), "tickers": members} for sector, members in by_sector.items()),
        key=lambda row: (-row["count"], row["sector"]),
    )

    warnings = [
        f"{row['count']} of {len(tickers)} picks are {row['sector']} stocks."
        for row in sector_rows
        if row["count"] >= cfg.conc_min_sector and row["count"] / len(tickers) >= cfg.conc_sector_share
    ]
    warnings += [
        f"{_names(group)} move together (daily correlation {cfg.conc_pair_corr:.1f} or more), so buying all of them is close to one bet."
        for group in _groups(corr.fillna(0), cfg.conc_pair_corr)
        if len(group) >= 3
    ]
    if count >= 4 and effective <= count / 2:
        warnings.append(f"Together, the {count} picks behave like about {round(effective)} independent bets.")

    order = _order(corr)
    return {
        "tickers": order,
        "matrix": [[round(float(corr.loc[a, b]), 2) if pd.notna(corr.loc[a, b]) else None for b in order] for a in order],
        "sector_of": {ticker: sectors.get(ticker, "Other") for ticker in order},
        "window_days": cfg.conc_window_days,
        "effective_bets": effective,
        "avg_corr": float(off_diagonal.mean()),
        "close_pairs": pairs,
        "sectors": sector_rows,
        "unmeasured": unmeasured,
        "warnings": warnings,
    }
