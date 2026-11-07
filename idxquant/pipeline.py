"""The daily run: fetch, score, build plays, save a snapshot for the web app."""
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict
from datetime import date, datetime, timedelta, timezone
import math
import zlib

import numpy as np
import pandas as pd

from idxquant import backtest, clusters, concentration, events, factors, learn, montecarlo, news, pairs, plays, regimes, universe, yahoo
from idxquant.config import CONFIG
from idxquant.sectors import rotation as sector_rotation
from idxquant.trading import net_return

WIB = timezone(timedelta(hours=7))
FETCH_WORKERS = 6
LIQUIDITY_WINDOW = 20
MIN_SECTOR_SIZE = 3
OUTCOME_OPEN = "Open"
INDEX_TICKER = "^JKSE"
MEDIAN_FIELDS = ("pe", "pbv", "ps", "ev_ebitda", "earnings_yield", "fcf_yield", "dividend_yield", "gross_margin", "operating_margin", "net_margin", "roe", "roa")


def drop_partial_bar(frame: pd.DataFrame, now: datetime, cfg=CONFIG) -> pd.DataFrame:
    """Today's bar still changes until the data counts as final."""
    if frame.empty or now.hour >= cfg.final_hour_wib:
        return frame
    return frame[frame.index.date < now.date()]


def latest_cutoff(now: datetime, cfg=CONFIG) -> datetime:
    """The most recent weekday moment at which a day's data became final."""
    moment = now.replace(hour=cfg.final_hour_wib, minute=0, second=0, microsecond=0)
    if moment > now:
        moment -= timedelta(days=1)
    while moment.weekday() >= 5:
        moment -= timedelta(days=1)
    return moment


def needs_refresh(now: datetime, snapshot: dict | None, cfg=CONFIG) -> bool:
    if not snapshot:
        return True
    if datetime.fromisoformat(snapshot["ran_at"]) < latest_cutoff(now, cfg):
        return True
    # Yahoo can lag past the close. Holidays look the same, so retries stop for the evening.
    in_retry_window = now.weekday() < 5 and cfg.final_hour_wib <= now.hour < cfg.retry_until_hour_wib
    data_date = snapshot.get("data_date")
    return in_retry_window and data_date is not None and data_date < now.date().isoformat()


def tradable(prices: pd.DataFrame, cfg=CONFIG) -> bool:
    if len(prices) < cfg.min_history_days:
        return False
    if (prices["volume"].iloc[-cfg.suspension_window :] == 0).any():
        return False
    traded_value = (prices["close"] * prices["volume"]).iloc[-LIQUIDITY_WINDOW:]
    return traded_value.median() >= cfg.min_value_idr


