# IDX Quant Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A local app that ranks IDX buy candidates after each trading day, with a playbook, valuation, pairs and factor scores per stock.

**Architecture:** Pure calculation modules (`trading`, `factors`, `pairs`, `plays`, `backtest`) take pandas data and never touch the network. `yahoo` is the only module that does. `pipeline` joins them and writes a JSON snapshot to SQLite, and FastAPI serves that snapshot to one static page.

**Tech Stack:** Python 3.14, pandas, numpy, statsmodels, yfinance, FastAPI, uvicorn, SQLite (stdlib), pytest, plain HTML/CSS/JS.

**Spec:** `docs/superpowers/specs/2026-11-02-idx-quant-app-design.md`

## Global Constraints

- Every threshold in the spec's Play rules lives in `idxquant/config.py`, never inline.
- Fees: 0.15% buy, 0.25% sell. Lot: 100 shares.
- IDX ticks: Rp 1 under 200; 2 from 200 to under 500; 5 from 500 to under 2,000; 10 from 2,000 to under 5,000; 25 from 5,000.
- Missing values show as a dash, never zero. In JSON they are `null`.
- No shorting, and no broker connection.
- Every page says the output is model output, not personal advice.
- Only `idxquant/yahoo.py` may call the network.
- The folder is not a git repository, so tasks have no commit step unless the user asks for one.

## Review Focus

- A ticker that Yahoo returns empty or partially: skip that stock and record it, the run still finishes. Test in Task 2 and Task 7.
- Zero or negative earnings or book value: PE or PBV is `null`, the stock gets no long-term play. Test in Task 3.
- Opening on a weekend, a holiday or before 17:00 WIB: the latest complete session is used, no false stale warning, and a partial bar for today is ignored. Test in Task 7.
- Suspended stocks with flat prices or zero volume: excluded by liquidity, and they never produce a pair. Test in Task 4.
- Entry, target or stop landing near a tick band boundary, or a stop below Rp 50: prices stay on valid ticks, and a stop under Rp 50 drops the pick. Test in Task 1 and Task 5.

---

### Task 1: Project setup, config and trading rules

**Files:**
- Create: `requirements.txt`, `idxquant/__init__.py`, `idxquant/config.py`, `idxquant/trading.py`, `tests/test_trading.py`

**Interfaces:**
- Produces: `Config` (frozen dataclass with fields below) and `CONFIG` instance; `tick_size(price: float) -> int`; `round_tick(price: float, direction: str = "nearest") -> int` where direction is `"up"`, `"down"` or `"nearest"`; `net_return(entry: float, exit: float, cfg=CONFIG) -> float`.

`Config` fields: `buy_fee=0.0015, sell_fee=0.0025, lot=100, min_value_idr=5e9, min_history_days=504, factor_top_pct=0.20, max_fundamental_age_days=548, pair_pvalue=0.05, pair_hl_min=3, pair_hl_max=30, pair_lookback=504, z_window=60, z_active=-2.0, z_watch=-1.0, z_exit=-0.5, z_stop=-3.5, long_entry_band=0.02, long_target_cap=0.35, long_stop=0.15, long_days=365, short_entry_band=0.01, short_target_atr=3.0, short_stop_atr=1.5, short_days=14, pair_entry_band=0.015, pair_time_mult=2, min_up_long=0.10, min_up_other=0.03, min_stop_price=50, max_rows=15, final_hour_wib=17`.

- [ ] **Step 1: Create a virtual environment and install requirements**

Run: `python -m venv .venv` then `.venv/Scripts/pip install -r requirements.txt`
Expected: installs without errors.

- [ ] **Step 2: Write failing tests**

```python
def test_tick_bands():
    assert [tick_size(p) for p in (199, 200, 499, 500, 1999, 2000, 4990, 5000)] == [1, 2, 2, 5, 5, 10, 10, 25]

def test_round_tick_directions():
    assert round_tick(2483, "up") == 2490
    assert round_tick(2483, "down") == 2480
    assert round_tick(201, "up") == 202

def test_round_tick_crossing_band_stays_valid():
    assert round_tick(499.5, "up") % tick_size(round_tick(499.5, "up")) == 0

def test_net_return_includes_both_fees():
    assert net_return(1000, 1100) == pytest.approx((1100 * 0.9975) / (1000 * 1.0015) - 1)
```

