# IDX Quant

A personal app that ranks about 137 liquid Indonesian stocks (the IDX80 plus other actively traded names) after each trading day, using factor scores, statistical arbitrage, Monte Carlo simulation, market regime detection and machine learning. Each pick comes with a playbook.

This is model output, not personal financial advice. It doesn't know your money or risk limits, and it can be wrong. The app has no login, so anyone with its link can open it. Don't publish the link: sharing recommendations publicly or with paying users may fall under Indonesian investment advice rules.

## Run it on your computer

On Windows, double-click `run.bat`. It sets everything up on the first run and opens http://127.0.0.1:8765.

## Run the tests

```bash
python -m venv .venv
.venv/Scripts/pip install -r requirements-dev.txt
.venv/Scripts/python -m pytest
```

## How it works

Every number below is the current default from `idxquant/config.py`. These are starting points, not tuned results. The app's **How it works** page and **?** icons explain each figure in more detail.

### The daily flow

Each refresh runs this once, and the result is saved as that day's snapshot. Monte Carlo, the market regime and market types add information for you to read, but none of them changes which stocks are picked or how they rank.

```mermaid
flowchart TD
    A["Yahoo Finance: prices, annual reports, USD/IDR, IHSG"] --> B["Stock list filter"]
    B --> C["Valuation"]
    C --> D["Factor scores"]
    B --> E["Statistical arbitrage"]
    B --> F["Breakout check"]
    D --> G["Long-term plays"]
    E --> H["Pair plays"]
    F --> I["Short-term plays"]
    G --> J["Filters on every play"]
    H --> J
    I --> J
    J --> K["Rank by reward to risk"]
    K --> L["Today's table: up to 15 stocks"]
    J --> M["Monte Carlo odds for each play"]
    M --> N["Stock page"]
    A --> O["Market regime from IHSG"]
    O --> P["Today's market lines"]
    A --> Q["Market type from five measures"]
    Q --> P
```

### Stock list

```mermaid
flowchart TD
    A["Stock list in universe.csv"] --> B{"Did Yahoo return prices?"}
    B -- No --> X["Skipped, with the reason recorded"]
    B -- Yes --> C{"Traded on the latest session?"}
    C -- No --> X
    C -- Yes --> D{"At least 504 days of prices?"}
    D -- No --> X
    D -- Yes --> E{"Any zero-volume day in the last 10?"}
    E -- Yes --> X
    E -- No --> F{"Median daily value over 20 days at least Rp 5 billion?"}
    F -- No --> X
    F -- Yes --> G["Scored by the app"]
```

If more than 30% of stocks return no data, the refresh counts as failed and the last good result stays on screen.

### Valuation

Figures use today's close and the latest annual report. US dollar reporters are converted at the latest USD/IDR rate.

| Figure | How it's calculated |
|---|---|
| PE | Close / earnings per share. Blank if earnings are zero or negative. |
| PBV | Close / (equity / shares). Blank if equity is negative. |
| P/S | Market cap / revenue |
| EV/EBITDA | (Market cap + debt - cash) / EBITDA |
| Earnings yield | Earnings per share / close |
| Free cash flow yield | Free cash flow / market cap |
| Dividend yield | Rupiah dividends per share over the last 365 days / close |
| Graham value | Square root of (22.5 x EPS x book value per share) |
| Margins | Gross profit, operating income and net income, each / revenue |
| ROE and ROA | Net income / equity, and net income / total assets |
| Growth | Latest year / previous year - 1, and EPS growth per year over the available reports |
| Debt to equity | Total debt / equity |
| Net debt to EBITDA | (Debt - cash) / EBITDA |
| Current ratio | Current assets / current liabilities |
| Interest cover | Operating income / interest expense |
| Payout ratio | Dividends per share / earnings per share |

EV/EBITDA, free cash flow yield, net debt to EBITDA, current ratio and interest cover don't apply to banks and finance companies, so they show a dash. Sector medians need at least 3 stocks with a usable value.

### Factor scores

Each score is a percentile from 0 to 100, so 85 means the stock beats about 85% of the list.

```mermaid
flowchart TD
    A["Valuation and price history"] --> B["Value"]
    A --> C["Quality"]
    A --> D["Momentum"]
    A --> E["Size"]
    B --> B1["Rank earnings yield, book yield and dividend yield inside the sector, then average"]
    C --> C1["Rank ROE, earnings stability and low debt across the list, then average"]
    D --> D1["Rank the return from 252 to 21 trading days ago across the list"]
    E --> E1["Rank market cap across the list"]
    B1 --> F["Combined score = average of value, quality and momentum"]
    C1 --> F
    D1 --> F
    E1 --> G["Shown only, not in the combined score"]
    F --> H{"Top 20% of the list?"}
    H -- Yes --> I["Long-term candidate"]
    H -- No --> J["No long-term play"]
```

