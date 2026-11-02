"""Market types: groups similar weeks using a Gaussian mixture on several market measures.

The groups are named from their average measures, not their number, so a label keeps its
meaning when the model is refitted. Each week is labelled by a model fitted on earlier
weeks only. This is for information and doesn't change the picks.
"""
from dataclasses import dataclass
import math

import numpy as np
import pandas as pd
from sklearn.mixture import GaussianMixture

from idxquant.backtest import summarise_dated
from idxquant.config import CONFIG

FEATURES = ["ret", "vol", "breadth", "rupiah", "corr"]
TRADING_DAYS_PER_YEAR = 252
BREADTH_DAYS = 50
BREADTH_MIN_DAYS = 40
MIN_WEEKS_PER_GROUP = 5
MIN_DAYS_FOR_CORRELATION = 15
RANDOM_SEED = 20261102
HIGH_VOLATILITY = 1.0  # Standard deviations above normal
STRONG_RETURN = 0.5
WEAK_RETURN = -0.2
WEAK_BREADTH = -0.3


@dataclass
class ClusterFit:
    model: GaussianMixture
    mean: pd.Series
    std: pd.Series
    names: list[str]


def name_group(centre: pd.Series) -> str:
    """Names a group from its average measures, in standard deviations from normal."""
    if centre["vol"] > HIGH_VOLATILITY:
        return "Panic" if centre["ret"] < 0 else "Rebound"
    if centre["ret"] > STRONG_RETURN:
        return "Rally"
    if centre["ret"] < WEAK_RETURN or centre["breadth"] < WEAK_BREADTH:
        return "Weakening"
    return "Quiet"


def _average_correlation(returns: pd.DataFrame) -> float:
    usable = returns.dropna(axis=1, thresh=MIN_DAYS_FOR_CORRELATION)
    if usable.shape[1] < 2:
        return 0.0
    matrix = usable.corr().to_numpy()
    upper = matrix[np.triu_indices_from(matrix, k=1)]
    return float(np.nanmean(upper)) if not np.isnan(upper).all() else 0.0


def weekly_features(ihsg: pd.Series, closes: pd.DataFrame, usdidr: pd.Series, cfg=CONFIG) -> pd.DataFrame:
    """One row per week, taken at its last trading day. Every measure looks backwards only."""
    window = cfg.cluster_window_days
    index = ihsg.dropna().index
    prices = closes.reindex(index)
    rates = usdidr.reindex(index.union(usdidr.index)).ffill().reindex(index)
    log_index = np.log(ihsg.reindex(index))
    average = prices.rolling(BREADTH_DAYS, min_periods=BREADTH_MIN_DAYS).mean()
    measured = average.notna().sum(axis=1).replace(0, np.nan)

    daily = pd.DataFrame(
        {
            "ret": log_index.diff(window),
            "vol": log_index.diff().rolling(window).std() * math.sqrt(TRADING_DAYS_PER_YEAR),
            "breadth": (prices > average).sum(axis=1) / measured,
            "rupiah": np.log(rates).diff(window),
        }
    )
    weekly = daily.groupby(daily.index.to_period("W")).tail(1).dropna()
    returns = np.log(prices).diff()
    positions = index.get_indexer(weekly.index)
    weekly["corr"] = [_average_correlation(returns.iloc[max(0, at - window + 1) : at + 1]) for at in positions]
    return weekly[FEATURES]


def fit_groups(train: pd.DataFrame, cfg=CONFIG) -> ClusterFit | None:
    if len(train) < cfg.cluster_groups * MIN_WEEKS_PER_GROUP:
        return None
    mean, std = train.mean(), train.std().replace(0, 1.0)
    model = GaussianMixture(
        cfg.cluster_groups, covariance_type="diag", n_init=3, reg_covar=1e-3, random_state=RANDOM_SEED
    ).fit(((train - mean) / std).to_numpy())
    names = [name_group(pd.Series(centre, index=train.columns)) for centre in model.means_]
    return ClusterFit(model, mean, std, names)


def _assign(fit: ClusterFit, rows: pd.DataFrame) -> pd.DataFrame:
    """Groups that share a name count as one, so their probabilities add together."""
    probabilities = fit.model.predict_proba(((rows - fit.mean) / fit.std).to_numpy())
    by_name = pd.DataFrame(probabilities, index=rows.index, columns=fit.names).T.groupby(level=0).sum().T
    return pd.DataFrame({"label": by_name.idxmax(axis=1), "confidence": by_name.max(axis=1).clip(upper=1.0)})


def label_series(features: pd.DataFrame, cfg=CONFIG) -> pd.DataFrame:
    """Walk-forward: each stretch of weeks is labelled by a model fitted on the weeks before it."""
    pieces, fit = [], None
    for start in range(cfg.cluster_min_weeks, len(features), cfg.cluster_refit_weeks):
        fit = fit_groups(features.iloc[:start], cfg) or fit
        if fit is not None:
            pieces.append(_assign(fit, features.iloc[start : start + cfg.cluster_refit_weeks]))
    return pd.concat(pieces) if pieces else pd.DataFrame(columns=["label", "confidence"])


def current_market_type(features: pd.DataFrame, cfg=CONFIG) -> dict | None:
    labels = label_series(features, cfg)
    if labels.empty:
        return None
    names = labels["label"]
    latest = names.iloc[-1]
    changed = names[names != latest]
    since = names.index[0] if changed.empty else names.index[names.index > changed.index[-1]][0]
    joined = features.loc[labels.index].assign(label=names)
    groups = [
        {"label": label, "weeks": len(rows), "share": len(rows) / len(joined)}
        | {name: float(rows[name].mean()) for name in FEATURES}
        for label, rows in joined.groupby("label")
    ]
    return {
        "label": latest,
        "confidence": float(labels["confidence"].iloc[-1]),
        "since": since.strftime("%Y-%m-%d"),
        "features": {name: float(features[name].iloc[-1]) for name in FEATURES},
        "groups": groups,
        "history": [[day.strftime("%Y-%m-%d"), label] for day, label in names.items()],
    }


def split_by_label(trades: list[tuple[pd.Timestamp, float]], labels: pd.DataFrame) -> dict:
    """Groups trades by the latest label known on their signal day."""
    if labels.empty:
        return {}
    groups: dict[str, list] = {}
    for date, result in trades:
        position = labels.index.searchsorted(date, side="right") - 1
        if position >= 0:
            groups.setdefault(labels["label"].iloc[position], []).append((date, result))
    return {label: summarise_dated(group) for label, group in sorted(groups.items())}
