# IDX Quant: design

Date: 2026-11-02. Status: awaiting approval.

## Intent

A personal app that, after each IDX trading day, answers one question: which stocks does the model rate as buys right now, and what is the play for each? It combines two methods, quantitative factor investing and statistical arbitrage, into a single ranked list with a concrete playbook per stock.

The value is in turning two research methods into a decision someone can read in a few minutes, while being honest about how far free data can be trusted.

## Goals

- First page: a dense ranked table of today's buy candidates (mockup A). Columns: rank, stock, play, entry, target, stop, PE, PBV, why today.
- Clicking a row opens a detail page with the playbook, valuation, stat arb pairs and factor scores.
- Each pick is either long term, short term or pair trade.
- Each pick shows why it ranked there and how that kind of signal did in past data.
- Numbers reflect real trading: fees, 100-share lots, IDX tick sizes.
- One command starts the app, and it runs on the user's own computer.

## Non-goals

- Automatic trading or any broker connection.
- Intraday or live prices. This is an end-of-day tool.
- Shorting. Pair trades buy the cheap stock only.
- Position sizing, portfolio tracking or anything based on the user's own money.
- Multiple users, logins, hosting, mobile app, alerts.

## Anti-goals: failure even if it technically works

- Fake precision: showing a number as solid when the data behind it is missing, stale or untested.
- Forcing picks on a quiet day. If few stocks qualify, the list is short, and it can be empty.
- Backtests that look good only because they ignore costs or use information unavailable at the time.
- Stating "recommended" as certainty. Every page says this is model output, not personal advice.

## Constraints and what was checked

- **Prices:** Yahoo Finance returned current daily IDX data for `BBCA.JK` on 2026-11-02.
- **Fundamentals:** Yahoo returned only 4 annual periods (2022 to 2025) for `BBCA.JK`. Current PE and PBV are workable. A decade of factor testing is not.
- **Yahoo is unofficial** and can change or rate-limit without warning. All access goes through one module, and results are cached locally.
- **Machine:** Python 3.14 on Windows. pandas, statsmodels, yfinance and FastAPI all have compatible releases. None of them are installed yet.

## Stack

Builder's call, stated here so it can be rejected:

- Python with pandas, numpy and statsmodels for the engines.
- yfinance, or direct Yahoo calls, behind a single data module.
- SQLite for the local cache and daily snapshots.
- FastAPI serving one plain HTML and JavaScript page, with no front-end build step.
- UI language is English, and prices are in rupiah.

## Stock universe

- An editable `universe.csv` of IDX80 stocks, which includes the LQ45. Membership has no free feed, so it is compiled once and updated by hand when the index rebalances.
- Each day, drop stocks whose 20-day median traded value is under Rp 5 billion, or that have under 2 years of prices.

## Daily refresh

- Market closes around 16:15 WIB. Data counts as final from 17:00 WIB.
- Opening the app after that refreshes automatically if today's data is missing, and there is also a manual refresh button.
- The page always shows the data date. If a refresh fails, it shows the last good result with a visible warning.
- Each day's list is saved as a snapshot. Comparing old picks with what happened later becomes the app's real track record, which matters most for long-term picks that can't be properly backtested.

## Factor engine

Scores are percentiles from 0 to 100 within the universe.

- **Value:** earnings yield, book yield, dividend yield. Ranked within sector, since a bank's PBV can't be compared with a miner's.
- **Quality:** ROE, stability of annual earnings, debt to equity (skipped for banks).
- **Momentum:** 12-month return, excluding the latest month.
- **Size:** market cap. Shown for information, not part of the composite.

The composite is the equal-weighted average of value, quality and momentum.

PE and PBV are calculated from the latest annual report and today's price. Some IDX companies, mainly in coal, report in US dollars, so financials are converted using `USDIDR=X` whenever the reported currency isn't IDR.

## Stat arb engine

- Pairs are tested within the same sector only, on 2 years of daily log prices.
- Keep a pair if the Engle-Granger test passes at 5% after correcting for testing many pairs, and its half-life is between 3 and 30 days.
- The hedge ratio comes from OLS. The gap's z-score uses a 60-day window.
- Pairs are re-tested every run.
- Status shown on the detail page: Active at z of -2 or lower, Watch from -1 to -2, otherwise None.

Because only the cheap stock is bought, each trade still carries market risk. The UI says so, and the backtest reports the buy-only result, not a theoretical long/short one.

## Play rules

All entries, targets and stops are rounded to valid IDX ticks. Fee defaults are in a config file: 0.15% buy, 0.25% sell.

| | Long term | Short term | Pair trade |
|---|---|---|---|
| **Qualifies when** | Composite in top 20%, fundamentals complete and under 18 months old | Above 50-day average, new 20-day high, volume above its 20-day average | Pair is Active |
| **Entry** | Today's close, down to 2% below | Today's close, up to 1% above | Today's close, up to 1.5% above |
| **Target** | Sector median PE and PBV applied to the stock, averaged, capped at +35% | Entry + 3 × ATR(14) | Price where z returns to -0.5 |
| **Stop** | Entry - 25% (changed from 15% on 2026-11-02 after a 2017-2025 test: more winners and a flat typical trade, but larger losses) | Entry - 1.5 × ATR(14) | Price where z reaches -3.5 |
| **Time limit** | 12 months, review after each annual report | 2 weeks | 2 × half-life |

A pick is dropped if its upside after costs is under 10% for long term or under 3% for the other two.

**Ranking:** sort by reward to risk after costs, with ties broken by composite score. A stock appears once, under its best play, and any other plays are shown on its detail page. The table shows at most 15 rows, with a filter by play type.

## Backtest and track record

- Short-term and pair rules are tested walk-forward on up to 10 years of prices: decisions use only earlier data, trades enter at the next day's open, and fees are included.
- Results shown per play type: number of trades, win rate, average return after costs, worst drawdown.
- Momentum can be tested the same way. Value and quality cannot, because free data lacks the history, so long-term picks are labelled "not backtested".
- The universe is today's index members, which flatters past results (survivorship bias). The results page says so.

## Pages

1. **Today:** ranked table, play filter, data date, disclaimer.
2. **Stock detail:** as in the mockup, plus the past performance of that play type and the data date of its financials.
3. **Results:** backtest figures, and the snapshot track record as it builds up.

Missing values show as a dash, never zero. A stock with missing fundamentals can't be a long-term pick, but it can still be a short-term or pair trade.

## What done looks like

- One command starts the app and it opens in the browser.
- Live Yahoo data produces today's ranked list, or an honest short or empty one.
- Clicking any row shows its complete detail page.
- Automated tests cover the calculations using fixed sample data, including tick rounding, USD conversion, walk-forward with no look-ahead, and a known cointegrated pair.
- A failed refresh shows the warning instead of crashing or showing blank data.

## Left to the builder

Code structure, table styling, chart choices, and retry and rate-limit handling.

## Calls made by the designer, for the user to check

- Stock universe: IDX80, and the Rp 5 billion liquidity floor.
- All thresholds in Play rules. These are reasonable starting points, not tuned results, and they live in config so they can change.
- Size shown but excluded from the composite score.
- Ranking by reward to risk across all play types.
- Added beyond the request: the daily snapshot track record and the Results page.