- **Value:** a sector with fewer than 3 scored stocks ranks against the whole list. Missing parts are skipped.
- **Quality:** earnings stability is average net income / its standard deviation, and needs at least 3 years. Banks skip the debt part.
- **Momentum:** the latest month is left out because very recent moves often reverse. Dividends are included.
- **Combined score:** it's blank if value, quality or momentum is missing.

### Statistical arbitrage

```mermaid
flowchart TD
    A["Two stocks in the same sector"] --> B["504 days of log prices"]
    B --> C["Fit log(A) = alpha + beta x log(B)"]
    C --> D{"Beta above 0?"}
    D -- No --> X["No pair"]
    D -- Yes --> E["Engle-Granger cointegration test"]
    E --> F{"Passes 5% after Benjamini-Hochberg correction?"}
    F -- No --> X
    F -- Yes --> G{"Half-life between 3 and 30 days?"}
    G -- No --> X
    G -- Yes --> H["Gap = today's spread vs its 60-day average, in standard deviations"]
    H --> I{"How wide is the gap?"}
    I -- "-1 or higher" --> J["None"]
    I -- "-1 to -2" --> K["Watch"]
    I -- "-2 to -3.5" --> L["Active: pair play"]
    I -- "-3.5 or lower" --> M["Broken: stay out"]
```

Half-life comes from regressing the daily change in the spread on the previous day's spread: half-life = ln(2) / -slope. Pairs are re-tested at every refresh.

A true pair trade also shorts the expensive stock, but shorting on IDX is restricted. The app only buys the cheap stock, so these trades still carry market risk.

### Plays and ranking

| | Long term | Short term | Pair trade |
|---|---|---|---|
| **Qualifies when** | Combined score in the top 20%, with financials under 18 months old | Close above its 50-day average and the previous 20 days' highest high, on volume above their average | Gap is Active |
| **Entry** | From 2% below the close up to the close | From the close up to 1% above | From the close up to 1.5% above |
| **Target** | Average of sector PE x EPS and sector PBV x book value, capped at +35% | Close + 3 x ATR(14) | Price where the gap reaches -0.5 |
| **Stop** | 25% below the top of the entry zone | Close - 1.5 x ATR(14) | Price where the gap reaches -3.5 |
| **Time limit** | 12 months | 2 weeks | 2 x half-life, in trading days |

```mermaid
flowchart TD
    A["Candidate play"] --> B["Round prices to valid IDX ticks"]
    B --> C["Measure upside and downside after fees, from the top of the entry zone"]
    C --> D{"Stop at least Rp 50?"}
    D -- No --> X["Dropped"]
    D -- Yes --> E{"Upside at least 10% long term, or 3% otherwise?"}
    E -- No --> X
    E -- Yes --> F["Reward to risk = upside / downside"]
    F --> G["Sort highest first, ties by combined score"]
    G --> H["Keep each stock's best play"]
    H --> I["Show up to 15 stocks"]
```

Fees are 0.15% to buy and 0.25% to sell. A quiet day can give a short list or none at all.

### Monte Carlo

Every play is simulated 10,000 times, so you can see how it might end. This runs after the picks are chosen and doesn't change them.

```mermaid
flowchart TD
    A["The play's entry, target, stop and time limit"] --> B{"Pair trade?"}
    B -- No --> C["Take the stock's last 756 days of daily moves"]
    C --> D["Remove the average daily move"]
    D --> E["Join random 5-day blocks into a path"]
    B -- Yes --> F["Simulate the partner stock from its past moves"]
    F --> G["Let the gap drift back using the half-life, with past shocks"]
    G --> E2["Stock price = fair price from the partner + gap"]
    E --> H["Start at the top of the entry zone and walk day by day"]
    E2 --> H
    H --> I{"First level touched?"}
    I -- Stop --> J["Hits stop"]
    I -- Target --> K["Hits target"]
    I -- "Both on one day" --> J
    I -- Neither --> L["Neither in time: exit at the last close"]
    J --> M["Repeat 10,000 times"]
    K --> M
    L --> M
    M --> N["Odds, average outcome after fees, and the 10th to 90th percentile range"]
```

- **Why the average move is removed:** a past trend isn't evidence of a future one, so the odds reflect how much a stock moves, not whether the signal is any good.
- **Time limits:** 260 trading days for long term, 10 for short term, and 2 x half-life for pairs.
- **Repeatable odds:** each simulation is seeded by stock, play and date, so refreshing the same day gives the same odds.
- **Accuracy check:** the Results page compares past predictions, made using only earlier data, with what really happened. Pair odds aren't checked, because there are too few past trades.

