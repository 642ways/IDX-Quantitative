"""Machine learning on past setups, for more information before buying.

Two models learn from every stock's past prices:
- ML odds: a gradient-boosted classifier estimating how often a trade like today's reached its target
  before its stop, given the price pattern and the market at the time.
- Similar past setups: the past moments that looked most like a stock today, and what happened next.

Both are checked walk-forward: each year is predicted only by a model trained on trades that had
already finished before that year began. Free data has no usable history of company financials, so the
models see price, volume and market measures only, and say nothing about value or quality.
"""
from dataclasses import dataclass

import numpy as np
import pandas as pd
from sklearn.ensemble import HistGradientBoostingClassifier
from sklearn.inspection import permutation_importance
from sklearn.metrics import roc_auc_score
from sklearn.neighbors import NearestNeighbors

from idxquant.backtest import SIGNAL_WINDOW_DAYS, short_signals
from idxquant.config import CONFIG
from idxquant.montecarlo import calibration_buckets
from idxquant.plays import short_play

MONTH, QUARTER, YEAR = 21, 63, 252
FEATURES = (
    ("ret_1m", "1-month return"),
    ("ret_3m", "3-month return"),
    ("mom_12_1", "12-month momentum"),
    ("volatility", "Volatility"),
    ("from_high", "Distance from 1-year high"),
    ("vs_ma200", "Distance from 200-day average"),
    ("activity", "Trading activity"),
    ("ihsg_3m", "IHSG 3-month return"),
    ("ihsg_vol", "IHSG volatility"),
)
COLUMNS = [key for key, _ in FEATURES]
# Similar setups match on the stock's own pattern. With the IHSG measures in, every match came from the same
# few weeks as today, so the setups only echoed the current market, which the ML odds already cover.
MATCH_COLUMNS = [key for key in COLUMNS if not key.startswith("ihsg")]
LABELS = dict(FEATURES)
SHARE = 0.2  # The top and bottom fifth of predictions are compared with each other
DRIVERS = 4
IMPORTANCE_REPEATS = 5
MIN_AUC = 0.55  # Below this, an odds model ranks setups little better than a coin
MIN_RANK_IC = 0.02  # Below this, similar setups don't sort stocks usefully


def _price(frame: pd.DataFrame) -> pd.Series:
    """Dividend-adjusted where Yahoo has it, so payouts don't look like price drops."""
    if "adj_close" not in frame:
        return frame["close"]
    return frame["adj_close"].where(frame["adj_close"] > 0, frame["close"])


def _market_measures(market: pd.Series | None, index: pd.Index) -> pd.DataFrame:
    if market is None or market.empty:
        return pd.DataFrame({"ihsg_3m": np.nan, "ihsg_vol": np.nan}, index=index)
    measures = pd.DataFrame(
        {
            "ihsg_3m": market / market.shift(QUARTER) - 1,
            "ihsg_vol": np.log(market).diff().rolling(QUARTER).std() * np.sqrt(YEAR),
        }
    )
    # The index may trade on slightly different days, so each stock day takes the latest reading so far
    return measures.reindex(measures.index.union(index)).ffill().reindex(index)


def features(frame: pd.DataFrame, market: pd.Series | None) -> pd.DataFrame:
    """One row per trading day, built only from that day and earlier."""
    price = _price(frame)
    value = frame["close"] * frame["volume"]
    activity = value.rolling(20).mean() / value.rolling(120).mean()
    measures = pd.DataFrame(
        {
            "ret_1m": price / price.shift(MONTH) - 1,
            "ret_3m": price / price.shift(QUARTER) - 1,
            "mom_12_1": price.shift(MONTH) / price.shift(YEAR) - 1,
            "volatility": np.log(price).diff().rolling(QUARTER).std() * np.sqrt(YEAR),
            "from_high": price / price.rolling(YEAR).max() - 1,
            "vs_ma200": price / price.rolling(200).mean() - 1,
            "activity": np.log(activity.where(activity > 0)),  # Blank, not minus infinity, for a stock with no trades
        },
        index=frame.index,
    ).join(_market_measures(market, frame.index))
    return measures[COLUMNS].replace([np.inf, -np.inf], np.nan)


