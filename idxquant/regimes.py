"""Market regimes: a two-state hidden Markov model on daily IHSG returns.

Each day's state is judged only from data up to that day (the filtered probability), never
from later days. The smoothed probabilities most libraries show look ahead, so they aren't used.
"""
from dataclasses import dataclass
import math
import warnings

import numpy as np
import pandas as pd
import statsmodels.api as sm

from idxquant.backtest import summarise_dated
from idxquant.config import CONFIG

TRADING_DAYS_PER_YEAR = 252
MIN_FIT_DAYS = 30
CALM, STRESSED = 0, 1


@dataclass
class RegimeFit:
    """Daily figures in percent. Index 0 is the calm state and 1 is the stressed state."""

    means: tuple[float, float]
    variances: tuple[float, float]
    stay: tuple[float, float]


def fit_model(returns: pd.Series) -> RegimeFit | None:
    if len(returns) < MIN_FIT_DAYS:
        return None
    model = sm.tsa.MarkovRegression(returns.to_numpy(), k_regimes=2, trend="c", switching_variance=True)
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            result = model.fit(em_iter=20, search_reps=0, disp=False)
    except (ValueError, np.linalg.LinAlgError):
        return None
    params = dict(zip(model.param_names, result.params))
    means = (params["const[0]"], params["const[1]"])
    variances = (params["sigma2[0]"], params["sigma2[1]"])
    stay = (params["p[0->0]"], 1 - params["p[1->0]"])
    if not np.isfinite([*means, *variances, *stay]).all():
        return None
    order = (0, 1) if variances[0] <= variances[1] else (1, 0)
    pick = lambda values: tuple(float(values[i]) for i in order)
    return RegimeFit(pick(means), pick(variances), pick(stay))


def filter_probs(returns: pd.Series, fit: RegimeFit) -> pd.Series:
    """Hamilton filter: the chance of the stressed state each day, using only data up to that day."""
    stay_calm, stay_stressed = fit.stay
    leave_calm, leave_stressed = 1 - stay_calm, 1 - stay_stressed
    means, variances = np.array(fit.means), np.array(fit.variances)
    calm = leave_stressed / max(leave_calm + leave_stressed, 1e-12)
    belief = np.array([calm, 1 - calm])
    probs = np.empty(len(returns))
    for day, value in enumerate(returns.to_numpy()):
        predicted = np.array(
            [
                belief[CALM] * stay_calm + belief[STRESSED] * leave_stressed,
                belief[CALM] * leave_calm + belief[STRESSED] * stay_stressed,
            ]
        )
        likelihood = np.exp(-((value - means) ** 2) / (2 * variances)) / np.sqrt(2 * np.pi * variances)
        posterior = predicted * likelihood
        total = posterior.sum()
        belief = posterior / total if total > 0 else predicted
        probs[day] = belief[STRESSED]
    return pd.Series(probs, index=returns.index)


def _returns(closes: pd.Series) -> pd.Series:
    return np.log(closes).diff().dropna() * 100


def stress_series(closes: pd.Series, cfg=CONFIG) -> pd.Series:
    """Walk-forward: the model is refitted every quarter on earlier days only, then applied forward."""
    returns = _returns(closes)
    pieces, fit = [], None
    for start in range(cfg.regime_min_history, len(returns), cfg.regime_refit_days):
        fit = fit_model(returns.iloc[:start]) or fit
        if fit is None:
            continue
        end = start + cfg.regime_refit_days
        pieces.append(filter_probs(returns.iloc[:end], fit).iloc[start:])
    return pd.concat(pieces) if pieces else pd.Series(dtype=float)


def _regime_start(flags: pd.Series) -> pd.Timestamp:
    changed = flags != flags.iloc[-1]
    if not changed.any():
        return flags.index[0]
    return flags.index[flags.index > changed[changed].index[-1]][0]


def current_regime(closes: pd.Series, cfg=CONFIG) -> dict | None:
    stress = stress_series(closes, cfg)
    fit = fit_model(_returns(closes))
    if stress.empty or fit is None:
        return None
    flags = stress > cfg.regime_threshold
    weekly = pd.DataFrame({"close": closes.reindex(stress.index), "prob": stress}).resample("W").agg(
        {"close": "last", "prob": "mean"}
    ).dropna()
    yearly_vol = lambda state: math.sqrt(fit.variances[state] * TRADING_DAYS_PER_YEAR) / 100
    return {
        "label": "Stressed" if flags.iloc[-1] else "Calm",
        "stress_prob": float(stress.iloc[-1]),
        "threshold": cfg.regime_threshold,
        "since": _regime_start(flags).strftime("%Y-%m-%d"),
        "calm_vol": yearly_vol(CALM),
        "stressed_vol": yearly_vol(STRESSED),
        "calm_days": 1 / max(1 - fit.stay[CALM], 1e-9),
        "stressed_days": 1 / max(1 - fit.stay[STRESSED], 1e-9),
        "stressed_share": float(flags.mean()),
        "history": [
            [day.strftime("%Y-%m-%d"), round(float(row["close"]), 2), round(float(row["prob"]), 3)]
            for day, row in weekly.iterrows()
        ],
    }


def split_by_regime(trades: list[tuple[pd.Timestamp, float]], stress: pd.Series, cfg=CONFIG) -> dict:
    """Groups trades by the state known on their signal day. Trades before the model starts are left out."""
    groups = {"calm": [], "stressed": []}
    for date, result in trades:
        position = stress.index.searchsorted(date, side="right") - 1
        if position >= 0:
            groups["stressed" if stress.iloc[position] > cfg.regime_threshold else "calm"].append((date, result))
    return {name: summarise_dated(group) for name, group in groups.items()}