### Market regime

```mermaid
flowchart TD
    A["Daily IHSG returns"] --> B["Two-state hidden Markov model"]
    B --> C["Calm state: lower volatility"]
    B --> D["Stressed state: higher volatility"]
    C --> E["Update the chance of each state with each new day"]
    D --> E
    E --> F{"Stress probability above 50%?"}
    F -- Yes --> G["Market: Stressed"]
    F -- No --> H["Market: Calm"]
```

The model needs 504 days of data to start and is refitted every 63 trading days. Each day's reading uses only data up to that day, so it reacts after a move starts and doesn't predict turns. The regime is for information only and doesn't change the picks.

### Market types

The regime only looks at the index. Market types look at several measures at once, using a Gaussian mixture model that groups similar weeks.

```mermaid
flowchart TD
    A["Every week, measure five things"] --> B["IHSG return over 21 days"]
    A --> C["IHSG volatility over 21 days"]
    A --> D["Share of stocks above their 50-day average"]
    A --> E["USD/IDR change over 21 days"]
    A --> F["Average correlation between stocks"]
    B --> G["Scale using earlier weeks only"]
    C --> G
    D --> G
    E --> G
    F --> G
    G --> H["Gaussian mixture model: 4 groups"]
    H --> I{"Group volatility far above normal?"}
    I -- "Yes, and falling" --> J["Panic"]
    I -- "Yes, and rising" --> K["Rebound"]
    I -- No --> L{"Strongly rising?"}
    L -- Yes --> M["Rally"]
    L -- No --> N{"Falling, or few stocks above average?"}
    N -- Yes --> O["Weakening"]
    N -- No --> P["Quiet"]
```

- **Why 4 groups:** more groups fit better, but 5 or more split off groups covering only 2 to 4% of weeks, too few to learn from.
- **Named from their averages:** a group's name comes from what it looks like, not its number, so a type keeps its meaning after each refit.
- **No look-ahead:** the model needs 104 weeks to start and is refitted every 13 weeks. Each week is judged by a model fitted on earlier weeks only.
- **Thin results are hidden:** the Results page hides any signal and market type with fewer than 30 trades.

Market types are for information only and don't change the picks.

### Machine learning

Two models give more information on each stock page before you buy. They're shown beside the picks and don't change them.

```mermaid
flowchart TD
    A["Every stock, once a month, for about 10 years"] --> B["Measure 9 things from prices and the IHSG"]
    B --> C["Long term: did +35% come before -25% within 12 months?"]
    B --> D["Short term: did each past breakout reach its target first?"]
    B --> E["What did the price do 3 and 12 months later?"]
    C --> F["Gradient-boosted trees: ML odds"]
    D --> F
    E --> G["k-nearest neighbours: similar past setups"]
    F --> H["Walk-forward test on years the model never saw"]
    G --> H
    H --> I["Stock page shows each result with its test grade"]
```