def outcome(open_: np.ndarray, high: np.ndarray, low: np.ndarray, first: int, last: int, stop: float, target: float) -> str:
    """backtest.walk's rules on plain arrays: a gap through or touch of the stop beats the target that day."""
    stopped = (open_[first : last + 1] <= stop) | (low[first : last + 1] <= stop)
    reached = high[first : last + 1] >= target
    either = stopped | reached
    if not either.any():
        return "time"
    return "stop" if stopped[int(np.argmax(either))] else "target"


def _arrays(frame: pd.DataFrame) -> tuple[np.ndarray, ...]:
    return tuple(frame[key].to_numpy(dtype=float) for key in ("open", "high", "low", "close"))


def samples(frames: dict[str, pd.DataFrame], market: pd.Series | None, cfg=CONFIG) -> pd.DataFrame:
    """Each stock once a month: its measures, whether a long trade from there worked, and what came next.

    The long trade uses the app's own levels (+long_target_cap, -long_stop, long_days) from that close.
    A row is only labelled once the whole holding period is over, and `known` is the day that happened.
    """
    hold = cfg.long_days * 5 // 7
    rows = []
    for ticker, frame in frames.items():
        measured = features(frame, market).to_numpy()
        open_, high, low, close = _arrays(frame)
        price = _price(frame).to_numpy(dtype=float)
        dates, count = frame.index, len(frame)
        for day in range(YEAR, count, cfg.ml_step_days):
            row = {"ticker": ticker, "date": dates[day], **dict(zip(COLUMNS, measured[day]))}
            if day + hold + 1 < count:
                ended = outcome(open_, high, low, day + 1, day + hold, close[day] * (1 - cfg.long_stop), close[day] * (1 + cfg.long_target_cap))
                row |= {"hit": ended == "target", "known": dates[day + hold + 1]}
            if day + QUARTER < count:
                row |= {"fwd_3m": price[day + QUARTER] / price[day] - 1, "known_3m": dates[day + QUARTER]}
            if day + YEAR < count:
                row["fwd_12m"] = price[day + YEAR] / price[day] - 1
            rows.append(row)
    columns = ["ticker", "date", *COLUMNS, "hit", "known", "fwd_3m", "known_3m", "fwd_12m"]
    return _dated(pd.DataFrame(rows, columns=columns))


def short_samples(frames: dict[str, pd.DataFrame], market: pd.Series | None, cfg=CONFIG) -> pd.DataFrame:
    """Every past short-term breakout signal, with the same one-trade-at-a-time rule as the backtest."""
    hold = cfg.short_days * 5 // 7
    rows = []
    for ticker, frame in frames.items():
        measured = features(frame, market).to_numpy()
        open_, high, low, _ = _arrays(frame)
        dates, count, free_from = frame.index, len(frame), 0
        for day in short_signals(frame):
            if day < free_from or day < YEAR or day + hold + 1 >= count:
                continue
            play = short_play(frame.iloc[max(0, day - SIGNAL_WINDOW_DAYS) : day + 1], ticker=ticker, cfg=cfg)
            if play is None:
                continue
            ended = outcome(open_, high, low, day + 1, day + hold, play.stop, play.target)
            rows.append({"ticker": ticker, "date": dates[day], **dict(zip(COLUMNS, measured[day])), "hit": ended == "target", "known": dates[day + hold + 1]})
            free_from = day + hold + 1
    return _dated(pd.DataFrame(rows, columns=["ticker", "date", *COLUMNS, "hit", "known"]))


def _dated(data: pd.DataFrame) -> pd.DataFrame:
    """Dates as real datetimes even when a column is empty or partly blank."""
    for column in ("date", "known", "known_3m"):
        if column in data:
            data[column] = pd.to_datetime(data[column])
    return data


def _labelled(data: pd.DataFrame) -> pd.DataFrame:
    found = data.dropna(subset=["known"])
    return found.assign(hit=found["hit"].astype(bool))