def _clean(value):
    """Makes a value JSON-safe: NaN becomes null and numpy types become plain Python."""
    if isinstance(value, dict):
        return {key: _clean(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_clean(item) for item in value]
    if isinstance(value, np.generic):
        value = value.item()
    if isinstance(value, float) and math.isnan(value):
        return None
    return value


def _fetch_all(tickers: list[str], fetcher) -> dict[str, tuple[pd.DataFrame, dict | None, dict | None]]:
    def fetch(ticker):
        try:
            prices = fetcher.fetch_prices(ticker)
        except Exception:
            prices = pd.DataFrame()
        try:
            funda = fetcher.fetch_fundamentals(ticker)
        except Exception:
            funda = None
        try:
            dated = fetcher.fetch_events(ticker)
        except Exception:
            dated = None  # Events are extra information, so a stock without them is still analysed
        return ticker, (prices, funda, dated)

    with ThreadPoolExecutor(FETCH_WORKERS) as pool:
        return dict(pool.map(fetch, tickers))


NEWS_WORKERS = 4  # Gentle on Google News: about 120 small requests a day


def _news_source(fetcher):
    """The real Yahoo fetcher pairs with Google News. Test fetchers bring their own headlines, or none."""
    return news.fetch_headlines if fetcher is yahoo else getattr(fetcher, "fetch_news", None)


def _fetch_news(tickers: list[str], names: dict[str, str], source) -> dict[str, list[dict] | None]:
    if source is None:
        return {}

    def fetch(ticker):
        try:
            return ticker, source(ticker, names[ticker])
        except Exception:
            return ticker, None  # News is extra information, so a stock without it is still analysed

    with ThreadPoolExecutor(NEWS_WORKERS) as pool:
        return dict(pool.map(fetch, tickers))


def _sector_medians(table: pd.DataFrame) -> dict[str, dict]:
    medians = {}
    for sector, group in table.groupby("sector"):
        values = {}
        for name in MEDIAN_FIELDS:
            present = pd.to_numeric(group[name], errors="coerce").dropna()
            values[name] = float(present.median()) if len(present) >= MIN_SECTOR_SIZE else None
        medians[sector] = values
    return medians


def _pair_rows(found: list[pairs.Pair], ticker: str) -> list[dict]:
    rows = []
    for pair in found:
        if ticker not in (pair.a, pair.b):
            continue
        is_cheap_side = pair.a == ticker
        signal = pairs.status(pair.z)
        rows.append(
            {
                "with": pair.b if is_cheap_side else pair.a,
                "gap": pair.z if is_cheap_side else -pair.z,
                "half_life": pair.half_life,
                "pvalue": pair.pvalue,
                "gap_history": [gap if is_cheap_side else -gap for gap in pair.recent_z],
                "status": signal if is_cheap_side or signal == "None" else "Other side",
            }
        )
    return sorted(rows, key=lambda row: row["gap"])


def _usable_bars(prices: pd.DataFrame, store, ticker: str) -> pd.DataFrame:
    """Yahoo sometimes blanks a recent bar it had earlier, so saved values fill any gaps."""
    if prices.empty:
        return prices
    saved = store.load_prices(ticker)
    filled = prices.fillna(saved.reindex(prices.index)) if not saved.empty else prices
    return filled.dropna(subset=["close"])


def _market_closes(fetcher, store, now, cfg) -> pd.Series | None:
    try:
        index = drop_partial_bar(fetcher.fetch_index(), now, cfg)
    except Exception:
        return None
    index = _usable_bars(index, store, INDEX_TICKER)
    if index.empty:
        return None
    store.save_prices(INDEX_TICKER, index)
    return index["close"]


def _market_features(fetcher, market, frames, cfg) -> pd.DataFrame | None:
    if market is None:
        return None
    try:
        rates = fetcher.fetch_usdidr_history()
    except Exception:
        return None
    if rates.empty:
        return None
    closes = pd.DataFrame({ticker: frame["close"] for ticker, frame in frames.items()})
    return clusters.weekly_features(market, closes, rates["close"], cfg)


def _backtests(frames, sectors, previous, today, market, features, cfg):
    earlier = (previous or {}).get("backtest") or {}
    same_rules = earlier.get("calibration", {}).get("long", {}).get("stop") == cfg.long_stop
    complete = earlier.get("regimes") and earlier.get("market_types") and earlier.get("equity") is not None
    if same_rules and complete and previous.get("backtest_at"):
        age = (today - date.fromisoformat(previous["backtest_at"])).days
        if age < cfg.backtest_max_age_days:
            return earlier, previous["backtest_at"]
    short = backtest.short_trades(frames, cfg)
    pair = backtest.pair_trades(frames, sectors, cfg) if len(frames) > 1 else []
    months = backtest.momentum_months(frames, cfg)
    stress = regimes.stress_series(market, cfg) if market is not None else None
    labels = clusters.label_series(features, cfg) if features is not None else None
    results = {
        "short": backtest.summarise_dated(short),
        "pair": backtest.summarise_dated(pair),
        "momentum": backtest.summarise([result for _, result in months]),
        "regimes": None
        if stress is None
        else {
            "short": regimes.split_by_regime(short, stress, cfg),
            "pair": regimes.split_by_regime(pair, stress, cfg),
            "momentum": regimes.split_by_regime(months, stress, cfg),
        },
        "market_types": None
        if labels is None
        else {
            "short": clusters.split_by_label(short, labels),
            "pair": clusters.split_by_label(pair, labels),
            "momentum": clusters.split_by_label(months, labels),
        },
        "equity": {
            "short": backtest.equity_curve(short),
            "pair": backtest.equity_curve(pair),
            "momentum": backtest.equity_curve(months),
        },
        "calibration": {
            "short": montecarlo.calibrate_short(frames, cfg=cfg),
            "long": montecarlo.calibrate_long(frames, cfg=cfg),
        },
    }
    return results, today.isoformat()


def _play_odds(play, frames, found, data_day, cfg) -> dict | None:
    """Seeded by stock and date, so refreshing the same day shows the same odds."""
    rng = np.random.default_rng(zlib.crc32(f"{play.ticker}{play.kind}{data_day}".encode()))
    days = montecarlo.trading_days(play)
    levels = (play.entry_high, play.stop, play.target, days)
    if play.kind != "pair":
        return montecarlo.simulate_play(frames[play.ticker], *levels, rng, cfg=cfg, with_chart=True)
    pair = next(p for p in found if p.a == play.ticker and p.b == play.pair_with)
    a_log, b_log = np.log(frames[pair.a]["close"]), np.log(frames[pair.b]["close"])
    other = float(frames[pair.b]["close"].iloc[-1])
    return montecarlo.simulate_pair(a_log, b_log, pair, *levels, other, rng, cfg=cfg, with_chart=True)


def _failed_run(previous: dict | None, message: str, now: datetime) -> dict:
    base = previous or {
        "run_date": None,
        "data_date": None,
        "ran_at": now.isoformat(),
        "picks": [],
        "stocks": {},
        "backtest": None,
        "skipped": [],
    }
    return base | {"warnings": [message]}


def run(store, fetcher=yahoo, now: datetime | None = None, cfg=CONFIG, stocks: pd.DataFrame | None = None) -> dict:
    now = now or datetime.now(WIB)
    stocks = universe.load() if stocks is None else stocks
    previous = store.latest_snapshot()
    names = dict(zip(stocks["ticker"], stocks["name"]))
    sectors = dict(zip(stocks["ticker"], stocks["sector"]))

    fetched = _fetch_all(list(stocks["ticker"]), fetcher)
    skipped, frames, fundamentals, failures = [], {}, {}, 0
    calendar = {ticker: dated for ticker, (_, _, dated) in fetched.items()}
    for ticker, (prices, funda, _) in fetched.items():
        prices = _usable_bars(drop_partial_bar(prices, now, cfg), store, ticker)
        if prices.empty:
            failures += 1
            skipped.append({"ticker": ticker, "reason": "No price data from Yahoo"})
            continue
        store.save_prices(ticker, prices)
        if funda:
            store.save_fundamentals(ticker, funda)
        frames[ticker] = prices
        fundamentals[ticker] = funda or store.load_fundamentals(ticker)

    if failures / len(stocks) > cfg.max_failed_share:
        message = f"Refresh failed: Yahoo returned no data for {failures} of {len(stocks)} stocks. Showing the last good result."
        return _failed_run(previous, message, now)

    data_day = max(frame.index[-1] for frame in frames.values())
    if previous and previous.get("data_date") and data_day.strftime("%Y-%m-%d") < previous["data_date"]:
        message = "Yahoo's latest data is older than the saved result, so the last good result stays on screen."
        return _failed_run(previous, message, now)
    for ticker in list(frames):
        frame = frames[ticker]
        reason = None
        if frame.index[-1] != data_day:
            reason = "No trade on the latest session"
        elif not tradable(frame, cfg):
            reason = "Too illiquid or too little price history"
        if reason:
            skipped.append({"ticker": ticker, "reason": reason})
            del frames[ticker]

    warnings = []
    if failures:
        warnings.append(f"{failures} stocks returned no data from Yahoo and were skipped.")
    no_financials = sum(1 for ticker in frames if not fundamentals.get(ticker))
    if no_financials:
        warnings.append(f"{no_financials} stocks have no financial data, so they can't be long-term picks.")
    usdidr = fetcher.fetch_usdidr()
    if usdidr is None:
        warnings.append("No USD/IDR rate today, so US dollar reporters have no PE or PBV.")

    rows = []
    for ticker, frame in frames.items():
        close = float(frame["close"].iloc[-1])
        funda = fundamentals.get(ticker)
        rows.append(
            {"ticker": ticker, "sector": sectors[ticker], "close": close}
            | factors.valuation(close, funda, usdidr, now.date(), sectors[ticker])
            | {
                "momentum": factors.momentum_12_1(frame["adj_close"]),
                "earnings_stability": factors.earnings_stability((funda or {}).get("net_income_history") or []),
            }
        )

    all_plays, found, table = [], [], pd.DataFrame(rows)
    if rows:
        table = factors.score(table)
        table["top_composite"] = table["composite"].rank(pct=True) >= 1 - cfg.factor_top_pct
        medians = _sector_medians(table)
        logs = {ticker: np.log(frame["close"]) for ticker, frame in frames.items()}
        found = pairs.find_pairs(logs, sectors, cfg)
        records = _clean(table.to_dict("records"))
        for record in records:
            ticker = record["ticker"]
            candidates = [
                plays.long_play(record, medians[record["sector"]], record["close"], cfg),
                plays.short_play(frames[ticker], ticker=ticker, cfg=cfg),
            ]
            for pair in found:
                if pair.a == ticker:
                    other = float(frames[pair.b]["close"].iloc[-1])
                    candidates.append(plays.pair_play(pair, record["close"], other, ticker, cfg))
            all_plays += [play for play in candidates if play]

    composites = dict(zip(table["ticker"], table["composite"])) if rows else {}
    ranked = plays.rank(all_plays, composites)
    records_by_ticker = {record["ticker"]: record for record in _clean(table.to_dict("records"))} if rows else {}

    odds = {id(play): _play_odds(play, frames, found, data_day, cfg) for play in all_plays}

    def play_page(play, with_chart: bool = True) -> dict:
        result = odds[id(play)]
        if result and not with_chart:
            result = {key: value for key, value in result.items() if key != "chart"}
        return asdict(play) | {"monte_carlo": result}

    upcoming = {
        ticker: events.summarise(calendar.get(ticker), now.date(), record["close"], cfg)
        for ticker, record in records_by_ticker.items()
    }
    headlines = _fetch_news(list(records_by_ticker), names, _news_source(fetcher))
    picks = [
        play_page(play, with_chart=False)
        | {
            "rank": position,
            "name": names[play.ticker],
            "close": records_by_ticker[play.ticker]["close"],
            "pe": records_by_ticker[play.ticker]["pe"],
            "pbv": records_by_ticker[play.ticker]["pbv"],
            "event": (upcoming.get(play.ticker) or {}).get("soon"),
        }
        for position, play in enumerate(ranked[: cfg.max_rows], start=1)
    ]
    overlap = concentration.check(picks, frames, sectors, cfg)

    stock_pages = {}
    for ticker, record in records_by_ticker.items():
        stock_pages[ticker] = {
            "ticker": ticker,
            "name": names[ticker],
            "sector": record["sector"],
            "close": record["close"],
            "valuation": {key: record[key] for key in factors.VALUATION_FIELDS},
            "years": factors.valuation_history(frames[ticker]["close"], fundamentals.get(ticker), usdidr),
            "sector_medians": medians[record["sector"]],
            "scores": {
                "value": record["value"],
                "quality": record["quality"],
                "momentum": record["momentum_score"],
                "size": record["size"],
                "composite": record["composite"],
            },
            "plays": [play_page(play) for play in all_plays if play.ticker == ticker],
            "pairs": _pair_rows(found, ticker),
            "events": upcoming[ticker],
            "news": news.summarise(headlines.get(ticker), ticker, names[ticker], now, cfg),
        }

    market = _market_closes(fetcher, store, now, cfg)
    regime = regimes.current_regime(market, cfg) if market is not None else None
    if regime is None:
        warnings.append("No IHSG data today, so there's no market regime reading.")
    features = _market_features(fetcher, market, frames, cfg)
    market_type = clusters.current_market_type(features, cfg) if features is not None else None
    if market_type is None:
        warnings.append("Not enough IHSG or USD/IDR data today, so there's no market type reading.")

    models = None
    short_tickers = {play.ticker for play in all_plays if play.kind == "short"}
    try:
        models, insights = learn.run(frames, market, short_tickers, cfg) if frames else (None, {})
    except Exception:
        insights = {}  # The picks don't depend on the models, so they still go out
        warnings.append("The machine learning models failed today, so stock pages have no ML odds or similar setups.")
    for ticker, page in stock_pages.items():
        page["insights"] = insights.get(ticker)

    results, tested_at = _backtests(frames, sectors, previous, now.date(), market, features, cfg)
    data_date = data_day.strftime("%Y-%m-%d")
    snapshot = _clean(
        {
            "run_date": data_date,
            "data_date": data_date,
            "ran_at": now.isoformat(),
            "picks": picks,
            "stocks": stock_pages,
            "regime": regime,
            "market_type": market_type,
            "backtest": results,
            "backtest_at": tested_at,
            "models": models,
            "concentration": overlap,
            "rotation": sector_rotation(frames, sectors, cfg) if frames else None,
            "universe_size": len(stocks),
            "skipped": skipped,
            "warnings": warnings,
        }
    )
    store.save_snapshot(data_date, snapshot)
    return snapshot


def _split_scale(pick: dict, frame: pd.DataFrame | None, picked_on: pd.Timestamp) -> float:
    """Stored prices get re-based after a split but saved picks don't, so bring the pick into line."""
    if frame is None or not pick.get("close") or picked_on not in frame.index:
        return 1.0
    return float(frame["close"].loc[picked_on]) / pick["close"]


def track_record(snapshots: list[dict], prices: dict[str, pd.DataFrame]) -> list[dict]:
    """What happened to each past pick. A stock already being tracked isn't counted again until it resolves."""
    record, open_keys = [], {}
    for snapshot in snapshots:
        picked_on = pd.Timestamp(snapshot["data_date"])
        for pick in snapshot["picks"]:
            key = (pick["ticker"], pick["kind"])
            if open_keys.get(key, picked_on) > picked_on:
                continue
            frame = prices.get(pick["ticker"])
            later = pd.DataFrame() if frame is None else frame[frame.index > picked_on]
            scale = _split_scale(pick, frame, picked_on)
            entry, stop, target = (pick[key] * scale for key in ("entry_high", "stop", "target"))
            days = pick.get("days")
            limit = picked_on + timedelta(days=days) if days else None
            outcome, exit_price, exit_date = OUTCOME_OPEN, None, None
            for held, (day, bar) in enumerate(later.iterrows(), start=1):
                exit_date = day
                if bar["low"] <= stop:
                    outcome, exit_price = "Stop hit", stop
                    break
                if bar["high"] >= target:
                    outcome, exit_price = "Target hit", target
                    break
                exit_price = float(bar["close"])
                # A pair's limit is trading days, the others are calendar days
                timed_out = held >= days if days and pick["kind"] == "pair" else limit is not None and day >= limit
                if timed_out:
                    outcome = "Time limit"
                    break
            open_keys[key] = pd.Timestamp.max if outcome == OUTCOME_OPEN else exit_date
            record.append(
                {
                    "picked_on": snapshot["data_date"],
                    "ticker": pick["ticker"],
                    "kind": pick["kind"],
                    "entry": pick["entry_high"],
                    "target": pick["target"],
                    "stop": pick["stop"],
                    "outcome": outcome,
                    "latest_close": None if later.empty else float(later["close"].iloc[-1]),
                    "return": None if exit_price is None else net_return(entry, exit_price),
                }
            )
    return record