- [ ] **Step 3: Run to confirm failure, implement `trading.py` and `config.py`, run to confirm pass**

Run: `.venv/Scripts/pytest tests/test_trading.py -v`
Expected: all PASS.

### Task 2: Yahoo access, local store and stock universe

**Files:**
- Create: `idxquant/yahoo.py`, `idxquant/store.py`, `idxquant/universe.csv`, `idxquant/universe.py`, `tests/test_store.py`, `tests/test_yahoo.py`

**Interfaces:**
- Consumes: `CONFIG`.
- Produces:
  - `universe.load() -> pd.DataFrame` with columns `ticker, name, sector`. Tickers have no `.JK` suffix.
  - `yahoo.fetch_prices(ticker: str, years: int = 10) -> pd.DataFrame` indexed by date, columns `open, high, low, close, adj_close, volume`. Empty frame on failure.
  - `yahoo.fetch_fundamentals(ticker: str) -> dict | None` keys `as_of, currency, eps, equity, net_income_history (list), total_debt, shares, dividends_ttm`.
  - `yahoo.fetch_usdidr() -> float | None`.
  - `store.Store(path)` with `save_prices`, `load_prices(ticker)`, `save_fundamentals`, `load_fundamentals(ticker)`, `save_snapshot(run_date: str, payload: dict)`, `latest_snapshot() -> dict | None`, `all_snapshots() -> list[dict]`.

`close` is split-adjusted and is used for all displayed prices. `adj_close` also includes dividends and is used only for returns.

Compile `universe.csv` from the current IDX80 list, found by web search. Record the source and date in a comment line. If no reliable current list can be found, stop and tell the user.

- [ ] **Step 1: Write failing tests**

`test_store.py`: prices and snapshots round-trip through a `tmp_path` database; saving the same date twice keeps one row; `latest_snapshot` returns the newest `run_date`.

`test_yahoo.py`, with yfinance monkeypatched:

```python
def test_fetch_prices_returns_empty_when_yahoo_fails(monkeypatch):
    monkeypatch.setattr(yahoo, "_download", raise_error)
    assert yahoo.fetch_prices("XXXX").empty

def test_fetch_prices_adds_jk_suffix(monkeypatch):
    # capture the symbol passed to _download
    assert captured == "BBCA.JK"
```

- [ ] **Step 2: Run to confirm failure, implement, run to confirm pass**

Run: `.venv/Scripts/pytest tests/test_store.py tests/test_yahoo.py -v`
Expected: all PASS.

- [ ] **Step 3: Check against live Yahoo**

Run: `.venv/Scripts/python -c "from idxquant import yahoo; print(yahoo.fetch_prices('BBCA').tail(2)); print(yahoo.fetch_fundamentals('BBCA'))"`
Expected: recent rows, and EPS for 2025 of 467.

### Task 3: Factor engine

**Files:**
- Create: `idxquant/factors.py`, `tests/test_factors.py`

**Interfaces:**
- Consumes: `CONFIG`, `store` data shapes.
- Produces:
  - `valuation(close: float, f: dict | None, usdidr: float | None) -> dict` keys `pe, pbv, roe, dividend_yield, market_cap, debt_to_equity, stale`.
  - `score(rows: pd.DataFrame) -> pd.DataFrame` where `rows` has `ticker, sector` and the valuation fields plus `momentum, earnings_stability`. Adds `value, quality, momentum_score, size, composite`, each 0 to 100.
  - `momentum_12_1(adj_close: pd.Series) -> float | None`.

Banks skip debt to equity in quality. Value ranks within sector. Composite is the mean of value, quality and momentum_score, and is `null` if any is missing. `stale` is true when financials are older than `max_fundamental_age_days`.

- [ ] **Step 1: Write failing tests**