def _classifier() -> HistGradientBoostingClassifier:
    """Shallow trees and strong smoothing: past market data is noisy, and a flexible model just memorises it."""
    return HistGradientBoostingClassifier(
        max_depth=3,
        learning_rate=0.05,
        max_iter=200,
        min_samples_leaf=100,
        l2_regularization=1.0,
        early_stopping=False,
        random_state=0,
    )


def folds(data: pd.DataFrame, known: str, cfg=CONFIG):
    """Yearly walk-forward splits: (year, training rows, test rows), training only on outcomes known before the year."""
    if data.empty:
        return
    for year in sorted(data["date"].dt.year.unique()):
        start = pd.Timestamp(year=year, month=1, day=1)
        train = data.index[data[known] < start]
        test = data.index[data["date"].dt.year == year]
        if len(train) >= cfg.ml_min_train and len(test):
            yield int(year), train, test


def fit(data: pd.DataFrame, cfg=CONFIG) -> HistGradientBoostingClassifier | None:
    labelled = _labelled(data)
    if len(labelled) < cfg.ml_min_train or labelled["hit"].nunique() < 2:
        return None
    return _classifier().fit(labelled[COLUMNS], labelled["hit"])


def odds_check(data: pd.DataFrame, cfg=CONFIG) -> dict | None:
    """How the odds model did on years it hadn't seen, against simply guessing the past hit rate."""
    labelled = _labelled(data).reset_index(drop=True)
    tested, last = [], None
    for year, train, test in folds(labelled, "known", cfg):
        if labelled.loc[train, "hit"].nunique() < 2:
            continue
        model = _classifier().fit(labelled.loc[train, COLUMNS], labelled.loc[train, "hit"])
        predicted = model.predict_proba(labelled.loc[test, COLUMNS])[:, 1]
        tested.append(pd.DataFrame({"year": year, "prob": predicted, "base": labelled.loc[train, "hit"].mean(), "hit": labelled.loc[test, "hit"].to_numpy()}))
        last = (model, test)
    if not tested:
        return None
    result = pd.concat(tested, ignore_index=True)
    actual = result["hit"].astype(float)
    ranked = result.groupby("year")["prob"].rank(pct=True)
    model, test = last
    importance = []
    if labelled.loc[test, "hit"].nunique() == 2:
        scores = permutation_importance(
            model, labelled.loc[test, COLUMNS], labelled.loc[test, "hit"], scoring="roc_auc", n_repeats=IMPORTANCE_REPEATS, random_state=0
        )
        importance = sorted(
            ({"feature": key, "label": LABELS[key], "drop": float(drop)} for key, drop in zip(COLUMNS, scores.importances_mean)),
            key=lambda item: -item["drop"],
        )
    return {
        "samples": len(result),
        "years": [int(result["year"].min()), int(result["year"].max())],
        "auc": float(roc_auc_score(actual, result["prob"])) if actual.nunique() == 2 else None,
        "brier": float(((result["prob"] - actual) ** 2).mean()),
        "brier_base": float(((result["base"] - actual) ** 2).mean()),
        "overall_rate": float(actual.mean()),
        "top_rate": float(actual[ranked > 1 - SHARE].mean()),
        "bottom_rate": float(actual[ranked <= SHARE].mean()),
        "buckets": calibration_buckets(list(zip(result["prob"], result["hit"].astype(bool)))),
        "importance": importance,
    }


def odds(model, data: pd.DataFrame, row: pd.Series) -> dict:
    """Today's odds, and the measures that moved them most.

    Each measure is swapped in turn for its typical past value: how far the odds move is that measure's
    effect. It's an approximation that ignores measures acting together.
    """
    labelled = _labelled(data)
    reference = labelled[COLUMNS].median()
    today = row[COLUMNS].astype(float)
    variants = pd.DataFrame([today] + [today.copy().where(today.index != key, reference[key]) for key in COLUMNS], columns=COLUMNS)
    predicted = model.predict_proba(variants)[:, 1]
    drivers = []
    for i, key in enumerate(COLUMNS, start=1):
        value = today[key]
        if np.isnan(value):
            continue
        past = labelled[key].dropna()
        drivers.append(
            {
                "feature": key,
                "label": LABELS[key],
                "value": float(value),
                "effect": float(predicted[0] - predicted[i]),
                "percentile": float((past <= value).mean()) if len(past) else None,
            }
        )
    drivers.sort(key=lambda item: -abs(item["effect"]))
    return {
        "prob": float(predicted[0]),
        "base_rate": float(labelled["hit"].mean()),
        "samples": len(labelled),
        "drivers": drivers[:DRIVERS],
    }