- **ML odds:** a gradient-boosted classifier (scikit-learn's `HistGradientBoostingClassifier`, shallow and heavily smoothed) estimates how often a trade like today's reached its target before its stop. The page shows it next to the usual rate, with the four measures that moved it most.
- **Similar past setups:** k-nearest neighbours finds the 30 past moments, across all stocks, that looked most like the stock today, and shows what happened 3 and 12 months later against all past setups. It matches on the stock's own measures only: with the IHSG measures in, every match came from the same few weeks as today. The stock's own last 12 months are left out, so it can't just match itself.
- **Measures:** 1- and 3-month return, 12-month momentum, volatility, distance from the 1-year high and 200-day average, trading activity, and the IHSG's 3-month return and volatility. Free data has no history of company financials, so the models can't see value or quality.
- **Walk-forward test:** each year is predicted by a model trained only on setups whose result was known before 1 January. An odds model counts as having an edge when its AUC is at least 0.55 and it beat the past hit rate. Similar setups count when their rank IC is at least 0.02. A model without an edge is still shown, labelled "no tested edge".
- **First results, November 2026:** long-term odds had an AUC of 0.61, mostly from market volatility. Its most hopeful fifth of setups worked 51% of the time, against 33% for the least hopeful fifth. Short-term odds showed no edge (AUC 0.53). Similar setups didn't sort stocks within a month (rank IC about 0.00, below the 0.02 bar), so they're shown as history, not a forecast.

The models retrain on every daily run, which adds about 15 seconds.

### Before you buy

Two checks that don't change the picks but can change how you buy them.

- **Overlap between picks:** the Today page measures how closely the picks' daily returns have moved together over the last 126 trading days, and shows it as a correlation heatmap ordered so stocks that move together sit side by side. It warns when 3 or more picks (and at least 40% of them) share a sector, when 3 or more picks are linked by correlations of 0.6 or more, or when the picks add up to half as many independent bets or fewer. Independent bets is the participation ratio of the correlation matrix: n² divided by the sum of every correlation squared.
- **Earnings and dividends:** each stock page shows the next earnings report, the last dividend, the dividend yield over 12 months, the usual dividend month and any recent split, all from Yahoo. Report dates are converted to Jakarta time. When Yahoo has no announced date, the next report is estimated from the same report a year earlier and labelled as an estimate. A pick with a report due within 14 days is flagged on the Today page.

### Backtest

Short-term, pair and momentum signals are tested on up to 10 years of prices. Decisions use only earlier data, trades enter at the next day's open, and fees are included. Backtests re-run every 30 days.

Value and quality can't be tested, because free data has only about 4 years of annual reports. The tests also use today's index members, so companies that collapsed are missing, which flatters the results.

## Settings

| Variable | Default | Purpose |
|---|---|---|
| `HOST` | `127.0.0.1` | Address to serve on. The Dockerfile sets `0.0.0.0`. |
| `PORT` | `8765` | Port to serve on. Most hosts set this for you. |
| `DATA_PATH` | `data/idxquant.sqlite` | Database location. The Dockerfile sets `/data/idxquant.sqlite`. |

On any address other than this computer, the app runs in server mode. It refreshes by itself, checking every 10 minutes and fetching new data after 17:00 WIB on weekdays, and the Refresh button runs at most once every 10 minutes.

## Deploy

The app needs one always-on instance and persistent storage. Don't run more than one copy, because they'd share one SQLite database. Plans that sleep when idle or wipe files between restarts won't work.

1. Put the project in a private GitHub repository.
2. Create a service from that repository on a host that builds Dockerfiles. Start with about 1 GB of memory.
3. Attach a persistent volume mounted at `/data`.
4. Set the health check path to `/health`.
5. Run this in the host's shell to confirm Yahoo isn't blocking the server:

   ```bash
   python -m idxquant.check
   ```

6. Open the site and wait for the first fetch to finish. It takes a few minutes.

If the check fails, Yahoo is probably blocking the host's addresses. Try another host or region, or use a paid data source by replacing `idxquant/yahoo.py`, which is the only module that fetches data.

## Run it on GitHub Actions and Vercel

Instead of a server that's always on, GitHub Actions can refresh the data once a day and Vercel can host the pages as a static website.

```mermaid
flowchart LR
    A["GitHub Actions, weekdays 18:00 WIB"] --> B["Restore the database from the data branch"]
    B --> C["Refresh and export the pages as JSON"]
    C --> D["Save the database to the data branch"]
    C --> E["Push the website to the site branch"]
    E --> F["Vercel publishes it"]
```

- **`data` branch:** holds only the database. Each run replaces it with one fresh commit, so it doesn't build up history.
- **`site` branch:** holds the finished website. Each run replaces it the same way.
- **The static site:** shows the same pages, but has no Refresh button because data updates on a schedule.

### Set up GitHub Actions

1. Merge this into `main`. GitHub only runs scheduled workflows from the default branch.
2. In the repository, open **Settings > Actions > General > Workflow permissions** and choose **Read and write permissions**, so the workflow can push the `data` and `site` branches.
3. Open **Actions > Daily refresh > Run workflow** to start the first run by hand. It takes several minutes, because it builds the backtests from scratch.
4. Check the **Check Yahoo can be reached** step. If it fails, Yahoo is blocking GitHub's servers and this setup won't work as it is.

After that, it runs every weekday at 18:00 WIB. GitHub sometimes starts scheduled runs late. A failed refresh still publishes the last good result and marks the run as failed, so you'll get GitHub's failure email.

### Set up Vercel

1. In Vercel, choose **Add New > Project** and import this repository.
2. Set **Framework Preset** to **Other**. Leave the build command and output directory empty.
3. Deploy, then open **Settings > Git** and set the **Production Branch** to `site`.
4. Redeploy once, or wait for the next daily run.

`vercel.json` tells Vercel to skip every branch except `site`, so pushes to `main` or `data` don't create deployments.

The Vercel link is public, so anyone who finds it can see the picks. Vercel's password protection is a paid option. Don't share the link widely, for the investment advice reasons above.

### Try it locally

```bash
python -m idxquant.daily --out site
python -m http.server 8790 --directory site
```

Then open http://127.0.0.1:8790.

## Keeping it up to date

- **Stock list:** edit `idxquant/universe.csv` by hand. It holds the IDX80 (next change due after 29 January 2027) plus other stocks that traded at least about Rp 4bn a day when the list was compiled. Stocks that later go quiet are dropped automatically by the liquidity filter.
- **Rules:** thresholds are in `idxquant/config.py`.