```python
def test_pe_pbv_basic():
    v = valuation(5000, {"eps": 500, "equity": 2e12, "shares": 1e9, "currency": "IDR", ...}, None)
    assert v["pe"] == 10
    assert v["pbv"] == 2.5

def test_negative_earnings_gives_no_pe():
    assert valuation(5000, make_f(eps=-10), None)["pe"] is None

def test_negative_equity_gives_no_pbv():
    assert valuation(5000, make_f(equity=-1), None)["pbv"] is None

def test_usd_reporter_is_converted():
    v = valuation(2500, make_f(eps=0.05, currency="USD", ...), 16000)
    assert v["pe"] == pytest.approx(2500 / (0.05 * 16000))

def test_usd_reporter_without_rate_is_missing():
    assert valuation(2500, make_f(eps=0.05, currency="USD"), None)["pe"] is None

def test_missing_fundamentals_all_null():
    assert valuation(5000, None, None)["pe"] is None

def test_value_ranks_within_sector():
    # cheapest bank scores above an equally priced stock in a cheaper sector
    ...

def test_size_not_in_composite():
    # changing market_cap leaves composite unchanged
    ...

def test_momentum_skips_latest_month():
    # a spike in the last 21 days does not change the result
    ...
```

- [ ] **Step 2: Run to confirm failure, implement, run to confirm pass**

Run: `.venv/Scripts/pytest tests/test_factors.py -v`
Expected: all PASS.

### Task 4: Stat arb engine

**Files:**
- Create: `idxquant/pairs.py`, `tests/test_pairs.py`

**Interfaces:**
- Consumes: `CONFIG`.
- Produces:
  - `analyse_pair(a: pd.Series, b: pd.Series) -> Pair | None` on log prices. `Pair` is a dataclass: `a, b, beta, alpha, pvalue, half_life, z, spread_mean, spread_std`.
  - `find_pairs(prices: dict[str, pd.Series], sectors: dict[str, str], cfg=CONFIG) -> list[Pair]`, tested within sector with Benjamini-Hochberg correction across all tests, then half-life filtered.
  - `status(z: float) -> str`, one of `"Active"`, `"Watch"`, `"None"`.
  - `price_at_z(pair: Pair, z: float, other_price: float) -> float`, the price of the cheap stock at which its gap equals `z` given the other stock's price.

Series are aligned on shared dates. Each pair is stored once, and `z` is signed so the cheap stock is the one bought. A flat series is skipped.

- [ ] **Step 1: Write failing tests**

Use seeded numpy data.

```python
def test_finds_known_cointegrated_pair():
    # b = random walk, a = b + AR(1) noise with half-life near 8
    assert len(find_pairs(...)) == 1

def test_rejects_independent_random_walks():
    assert find_pairs(two_walks, ...) == []

def test_only_tests_same_sector():
    assert find_pairs(cointegrated_in_two_sectors, ...) == []

def test_flat_series_never_pairs():
    assert find_pairs({"A": walk, "B": flat}, ...) == []

def test_status_bands():
    assert [status(z) for z in (-2.5, -2.0, -1.5, -1.0, -0.5, 1.0)] == ["Active", "Active", "Watch", "Watch", "None", "None"]

def test_price_at_z_round_trip():
    # price_at_z at the current z returns the current price
    ...
```

- [ ] **Step 2: Run to confirm failure, implement, run to confirm pass**

Run: `.venv/Scripts/pytest tests/test_pairs.py -v`
Expected: all PASS.

### Task 5: Play rules and ranking

**Files:**
- Create: `idxquant/plays.py`, `tests/test_plays.py`

**Interfaces:**
- Consumes: `round_tick`, `net_return`, `CONFIG`, `Pair`, `price_at_z`, `status`, `score` output.
- Produces:
  - `Play` dataclass: `ticker, kind ("long"|"short"|"pair"), entry_low, entry_high, target, stop, days, reason, upside, downside, reward_risk, pair_with`.
  - `long_play(row: dict, sector_medians: dict, close: float) -> Play | None`.
  - `short_play(ohlcv: pd.DataFrame) -> Play | None` with ticker passed by keyword.
  - `pair_play(pair: Pair, close: float, other_close: float, ticker: str) -> Play | None`.
  - `atr(ohlcv: pd.DataFrame, n: int = 14) -> float`.
  - `rank(plays: list[Play], composites: dict[str, float]) -> list[Play]`.