def _summary(rows: pd.DataFrame) -> dict:
    known = rows["fwd_12m"].dropna()
    return {
        "median_3m": float(rows["fwd_3m"].median()),
        "up_3m": float((rows["fwd_3m"] > 0).mean()),
        "median_12m": float(known.median()) if len(known) else None,
        "up_12m": float((known > 0).mean()) if len(known) else None,
    }


@dataclass
class _Scale:
    centre: pd.Series
    spread: pd.Series

    def apply(self, rows: pd.DataFrame) -> np.ndarray:
        columns = list(self.centre.index)
        return ((rows[columns].astype(float).fillna(self.centre) - self.centre) / self.spread).to_numpy()


def _scale(pool: pd.DataFrame) -> _Scale:
    centre = pool[MATCH_COLUMNS].median()
    spread = pool[MATCH_COLUMNS].std().replace(0, 1).fillna(1)
    return _Scale(centre.fillna(0), spread)


def _nearest(finder, scaled, pool_tickers, pool_dates, tickers, dates, wanted, recent_days) -> np.ndarray:
    """The `wanted` nearest rows for each query, skipping the same stock's own recent moments."""
    extra = min(len(pool_tickers), wanted * 4)
    _, found = finder.kneighbors(scaled, n_neighbors=extra)
    same = pool_tickers[found] == np.asarray(tickers)[:, None]
    recent = pool_dates[found] > (np.asarray(dates, dtype="datetime64[ns]") - np.timedelta64(recent_days, "D"))[:, None]
    allowed = ~(same & recent)
    order = np.argsort(~allowed, axis=1, kind="stable")[:, :wanted]
    return np.take_along_axis(found, order, axis=1)


class Similar:
    """Finds the past moments, across all stocks, that looked most like a stock does today."""

    def __init__(self, data: pd.DataFrame, cfg=CONFIG):
        self.cfg = cfg
        self.pool = data.dropna(subset=["fwd_3m"]).reset_index(drop=True)
        self.scale = _scale(self.pool)
        self.finder = NearestNeighbors().fit(self.scale.apply(self.pool))
        self.tickers = self.pool["ticker"].to_numpy()
        self.dates = self.pool["date"].to_numpy(dtype="datetime64[ns]")
        self.baseline = _summary(self.pool)

    def query(self, row: pd.Series, ticker: str, today) -> dict:
        wanted = min(self.cfg.ml_neighbours, len(self.pool))
        query = self.scale.apply(pd.DataFrame([row[MATCH_COLUMNS]], columns=MATCH_COLUMNS))
        picked = _nearest(self.finder, query, self.tickers, self.dates, [ticker], [pd.Timestamp(today)], wanted, self.cfg.ml_recent_days)[0]
        rows = self.pool.iloc[picked]
        examples = [
            {
                "ticker": r.ticker,
                "date": r.date.strftime("%Y-%m-%d"),
                "ret_3m": float(r.fwd_3m),
                "ret_12m": None if pd.isna(r.fwd_12m) else float(r.fwd_12m),
            }
            for r in rows.head(self.cfg.ml_examples).itertuples()
        ]
        return {"count": len(rows), **_summary(rows), "baseline": self.baseline, "examples": examples}


