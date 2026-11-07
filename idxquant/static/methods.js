// The "How it works" pages. Tunable numbers come from the app's live settings in config.py.
function methodTopics(cfg) {
  const percent = (value, digits = 0) => `${(value * 100).toFixed(digits)}%`;
  const months = Math.round(cfg.max_fundamental_age_days / 30.4);
  const billions = cfg.min_value_idr / 1e9;
  const longDays = Math.floor((cfg.long_days * 5) / 7);
  const shortDays = Math.floor((cfg.short_days * 5) / 7);

  return [
    {
      id: "valuation",
      title: "Valuation",
      intro: "These figures compare today's closing price with the company's latest annual report, taken from Yahoo Finance. Only PE, PBV, dividend yield, ROE and debt to equity feed the scores. The rest are there to help you judge the company.",
      items: [
        {
          name: "PE (price to earnings)",
          means: "How many rupiah you pay for each rupiah of yearly profit.",
          formula: "PE = closing price / earnings per share",
          read: "Lower is cheaper. For example, Rp 5,000 with earnings of Rp 500 per share gives a PE of 10. Compare it with the sector median shown beside it.",
          caution: "It uses the latest annual report, so earnings can be over a year old. Zero or negative earnings show a dash.",
        },
        {
          name: "PBV (price to book value)",
          means: "The price compared with the company's net assets per share.",
          formula: "Book value per share = shareholders' equity / shares\nPBV = closing price / book value per share",
          read: "Below 1 means the market values the company at less than its net assets. Banks and asset-heavy companies are usually judged on this.",
          caution: "Negative equity shows a dash. A low PBV can also mean the market expects poor returns.",
        },
        {
          name: "ROE (return on equity)",
          means: "How much profit the company makes from shareholders' money.",
          formula: "ROE = latest annual net income / shareholders' equity",
          read: "Higher is better. A ROE of 20% means Rp 20 of profit a year for every Rp 100 of equity.",
          caution: "High debt can lift ROE, which is why quality also looks at debt.",
        },
        {
          name: "Dividend yield",
          means: "The cash paid to shareholders over the last year, relative to the price.",
          formula: "Dividend yield = rupiah dividends per share, last 365 days / closing price",
          read: "Higher means more cash back. It uses dividends actually paid, not forecasts.",
          caution: "A one-off special dividend or a falling price can make it look unusually high.",
        },
        {
          name: "Market cap and debt to equity",
          means: "The size of the company, and how much it relies on borrowing.",
          formula: "Market cap = closing price x shares\nDebt to equity = total debt / shareholders' equity",
          read: "Both feed the factor scores: market cap into size, and debt into quality.",
          caution: "Debt to equity is ignored for banks, because taking deposits is their business.",
        },
        {
          name: "Sector median",
          means: "The typical PE and PBV of the stock's peers.",
          formula: `Median of the sector's stocks, needing at least ${cfg.min_sector_size} with a usable value`,
          read: "This is the fair value used for long-term targets.",
          caution: "Sector groups are assigned by hand, and small sectors have few peers.",
        },
        {
          name: "P/S (price to sales)",
          means: "The price compared with yearly revenue.",
          formula: "P/S = market cap / latest annual revenue",
          read: "Lower is cheaper. It's useful when a company makes little or no profit, since revenue is rarely negative.",
          caution: "It ignores profitability, so compare it within a sector. Low-margin retailers normally look cheap on this.",
        },
        {
          name: "EV/EBITDA",
          means: "What the whole business costs compared with its operating cash earnings.",
          formula: "Enterprise value = market cap + total debt - cash\nEV/EBITDA = enterprise value / latest annual EBITDA",
          read: "Lower is cheaper. Unlike PE, it counts debt, so it compares companies with different borrowing fairly.",
          caution: "It doesn't apply to banks and finance companies, and it needs positive EBITDA. Heavy spending on equipment isn't counted.",
        },
        {
          name: "Earnings yield",
          means: "PE turned upside down, as a percentage.",
          formula: "Earnings yield = earnings per share / closing price",
          read: "Higher is cheaper. A 10% yield means Rp 10 of yearly profit for every Rp 100 of share price, which is easy to compare with a deposit rate.",
          caution: "Profit isn't cash paid to you, and it comes from the last annual report.",
        },
        {
          name: "Free cash flow yield",
          means: "The real cash the business generated, relative to its market value.",
          formula: "Free cash flow yield = latest annual free cash flow / market cap",
          read: "Higher is better. A company showing profits but poor cash flow deserves a closer look.",
          caution: "One year of heavy investment can make it low or negative. It doesn't apply to banks and finance companies.",
        },
        {
          name: "Margins",
          means: "How much of each rupiah of revenue is left at each stage.",
          formula: "Gross margin = gross profit / revenue\nOperating margin = operating income / revenue\nNet margin = net income / revenue",
          read: "Higher is better, and steady margins suggest pricing power. Compare them within a sector.",
          caution: "One-off gains can lift net margin, and Yahoo has no gross or operating figures for some banks.",
        },
        {
          name: "ROA (return on assets)",
          means: "How much profit the company makes from everything it owns.",
          formula: "ROA = latest annual net income / total assets",
          read: "Higher is better. Unlike ROE, debt can't flatter it, so the two together show how much borrowing helps.",
          caution: "Banks naturally have low ROA, because they hold large assets funded by deposits.",
        },
        {
          name: "Growth",
          means: "How fast sales and earnings have changed.",
          formula: "Yearly growth = latest year / previous year - 1\nEPS per year = (latest EPS / oldest EPS)^(1 / years between) - 1",
          read: "Yearly figures show the latest change, and EPS per year smooths the whole span of up to 4 reports.",
          caution: "Growth from a loss shows a dash, and only about 4 years are available. Commodity companies swing with prices.",
        },
        {
          name: "Net debt to EBITDA",
          means: "How many years of operating earnings it would take to repay debt.",
          formula: "Net debt = total debt - cash\nNet debt to EBITDA = net debt / latest annual EBITDA",
          read: "Lower is safer. A negative figure means the company holds more cash than debt.",
          caution: "It doesn't apply to banks and finance companies, and it needs positive EBITDA.",
        },
        {
          name: "Current ratio",
          means: "Whether short-term assets cover bills due within a year.",
          formula: "Current ratio = current assets / current liabilities",
          read: "Above 1 means short-term assets exceed short-term debts. A value below 1 deserves a closer look, though some retailers run that way safely.",
          caution: "It doesn't apply to banks and finance companies. Stock that's slow to sell counts as a current asset.",
        },
        {
          name: "Interest cover",
          means: "How easily operating profit pays the interest bill.",
          formula: "Interest cover = operating income / interest expense",
          read: "Higher is safer. Below about 2 times means little room if profits fall.",
          caution: "It doesn't apply to banks and finance companies, and it says nothing about repaying the debt itself.",
        },
        {
          name: "Payout ratio",
          means: "How much of earnings goes out as dividends.",
          formula: "Payout ratio = dividends per share, last 365 days / earnings per share",
          read: "Lower leaves room to reinvest or keep paying in a bad year. Above 100% means paying out more than it earned.",
          caution: "It compares recent dividends with last year's earnings, so the two periods don't match exactly.",
        },
        {
          name: "Graham value",
          means: "A classic rough fair value from Benjamin Graham.",
          formula: "Graham value = square root of (22.5 x EPS x book value per share)",
          read: "It assumes a fair stock has a PE of 15 and a PBV of 1.5 at most. A price below it looks cheap on this simple test.",
          caution: "It's a rough screen for steady companies, and suits asset-light or fast-growing ones poorly. It doesn't affect the picks.",
        },
        {
          name: "Yearly history",
          means: "How the company and its valuation changed year by year.",
          formula: "Each annual report is valued at the closing price on its own report date\nPE = that price / that year's EPS\nPBV = that price / that year's book value per share",
          read: "It shows whether today's multiple is high or low against the company's own past, and whether profits are rising.",
          caution: "Free data has about 4 years. US dollar reporters use today's exchange rate for every year. A stock split or rights issue can distort older years.",
        },
        {
          name: "US dollar reporters and old reports",
          means: "Some IDX companies, mainly in coal, report in US dollars. Old reports are flagged.",
          formula: `Earnings and book value x the latest USD/IDR rate\nOut of date = report older than ${months} months`,
          read: "Prices and dividends are already in rupiah, so only the reported figures are converted.",
          caution: `An out-of-date report can't produce a long-term pick. If there's no USD/IDR rate that day, PE and PBV show a dash.`,
        },
      ],
    },
    {
      id: "factors",
      title: "Factor scores",
      intro: "Each score runs from 0 to 100 and shows where a stock ranks against the rest of the stock list. A score of 85 means it beats about 85% of them.",
      items: [
        {
          name: "Value",
          means: "How cheap the stock is compared with its sector.",
          formula: `Rank each of these within the sector, then average:\n  earnings yield = 1 / PE\n  book yield = 1 / PBV\n  dividend yield`,
          read: "Higher means cheaper than peers. Ranking inside the sector matters, since a bank's PBV can't be compared with a miner's.",
          caution: `Sectors with fewer than ${cfg.min_sector_size} scored stocks are ranked against the whole list. Missing parts are skipped. Cheap stocks can stay cheap for good reasons.`,
        },
        {
          name: "Quality",
          means: "How profitable, steady and lightly indebted the company is.",
          formula: "Rank each of these across the whole list, then average:\n  ROE\n  earnings stability = average net income / its standard deviation\n  low debt to equity (skipped for banks)",
          read: "Higher means a stronger business on these measures.",
          caution: "Free data has only about 4 years of annual results. Stability needs at least 3 years and positive average earnings.",
        },
        {
          name: "Momentum",
          means: "How strongly the price has risen over the past year.",
          formula: "Momentum = price 21 trading days ago / price 252 trading days ago - 1\nThen rank across the whole list",
          read: "Higher means a stronger trend. The latest month is left out because very recent moves often reverse. Dividends are included.",
          caution: "Momentum can turn quickly, and its past results are flattered by testing only today's index members.",
        },
        {
          name: "Size",
          means: "How large the company is.",
          formula: "Rank market cap across the whole list",
          read: "Higher means larger.",
          caution: "It's shown for information only and isn't part of the combined score.",
        },
        {
          name: "Combined score",
          means: "The single number used to choose long-term candidates.",
          formula: `Combined = (value + quality + momentum) / 3\nLong-term candidates = top ${percent(cfg.factor_top_pct)} of the list`,
          read: "Equal weights, by choice: they're simple and aren't fitted to past data.",
          caution: "If any of the three is missing there's no combined score. The value and quality parts can't be tested on past data with free information.",
        },
      ],
    },
    {
      id: "arbitrage",
      title: "Statistical arbitrage",
      intro: "Two stocks that tend to move together can drift apart for a while. The app looks for pairs like that and flags when one has become unusually cheap against the other.",
      items: [
        {
          name: "Finding pairs",
          means: "Which stocks have a lasting price relationship, not just a similar run.",
          formula: `Daily log prices over ${cfg.pair_lookback} trading days, same sector only\nlog(A) = alpha + beta x log(B)\nEngle-Granger cointegration test, kept at ${percent(cfg.pair_pvalue)} significance`,
          read: "Pairs are re-tested at every refresh. A corrected test (Benjamini-Hochberg) allows for trying many pairs, so few survive. That's deliberate.",
          caution: "A relationship that held in the past can break, for example after a takeover or a change in the business.",
        },
        {
          name: "Gap",
          means: "How far the pair is from its usual relationship right now.",
          formula: `Spread = log(A) - (alpha + beta x log(B))\nGap = (spread today - its ${cfg.z_window}-day average) / its ${cfg.z_window}-day standard deviation`,
          read: "Measured in standard deviations (σ). A gap of -2.3σ means the stock is unusually cheap against its partner, and positive means unusually rich.",
          caution: "A gap shows how unusual the price is, not that it will close.",
        },
        {
          name: "Half-life",
          means: "How quickly gaps have tended to close.",
          formula: `Regress the daily change in spread on the previous day's spread\nHalf-life = ln(2) / -slope\nKept if between ${cfg.pair_hl_min} and ${cfg.pair_hl_max} days`,
          read: "A half-life of 8 days means a gap has typically halved in about 8 trading days.",
          caution: "It's a past average, and a single gap can take much longer.",
        },
        {
          name: "Signal",
          means: "What the app does with the gap.",
          formula: `Active: ${cfg.z_active}σ or lower\nWatch: ${cfg.z_active}σ to ${cfg.z_watch}σ\nBroken: ${cfg.z_stop}σ or lower\nNone: anything else\nOther side: the partner of a stock that is flagged`,
          read: "Only Active produces a pick. Broken means the gap has gone past the stop, so the app stays out.",
          caution: "The partner's gap is shown as the mirror of the cheap stock's gap, so it's approximate.",
        },
        {
          name: "Pair trade rules",
          means: "How a gap becomes a playbook.",
          formula: `Buy the cheap stock, up to ${percent(cfg.pair_entry_band, 1)} above the close\nTarget = price where the gap reaches ${cfg.z_exit}σ\nStop = price where the gap reaches ${cfg.z_stop}σ\nTime limit = ${cfg.pair_time_mult} x half-life, in trading days`,
          read: "Target and stop use the partner's closing price on the day of the pick.",
          caution: "Only the cheap stock is bought, because shorting on IDX is restricted. A true pair trade cancels market moves, but this one still carries market risk.",
        },
      ],
    },
    {
      id: "montecarlo",
      title: "Monte Carlo",
      intro: `Each play is simulated ${cfg.mc_paths.toLocaleString("en-US")} times from the stock's own past behaviour, to show how often it might reach the target or the stop.`,
      items: [
        {
          name: "How a path is built",
          means: "One possible future for the stock.",
          formula: `Take the last ${cfg.mc_lookback} trading days\nRemove the average daily move\nPick random ${cfg.mc_block_days}-day blocks and join them up, starting at the top of the entry zone`,
          read: "Blocks keep volatile stretches together. The average move is removed because a past trend isn't evidence of a future one.",
          caution: "With the trend removed, the odds reflect how much the stock moves, not whether the signal is any good.",
        },
        {
          name: "Hits target, hits stop, neither in time",
          means: "How each simulated trade ended.",
          formula: `Walk each path day by day using highs and lows\nFirst level touched ends the trade\nIf one day touches both, count it as the stop\nTime limit: ${longDays} trading days long term, ${shortDays} short term, 2 x half-life for pairs`,
          read: "The three figures add up to 100%. A high 'neither' means the stock is too quiet to reach either level in time.",
          caution: "Real trades can gap past a stop, so an actual loss can be bigger than the simulation shows.",
        },
        {
          name: "Average outcome and range",
          means: "The typical result across all paths, after costs.",
          formula: `Return = exit x (1 - ${percent(cfg.sell_fee, 2)}) / (entry x (1 + ${percent(cfg.buy_fee, 2)})) - 1\nAverage outcome = mean of all paths\nRange = 10th to 90th percentile`,
          read: "Costs are the app's default broker fees: buying and selling are both included.",
          caution: "A small positive average isn't an edge: it mostly comes from where the target and stop sit.",
        },
        {
          name: "Pair trade simulation",
          means: "Pairs need a different model, since the gap tends to close.",
          formula: "Simulate the partner stock with blocks of its past moves\nGap tomorrow = 0.5^(1 / half-life) x gap today + a random past shock\nStock price = alpha + beta x log(partner) + gap",
          read: "Moving the partner separately keeps market risk in the result.",
          caution: "It uses closing prices only, and assumes the gap keeps its past half-life. These odds haven't been checked against past data.",
        },
        {
          name: "The chart",
          means: "A picture of the simulation.",
          formula: `Lines: ${cfg.mc_chart_paths} of the ${cfg.mc_paths.toLocaleString("en-US")} paths, ending when the trade ends\nBand: the middle 80% of all paths\nBold line: the median`,
          read: "Blue reached the target, orange reached the stop, and grey ran out of time.",
          caution: "Finished trades stay at their exit price in the band and median, so a rising median isn't a forecast.",
        },
        {
          name: "Accuracy check",
          means: "Whether past predictions matched what really happened.",
          formula: `At past dates, predict using only earlier data\nCompare with what the stock then did\nShort term: past signals. Long term: the +${percent(cfg.long_target_cap)} and -${percent(cfg.long_stop)} levels each quarter`,
          read: "On the Results page, the predicted and actual columns should be close.",
          caution: "The long-term check tests price levels, not the factor score, and its cases overlap in time.",
        },
      ],
    },
    {
      id: "regime",
      title: "Market regime",
      intro: "Markets swing between quiet stretches and turbulent ones. This model reads the IHSG index to judge which one the market is in today.",
      items: [
        {
          name: "Market regime",
          means: "Whether the whole market is currently calm or stressed.",
          formula: `Two-state hidden Markov model on daily IHSG returns\nEach state has its own average return and volatility\nStressed = the state with the higher volatility, when its probability is above ${percent(cfg.regime_threshold)}`,
          read: "Calm markets drift gently. Stressed markets swing several times harder and tend to fall. The states are learned from the data, not set by hand.",
          caution: "It describes the market now and doesn't predict a turn. It only reads the index, so a single stock can behave differently. It's for information and doesn't change the picks.",
        },
        {
          name: "Stress probability",
          means: "How confident the model is that the market is stressed today.",
          formula: `Today's belief = yesterday's belief x the chance of switching\nThen update using how well today's move fits each state\nRefit every ${cfg.regime_refit_days} trading days, after at least ${cfg.regime_min_history} days of data`,
          read: "This is a filtered probability, so it uses only data up to that day. Many charts use smoothed probabilities, which look cleaner but peek at the future.",
          caution: "Because it can't see ahead, it reacts after a move starts, and it can flip back and forth around the threshold. One very large day can move it sharply.",
        },
        {
          name: "Signals by market regime",
          means: "How each signal did when it fired in calm and in stressed markets.",
          formula: "Label each past trade by the state known on its signal day\nThen compare trades, winners, average return and drawdown",
          read: "On the Results page. A big gap between the two rows suggests a signal depends on market conditions.",
          caution: "Stressed days are rare, so that row has fewer trades and more noise. Trades overlap, and the results use today's index members.",
        },
      ],
    },
    {
      id: "types",
      title: "Market type",
      intro: "The market regime gives a simple Calm or Stressed reading from the index. Market types look at several measures together, to describe what kind of market it is.",
      items: [
        {
          name: "Market type",
          means: "Which of several past kinds of market this week looks most like.",
          formula: `Gaussian mixture model groups similar weeks into ${cfg.cluster_groups} groups\nRefit every ${cfg.cluster_refit_weeks} weeks, after at least ${cfg.cluster_min_weeks} weeks of data\nEach group is named from its average measures:\n  Panic: very high volatility, falling\n  Rebound: very high volatility, rising\n  Rally: strongly rising\n  Weakening: falling, or few stocks above average\n  Quiet: anything else`,
          read: "Confidence is the model's probability for that type. Names come from what a group looks like, so a type keeps its meaning after each refit.",
          caution: "It describes the market now and doesn't predict the next move. The names are labels on statistical groups, so they fit some weeks poorly. It's for information and doesn't change the picks.",
        },
        {
          name: "Market type measures",
          means: "The five things the model looks at each week.",
          formula: `IHSG return over ${cfg.cluster_window_days} trading days\nIHSG volatility over ${cfg.cluster_window_days} days, per year\nShare of stocks above their 50-day average\nUSD/IDR change over ${cfg.cluster_window_days} days (up = weaker rupiah)\nAverage correlation between stocks over ${cfg.cluster_window_days} days`,
          read: "Breadth shows whether most stocks are moving or a few large ones are carrying the index. High correlation means stocks are moving together, which is typical of panics.",
          caution: "Values are measured against earlier weeks only. Today's index members are used for breadth and correlation, so past values leave out companies that have since left.",
        },
        {
          name: "Signals by market type",
          means: "How each signal did when it fired in each type of market.",
          formula: `Label each past trade by the latest market type known on its signal day\nCompare trades, winners and average return\nResults under ${cfg.cluster_min_trades} trades are hidden`,
          read: "On the Results page. A clear gap suggests a signal depends on market conditions.",
          caution: "Each trade uses a model fitted only on earlier weeks. Rare market types have few trades, and results use today's index members.",
        },
      ],
    },
    {
      id: "ml",
      title: "Machine learning",
      intro: "Two models learn from every stock's last ten years of prices, to give more information before buying. They're shown next to the picks and don't change them.",
      items: [
        {
          name: "ML odds",
          means: "How often trades like this one reached their target before their stop, according to a model trained on past setups.",
          formula: `Past setups: every stock, once every ${cfg.ml_step_days} trading days\nLong term: did +${percent(cfg.long_target_cap)} come before -${percent(cfg.long_stop)} within 12 months?\nShort term: did each past breakout's target come before its stop?\nModel: gradient-boosted decision trees (shallow, heavily smoothed)\nTrained only on setups whose result was known by today`,
          read: "Compare it with the usual rate shown beside it: that's how often any past setup worked. The gap is what the model adds.",
          caution: "It learned from about ten years that include few crashes, so a reading driven by market volatility rests on few past episodes.",
        },
        {
          name: "Measures the models use",
          means: "The nine things measured at every past setup and today.",
          formula: "1-month and 3-month return\n12-month momentum, leaving out the last month\nVolatility over 3 months, per year\nDistance from the 1-year high\nDistance from the 200-day average\nTrading activity: 20-day value against 120-day value\nIHSG 3-month return and volatility",
          read: "All are measured from that day and earlier only, so no past setup peeks at what came next.",
          caution: "There are no value or quality measures, because free data has no history of company financials. Similar setups use the first seven only.",
        },
        {
          name: "What moved the odds",
          means: "The measures that pushed today's ML odds up or down the most.",
          formula: "For each measure in turn:\n  replace today's value with its typical past value\n  effect = today's odds - the odds after the swap\nShow the four largest effects",
          read: "A positive effect means today's value of that measure raised the odds. The percentile says how unusual today's value is against all past setups. For example, IHSG volatility at +30 pts means the odds would be about 30 points lower if the market were as calm as usual.",
          caution: "Measures act together inside the model, and this swaps one at a time, so the effects are an approximation and don't add up exactly to the gap from the usual rate. When the IHSG measures lead, the reading is about the market as a whole and applies to most stocks today, not this one in particular.",
        },
        {
          name: "Similar past setups",
          means: "The past moments, across all stocks, that looked most like this stock does today, and what happened next.",
          formula: `Match on the stock's own measures, not the IHSG ones\nScale each measure, then find the ${cfg.ml_neighbours} nearest past setups (k-nearest neighbours)\nThe stock's own setups from the last ${cfg.ml_recent_days} days are left out\nReport the median return 3 and 12 months later, and the share that rose\nCompare with all past setups`,
          read: "If similar setups did much better or worse than all setups, today's pattern has a history. If they look like the usual, the pattern says little.",
          caution: "It's history, not a forecast: in testing these didn't reliably sort stocks into winners and losers. Returns are price changes with dividends, before trading costs.",
        },
        {
          name: "Model test",
          means: "How each model did on years it had never seen.",
          formula: "For each year:\n  train only on setups whose result was known before 1 January\n  predict that year's setups\nPool every year's predictions and score them",
          read: "This is called walk-forward testing. It's the honest way to test a market model, because the model never learns from the future it's tested on.",
          caution: "Each year's test still uses today's stock list, which leaves out companies that collapsed, so results are a little flattering.",
        },
        {
          name: "AUC",
          means: "How well the odds model ranks setups that worked above ones that didn't.",
          formula: `0.5 = no better than a coin\n1.0 = perfect\nThe app counts a model as having an edge at ${0.55} or more, when it also beat the usual rate`,
          read: "In stock prediction 0.55 to 0.60 is already useful. Also check the top and bottom fifth: how often the model's most and least hopeful setups actually worked.",
          caution: "A good AUC across all years can come mostly from timing the market as a whole, rather than from picking better stocks on the same day.",
        },
        {
          name: "Rank IC",
          means: "How well similar setups sort stocks by their next 3 months.",
          formula: "Each month: rank stocks by predicted return, and by actual return\nRank IC = the correlation of the two orders\nAverage over all tested months",
          read: "0 means no skill. In stock prediction, 0.05 is already useful, and the app counts 0.02 or more as an edge.",
          caution: "Months with few stocks are noisy. The pooled figure also mixes in market timing, so it can look better than the stock-sorting skill.",
        },
      ],
    },
    {
      id: "risk",
      title: "Before you buy",
      intro: "Checks that don't change the picks but can change how you buy them: how much today's picks overlap, what's coming up for each stock, what the news says, and where each sector is heading.",
      items: [
        {
          name: "Overlap between picks",
          means: "How closely today's picks rise and fall together, and how many come from one sector.",
          formula: `Daily returns over the last ${cfg.conc_window_days} trading days\nCorrelation for every pair of picks\nWarn when:\n  ${cfg.conc_min_sector} or more picks, and at least ${percent(cfg.conc_sector_share)} of them, share a sector\n  3 or more picks are linked by correlations of ${cfg.conc_pair_corr} or more\n  the picks behave like half as many bets or fewer`,
          read: "Correlation runs from -1 to 1. Around 0 means unrelated, 1 means they move as one. In the heatmap, stocks that move together are placed side by side, so a block of deep colour is a group to size as one position. The colour is full from 0.8, since daily correlations between stocks seldom go higher.",
          caution: `Correlations change, and they tend to rise in a sell-off, just when spreading out matters most. Stocks from different sectors can still move together, like a coal miner and the ship that carries its coal. A stock with fewer than ${cfg.conc_min_days} days in the window is left out.`,
        },
        {
          name: "News tone",
          means: "Whether the last week's headlines about a stock lean positive or negative.",
          formula: `Headlines from Google News naming the ticker or company, last ${cfg.news_days} days\nThe same story from several outlets counts once\nEach headline: rising words (naik, borong, rekomendasi) minus falling ones (anjlok, lepas, denda)\n  the part of the headline naming the stock is read first\n  "tidak", "belum" and "bukan" flip the next word\nTone = (positive - negative) / headlines\nPositive at +${0.3} or more, negative at -${0.3} or less, mixed between`,
          read: "Tested on 98 fresh headlines from ten stocks, read by hand: it agreed 72% of the time, never called the opposite direction, and was right 89% of the time when it called one. Its usual miss is reading a positive headline as neutral.",
          caution: "It counts words, it doesn't understand sentences, so sarcasm, questions and unusual phrasing fool it. Headlines are often about the whole market. Read the articles before acting, and don't treat a busy news week as a signal on its own.",
        },
        {
          name: "Earnings and dividends",
          means: "When the next results are due, and how the stock pays dividends.",
          formula: `Report dates from Yahoo, in Jakarta time\nNo announced date: last year's matching report + 1 year, labelled as an estimate\nFlagged on Today when a report is within ${cfg.event_warn_days} days\nUsual dividend months: months it paid in during each of the last 3 years`,
          read: "Prices can jump or fall sharply on results day. Knowing it's close lets you choose to buy before or after. A regular dividend month tells you roughly when the next one may come.",
          caution: "Yahoo's coverage of IDX dates is incomplete, and an estimate can be weeks out. Even an announced date can move if the company files early or late. The dividend yield uses the last 12 months only, so a one-off special payment can inflate it, and a company can cut or skip a dividend it paid for years.",
        },
        {
          name: "Price chart",
          means: "The stock's daily closing price over the last 3, 6 or 12 months, with today's play drawn on top.",
          formula: "Price: each day's close\n50-day average: mean of the last 50 closes\n200-day average: mean of the last 200 closes\nShaded band: today's buy zone; dashed lines: target and stop",
          read: "Price above a rising 200-day average is a long uptrend; below a falling one, a long downtrend. The 50-day average shows the shorter trend. The band and lines show where today's trade sits against the stock's recent range. Hover the chart to read any day's price and averages.",
          caution: "Averages lag: they confirm a trend after it starts, and they whipsaw in a sideways market. Prices aren't adjusted for dividends here, so a large payout shows as a drop on its ex-date. A stock listed less than a year ago has a shorter chart, and its 200-day average starts late.",
        },
        {
          name: "Sector rotation",
          means: "Which sectors have been rising or falling, week by week, over the last few months.",
          formula: `Each week: the average return of the sector's stocks, each counting the same\nLast ${cfg.rotation_weeks} weeks, week ending Friday\nSorted by the ${cfg.rotation_weeks}-week total`,
          read: "A sector turning from orange to blue across recent weeks is drawing money in. Compare each row with All stocks to see which sectors lead or lag the market.",
          caution: "Small sectors with one or two stocks swing hard on a single name. Equal weighting means a small stock moves its sector as much as a giant does.",
        },
        {
          name: "Independent bets",
          means: "How many unrelated positions today's picks add up to.",
          formula: "n picks, correlation matrix C\nIndependent bets = n x n / (sum of every C squared)\nn unrelated picks give n; n picks moving as one give 1",
          read: "If 14 picks count as about 4 independent bets, splitting your money evenly across all 14 spreads your risk much less than it looks. Today's figure sits under the picks on the Today page, beside the heatmap that shows which picks drive it.",
          caution: "It only sees past daily moves, not shared exposures that haven't shown up yet, like one commodity price or one owner.",
        },
      ],
    },
    {
      id: "picks",
      title: "How picks are chosen",
      intro: "This is how the app goes from the stock list to today's ranked table.",
      items: [
        {
          name: "Stock list",
          means: "The stocks the app looks at.",
          formula: `IDX80 members plus other liquid stocks (about 137), then keep stocks with:\n  median daily value of at least Rp ${billions} billion over 20 days\n  at least ${cfg.min_history_days} days of prices\n  no zero-volume day in the last ${cfg.suspension_window} days\n  a trade on the latest session`,
          read: "Thin or suspended stocks give false signals, so they're left out. The Results page lists which ones.",
          caution: "The list is kept by hand and needs updating when the index changes.",
        },
        {
          name: "Long-term play",
          means: "Good, cheap stocks to hold for months.",
          formula: `Qualifies: combined score in the top ${percent(cfg.factor_top_pct)}, with financials under ${months} months old\nEntry: from ${percent(cfg.long_entry_band)} below the close up to the close\nTarget: average of sector PE x EPS and sector PBV x book value, capped at +${percent(cfg.long_target_cap)}\nStop: ${percent(cfg.long_stop)} below the top of the entry zone\nTime limit: 12 months`,
          read: "The target assumes the stock moves back to its sector's typical valuation.",
          caution: "This play can't be backtested with free data. Its real test is the track record on the Results page.",
        },
        {
          name: "Short-term play",
          means: "A breakout to ride for days or weeks.",
          formula: `Qualifies: close above its ${cfg.short_trend_days}-day average, above the highest high of the previous ${cfg.short_breakout_days} days, on volume above their average\nEntry: from the close up to ${percent(cfg.short_entry_band)} above\nTarget: close + ${cfg.short_target_atr} x ATR(14)\nStop: close - ${cfg.short_stop_atr} x ATR(14)\nTime limit: 2 weeks`,
          read: "ATR is the average daily price range over 14 days, so the levels adjust to each stock's volatility.",
          caution: "This rule has lost money after costs in past data. See the Results page.",
        },
        {
          name: "Filters on every play",
          means: "Trades that aren't worth taking are dropped.",
          formula: `Minimum upside after costs: ${percent(cfg.min_up_long)} long term, ${percent(cfg.min_up_other)} short term and pairs\nStop must be at least Rp ${cfg.min_stop_price}\nAll prices rounded to valid IDX ticks`,
          read: "Upside is measured from the top of the entry zone. Entry lows, stops and targets round down, and entry highs round up, so rounding never flatters a trade.",
          caution: "On a quiet day few stocks qualify, and the list can be empty.",
        },
        {
          name: "Ranking",
          means: "The order of the table on the Today page.",
          formula: `Reward to risk = upside after costs / downside after costs\nSort highest first, ties broken by combined score\nEach stock appears once, under its best play\nShows at most ${cfg.max_rows} rows`,
          read: "Other plays on the same stock still show on its detail page.",
          caution: "When several long-term targets hit the cap, their reward to risk is nearly the same, so treat those ranks as tied.",
        },
        {
          name: "Backtest",
          means: "How each kind of signal did in past data.",
          formula: `Decisions use only earlier data\nEntry at the next day's open, with fees\nPairs are re-chosen every quarter\nRe-run every ${cfg.backtest_max_age_days} days, or when the long-term stop changes`,
          read: "Results are on the Results page: trades, winners, average return and worst drawdown.",
          caution: "It uses today's index members, so companies that collapsed are missing, which flatters results. Past results don't predict future ones.",
        },
      ],
    },
  ];
}

function renderMethods(container, cfg, topicId) {
  const topics = methodTopics(cfg);
  const topic = topics.find((item) => item.id === topicId) || topics[0];
  const tabs = topics
    .map((item) => `<a href="#/how/${item.id}" class="${item === topic ? "current" : ""}">${item.title}</a>`)
    .join("");
  const cards = topic.items
    .map(
      (item) => `<article class="stat">
        <h2>${item.name}</h2>
        <p>${item.means}</p>
        <pre>${item.formula}</pre>
        <dl>
          <dt>How to read it</dt><dd>${item.read}</dd>
          <dt>Watch out</dt><dd>${item.caution}</dd>
        </dl>
      </article>`,
    )
    .join("");
  container.innerHTML = `<h1>How it works</h1>
    <p class="sub">What each number means and how the app decides it.</p>
    <div class="tabs">${tabs}</div>
    <h2 class="topic">${topic.title}</h2>
    <p class="sub">${topic.intro}</p>
    <div class="stats">${cards}</div>`;
}