Long target is the average of sector median PE × EPS and sector median PBV × book value per share, capped at +35%. Rounding: entry low, stop and target round down, and entry high rounds up, so rounding never flatters a trade. Upside and downside are measured from the entry zone's upper price after costs. Pick is dropped below `min_up_long` or `min_up_other`, or if the stop is under `min_stop_price`.

`rank` sorts by `reward_risk` descending, ties by composite, keeps each stock's best play, returns all kept. The caller trims to `max_rows`, and other plays stay available for the detail page.

- [ ] **Step 1: Write failing tests**

```python
def test_long_play_target_cap():
    # sector medians imply +60%: target == round_tick(close * 1.35, "down")

def test_long_play_needs_top_composite_and_fresh_data():
    assert long_play(row(stale=True), ...) is None
    assert long_play(row(pe=None), ...) is None

def test_long_play_dropped_under_10_percent_upside(): ...

def test_short_play_requires_breakout_trend_and_volume():
    # each condition removed in turn gives None

def test_short_play_targets_use_atr():
    # target == entry + 3 ATR, stop == entry - 1.5 ATR, rounded to ticks

def test_pair_play_only_when_active():
    assert pair_play(pair(z=-1.5), ...) is None

def test_pair_play_time_limit_two_half_lives():
    assert pair_play(pair(z=-2.2, half_life=9), ...).days == 18

def test_stop_under_50_drops_pick(): ...

def test_prices_land_on_valid_ticks_near_band():
    # close 505 with target and stop across the 500 band
    assert all(p % tick_size(p) == 0 for p in (play.entry_low, play.entry_high, play.target, play.stop))

def test_rank_orders_by_reward_risk_and_keeps_best_per_stock(): ...

def test_rank_breaks_ties_by_composite(): ...
```

- [ ] **Step 2: Run to confirm failure, implement, run to confirm pass**

Run: `.venv/Scripts/pytest tests/test_plays.py -v`
Expected: all PASS.

### Task 6: Backtest

**Files:**
- Create: `idxquant/backtest.py`, `tests/test_backtest.py`

**Interfaces:**
- Consumes: `net_return`, `analyse_pair`, `find_pairs`, `short_play`, `momentum_12_1`, `CONFIG`.
- Produces:
  - `summarise(trades: list[float]) -> dict` keys `trades, win_rate, avg_return, max_drawdown`. All `null` when empty.
  - `simulate(ohlc: pd.DataFrame, signal_day: int, stop: float, target: float, days: int) -> float | None`: enters at the next day's open, exits at stop, target or time limit. If both stop and target are hit in one day, assume the stop.
  - `backtest_short(prices: dict[str, pd.DataFrame]) -> dict`.
  - `backtest_pairs(prices: dict[str, pd.DataFrame], sectors: dict[str, str]) -> dict`, re-forming pairs every 63 trading days using only earlier data, buying the cheap stock only.
  - `backtest_momentum(prices: dict[str, pd.DataFrame]) -> dict`, monthly top-20% hold.

- [ ] **Step 1: Write failing tests**

```python
def test_enters_at_next_open_and_charges_fees():
    # hand-built OHLC, exit at target
    assert simulate(...) == pytest.approx(net_return(next_open, target))

def test_stop_wins_when_both_hit_same_day(): ...

def test_time_limit_exits_at_close(): ...

def test_no_lookahead_in_short_backtest():
    # altering prices after day N does not change signals up to day N

def test_no_lookahead_in_pair_backtest():
    # altering prices after a formation date does not change that formation's pairs

def test_empty_results_are_null():
    assert summarise([])["win_rate"] is None
```

- [ ] **Step 2: Run to confirm failure, implement, run to confirm pass**

Run: `.venv/Scripts/pytest tests/test_backtest.py -v`
Expected: all PASS.

