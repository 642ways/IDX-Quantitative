"""The only module that talks to Yahoo Finance. It is unofficial, so failures return empty results."""
import json
import time
import urllib.parse
import urllib.request

import pandas as pd
import yfinance as yf

INDEX_SYMBOL = "^JKSE"
TIMESERIES_URL ="https://query2.finance.yahoo.com/ws/fundamentals-timeseries/v1/finance/timeseries/{symbol}"
YEAR_FIELDS = {
    "revenue": "annualTotalRevenue",
    "gross_profit": "annualGrossProfit",
    "operating_income": "annualOperatingIncome",
    "ebitda": "annualEBITDA",
    "free_cash_flow": "annualFreeCashFlow",
    "total_assets": "annualTotalAssets",
    "cash": "annualCashAndCashEquivalents",
    "current_assets": "annualCurrentAssets",
    "current_liabilities": "annualCurrentLiabilities",
    "interest_expense": "annualInterestExpense",
    "total_debt": "annualTotalDebt",
    "net_income": "annualNetIncome",
    "equity": "annualStockholdersEquity",
    "shares": "annualOrdinarySharesNumber",
}
FIELDS = [*YEAR_FIELDS.values(), "annualDilutedEPS", "annualBasicEPS"]
PRICE_RENAMES = {
    "Open": "open",
    "High": "high",
    "Low": "low",
    "Close": "close",
    "Adj Close": "adj_close",
    "Volume": "volume",
}


def _download(symbol: str, years: int) -> pd.DataFrame:
    return yf.Ticker(symbol).history(period=f"{years}y", interval="1d", auto_adjust=False)


def _download_fx() -> pd.DataFrame:
    return yf.Ticker("USDIDR=X").history(period="5d", interval="1d")


def _dividends(symbol: str) -> pd.Series:
    return yf.Ticker(symbol).dividends


def _timeseries(symbol: str) -> dict[str, list[dict]]:
    query = urllib.parse.urlencode(
        {"symbol": symbol, "type": ",".join(FIELDS), "period1": 1420070400, "period2": int(time.time())}
    )
    request = urllib.request.Request(
        f"{TIMESERIES_URL.format(symbol=symbol)}?{query}", headers={"User-Agent": "Mozilla/5.0"}
    )
    with urllib.request.urlopen(request, timeout=20) as response:
        payload = json.load(response)
    series = {}
    for result in payload["timeseries"]["result"]:
        name = result["meta"]["type"][0]
        series[name] = [point for point in result.get(name) or [] if point]
    return series


def fetch_prices(ticker: str, years: int = 10) -> pd.DataFrame:
    return _prices(f"{ticker}.JK", years)


def fetch_index(years: int = 10) -> pd.DataFrame:
    """The Jakarta Composite Index (IHSG)."""
    return _prices(INDEX_SYMBOL, years)


def _prices(symbol: str, years: int) -> pd.DataFrame:
    try:
        raw = _download(symbol, years)
        if raw is None or raw.empty:
            return pd.DataFrame()
        frame = raw.rename(columns=PRICE_RENAMES)[list(PRICE_RENAMES.values())]
        index = pd.DatetimeIndex(frame.index)
        frame.index = (index.tz_localize(None) if index.tz is not None else index).normalize()
        return frame
    except Exception:
        return pd.DataFrame()


def _latest(series: dict, name: str) -> dict | None:
    points = series.get(name) or []
    return points[-1] if points else None


def _value(point: dict | None) -> float | None:
    return point["reportedValue"]["raw"] if point else None


def _by_date(series: dict, name: str) -> dict[str, float]:
    return {point["asOfDate"]: _value(point) for point in series.get(name) or []}


def _yearly(series: dict) -> list[dict]:
    """One row per report date, so a figure can never be matched with another year's."""
    columns = {key: _by_date(series, name) for key, name in YEAR_FIELDS.items()}
    eps = _by_date(series, "annualBasicEPS") | _by_date(series, "annualDilutedEPS")
    dates = sorted(columns["net_income"])
    return [
        {"as_of": day, "eps": eps.get(day)} | {key: values.get(day) for key, values in columns.items()}
        for day in dates
    ]


def _dividends_ttm(symbol: str) -> float | None:
    """Dividends per share paid over the last year, always in rupiah."""
    try:
        paid = _dividends(symbol)
    except Exception:
        return None
    if paid is None or paid.empty:
        return None
    index = pd.DatetimeIndex(paid.index)
    index = index.tz_localize(None) if index.tz is not None else index
    return float(paid[index >= pd.Timestamp.now() - pd.Timedelta(days=365)].sum())


def fetch_fundamentals(ticker: str) -> dict | None:
    symbol = f"{ticker}.JK"
    try:
        series = _timeseries(symbol)
        income = _latest(series, "annualNetIncome")
        if income is None:
            return None
        eps = _latest(series, "annualDilutedEPS") or _latest(series, "annualBasicEPS")
        return {
            "as_of": income["asOfDate"],
            "currency": income.get("currencyCode"),
            "eps": _value(eps),
            "equity": _value(_latest(series, "annualStockholdersEquity")),
            "net_income_history": [_value(point) for point in series["annualNetIncome"]],
            "total_debt": _value(_latest(series, "annualTotalDebt")),
            "shares": _value(_latest(series, "annualOrdinarySharesNumber")),
            "dividends_ttm": _dividends_ttm(symbol),
            "history": _yearly(series),
        }
    except Exception:
        return None


def fetch_usdidr() -> float | None:
    try:
        frame = _download_fx()
    except Exception:
        return None
    return None if frame is None or frame.empty else float(frame["Close"].iloc[-1])