def similar_check(data: pd.DataFrame, cfg=CONFIG) -> dict | None:
    """Each year, predicts every stock's next 3 months from its similar past setups, using only earlier ones.

    The rank IC is the correlation, within each month, between the predicted order of stocks and how they
    actually did. Zero means no skill; 0.05 is already useful in stock prediction.
    """
    known = data.dropna(subset=["fwd_3m"]).reset_index(drop=True)
    tested = []
    for year, train, test in folds(known, "known_3m", cfg):
        pool = known.loc[train].reset_index(drop=True)
        scale = _scale(pool)
        finder = NearestNeighbors().fit(scale.apply(pool))
        queries = known.loc[test]
        wanted = min(cfg.ml_neighbours, len(pool))
        picked = _nearest(
            finder, scale.apply(queries), pool["ticker"].to_numpy(), pool["date"].to_numpy(dtype="datetime64[ns]"),
            queries["ticker"].to_numpy(), queries["date"].to_numpy(), wanted, cfg.ml_recent_days,
        )
        predicted = np.median(pool["fwd_3m"].to_numpy()[picked], axis=1)
        tested.append(pd.DataFrame({"month": queries["date"].dt.to_period("M").to_numpy(), "predicted": predicted, "actual": queries["fwd_3m"].to_numpy()}))
    if not tested:
        return None
    result = pd.concat(tested, ignore_index=True)
    usable = result.groupby("month").filter(lambda group: len(group) >= 5)
    ics = pd.Series(
        [group["predicted"].rank().corr(group["actual"].rank()) for _, group in usable.groupby("month")], dtype=float
    ).dropna()
    ranked = usable.groupby("month")["predicted"].rank(pct=True)
    return {
        "samples": len(result),
        "months": len(ics),
        "rank_ic": float(ics.mean()) if len(ics) else None,
        # Across all moments, not just within a month: does it tell good times from bad ones?
        "pooled_ic": float(result["predicted"].rank().corr(result["actual"].rank())),
        "positive_months": float((ics > 0).mean()) if len(ics) else None,
        "top_return": float(usable.loc[ranked > 1 - SHARE, "actual"].mean()),
        "bottom_return": float(usable.loc[ranked <= SHARE, "actual"].mean()),
    }


def run(frames: dict[str, pd.DataFrame], market: pd.Series | None, short_tickers: set[str], cfg=CONFIG) -> tuple[dict, dict[str, dict]]:
    """Checks both models walk-forward, then gives each stock today's ML odds and similar past setups."""
    long = samples(frames, market, cfg)
    short = short_samples(frames, market, cfg)
    evaluation = {
        "long": odds_check(long, cfg),
        "short": odds_check(short, cfg),
        "similar": similar_check(long, cfg),
        "features": [{"feature": key, "label": label} for key, label in FEATURES],
    }
    long_model, short_model = fit(long, cfg), fit(short, cfg)
    pool_size = long["fwd_3m"].notna().sum()
    similar = Similar(long, cfg) if pool_size >= cfg.ml_min_train else None
    grades = {kind: grade(evaluation[kind]) for kind in ("long", "short", "similar")}
    evaluation["grades"] = grades
    insights = {}
    for ticker, frame in frames.items():
        row = features(frame, market).iloc[-1]
        today = frame.index[-1]
        long_odds = odds(long_model, long, row) if long_model is not None else None
        short_odds = odds(short_model, short, row) if short_model is not None and ticker in short_tickers else None
        found = similar.query(row, ticker, today) if similar is not None else None
        insights[ticker] = {
            "long_odds": long_odds and long_odds | {"check": grades["long"]},
            "short_odds": short_odds and short_odds | {"check": grades["short"]},
            "similar": found and found | {"check": grades["similar"]},
        }
    return evaluation, insights


def grade(check: dict | None) -> dict | None:
    """The headline test result each stock page shows beside a model, and whether it beat the simple baseline.

    An odds model has an edge when it beat the past hit rate on unseen years and ranked setups better than
    chance (AUC of at least MIN_AUC). Similar setups have one when their rank IC reached MIN_RANK_IC.
    """
    if check is None:
        return None
    if "auc" in check:
        edge = check["auc"] is not None and check["auc"] >= MIN_AUC and check["brier"] < check["brier_base"]
        return {"auc": check["auc"], "top_rate": check["top_rate"], "bottom_rate": check["bottom_rate"], "edge": bool(edge)}
    edge = check["rank_ic"] is not None and check["rank_ic"] >= MIN_RANK_IC
    return {"rank_ic": check["rank_ic"], "pooled_ic": check["pooled_ic"], "edge": bool(edge)}