### Task 7: Daily pipeline

**Files:**
- Create: `idxquant/pipeline.py`, `tests/test_pipeline.py`

**Interfaces:**
- Consumes: everything above.
- Produces:
  - `latest_final_date(now: datetime, last_bar: date) -> date`: the last bar, minus today's bar when `now` is before 17:00 WIB.
  - `needs_refresh(now: datetime, snapshot: dict | None) -> bool`: true only after 17:00 WIB on a weekday without a snapshot for today. Holidays are handled by comparing the bar date after fetching, so they cause one harmless fetch at most.
  - `run(store: Store, fetcher=yahoo, now: datetime | None = None) -> dict`, returns and saves the snapshot.
  - `tradable(prices: pd.DataFrame) -> bool`, liquidity and history filter.

Snapshot shape: `{run_date, data_date, picks: [...], stocks: {ticker: {name, sector, close, valuation, scores, plays, pairs}}, backtest: {short, pair, momentum}, skipped: [{ticker, reason}], warnings: []}`.

The backtest takes minutes, so it reruns only when absent or over 30 days old.

- [ ] **Step 1: Write failing tests**

Use a fake fetcher with seeded data.

```python
def test_run_survives_ticker_failures():
    # fetcher returns empty for one ticker: it appears in skipped, the run finishes

def test_all_fetches_failing_keeps_last_snapshot():
    # run adds a warning, and the earlier snapshot stays latest

def test_today_bar_dropped_before_17_wib(): ...

def test_weekend_does_not_need_refresh(): ...

def test_after_17_on_weekday_without_snapshot_needs_refresh(): ...

def test_quiet_day_gives_empty_picks():
    assert run(...)["picks"] == []

def test_picks_capped_at_15(): ...

def test_illiquid_and_short_history_filtered(): ...

def test_snapshot_is_json_serialisable_with_nulls():
    json.dumps(snapshot, allow_nan=False)
```

- [ ] **Step 2: Run to confirm failure, implement, run to confirm pass**

Run: `.venv/Scripts/pytest tests/test_pipeline.py -v`
Expected: all PASS.

### Task 8: Web app and pages

**Files:**
- Create: `idxquant/api.py`, `idxquant/static/index.html`, `idxquant/static/app.js`, `idxquant/static/style.css`, `run.py`, `run.bat`, `tests/test_api.py`

**Interfaces:**
- Consumes: `Store`, `pipeline.run`, `pipeline.needs_refresh`.
- Produces: `GET /api/today`, `GET /api/stock/{ticker}`, `GET /api/results`, `POST /api/refresh`, `GET /api/refresh/status`. Refresh runs in a background thread, and a second refresh while one runs is ignored.

Pages use hash routes `#/`, `#/stock/ADRO`, `#/results`, matching the approved mockups: table columns rank, stock, play, entry, target, stop, PE, PBV, why today. The detail page adds that play type's past performance and the financials' date. Long-term picks show "not backtested". Results shows the survivorship bias note and compares saved past picks with later prices. Footer on every page: "Model output, not personal advice."

Warnings appear as a banner, with the data date always visible. `null` renders as a dash. Works in light and dark.

- [ ] **Step 1: Write failing tests**

```python
def test_today_without_snapshot_says_so():
    assert client.get("/api/today").json()["picks"] == []

def test_unknown_ticker_404(): ...

def test_second_refresh_ignored_while_running(): ...

def test_failed_refresh_keeps_last_data_and_warns(): ...
```

- [ ] **Step 2: Run to confirm failure, implement, run to confirm pass**

Run: `.venv/Scripts/pytest tests/test_api.py -v`
Expected: all PASS.

- [ ] **Step 3: End-to-end check with live data**

Run: `.venv/Scripts/python run.py`, open the app, refresh, click a row of each play type, open Results, and check the browser console.
Expected: ranked list or an honest empty one, complete detail pages, no console errors, and PE for BBCA close to 10.7 (4,980 / 467).

- [ ] **Step 4: Run all tests**

Run: `.venv/Scripts/pytest -v`
Expected: all PASS.
