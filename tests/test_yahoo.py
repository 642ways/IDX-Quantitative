import pandas as pd

from idxquant import yahoo


def raise_error(*args, **kwargs):
    raise RuntimeError("Yahoo is down")


def raw_frame():
    idx = pd.to_datetime(["2026-10-30"])
    return pd.DataFrame(
        {"Open": [10.0], "High": [12.0], "Low": [9.0], "Close": [11.0], "Adj Close": [10.5], "Volume": [500]},
        index=idx,
    )


def test_fetch_prices_returns_empty_when_yahoo_fails(monkeypatch):
    monkeypatch.setattr(yahoo, "_download", raise_error)
    assert yahoo.fetch_prices("XXXX").empty


def test_fetch_prices_adds_jk_suffix(monkeypatch):
    seen = {}

    def capture(symbol, years):
        seen["symbol"] = symbol
        return raw_frame()

    monkeypatch.setattr(yahoo, "_download", capture)
    yahoo.fetch_prices("BBCA")
    assert seen["symbol"] == "BBCA.JK"


def test_fetch_prices_normalises_columns(monkeypatch):
    monkeypatch.setattr(yahoo, "_download", lambda symbol, years: raw_frame())
    frame = yahoo.fetch_prices("BBCA")
    assert list(frame.columns) == ["open", "high", "low", "close", "adj_close", "volume"]
    assert frame["adj_close"].iloc[0] == 10.5


def test_fetch_fundamentals_none_when_yahoo_fails(monkeypatch):
    monkeypatch.setattr(yahoo, "_timeseries", raise_error)
    assert yahoo.fetch_fundamentals("XXXX") is None


def test_fetch_prices_empty_when_a_column_is_missing(monkeypatch):
    monkeypatch.setattr(yahoo, "_download", lambda symbol, years: raw_frame().drop(columns="Adj Close"))
    assert yahoo.fetch_prices("BBCA").empty


def test_fetch_fundamentals_none_on_a_malformed_point(monkeypatch):
    bad = {"annualNetIncome": [{"asOfDate": "2025-12-31"}]}
    monkeypatch.setattr(yahoo, "_timeseries", lambda symbol: bad)
    monkeypatch.setattr(yahoo, "_dividends", lambda symbol: pd.Series(dtype=float))
    assert yahoo.fetch_fundamentals("BBCA") is None


def point(as_of, value):
    return {"asOfDate": as_of, "currencyCode": "IDR", "reportedValue": {"raw": value}}


def test_fundamentals_keep_each_year_aligned(monkeypatch):
    series = {
        "annualNetIncome": [point("2024-12-31", 10.0), point("2025-12-31", 20.0)],
        "annualTotalRevenue": [point("2024-12-31", 100.0), point("2025-12-31", 200.0)],
        "annualEBITDA": [point("2025-12-31", 30.0)],
        "annualDilutedEPS": [point("2024-12-31", 1.0), point("2025-12-31", 2.0)],
    }
    monkeypatch.setattr(yahoo, "_timeseries", lambda symbol: series)
    monkeypatch.setattr(yahoo, "_dividends", lambda symbol: pd.Series(dtype=float))
    history = yahoo.fetch_fundamentals("BBCA")["history"]
    assert [row["as_of"] for row in history] == ["2024-12-31", "2025-12-31"]
    assert history[0]["ebitda"] is None
    assert history[1]["ebitda"] == 30.0
    assert history[0]["revenue"] == 100.0
    assert history[1]["eps"] == 2.0


def test_fetch_usdidr_history_uses_the_rate_symbol(monkeypatch):
    seen = {}

    def capture(symbol, years):
        seen["symbol"] = symbol
        return raw_frame()

    monkeypatch.setattr(yahoo, "_download", capture)
    assert list(yahoo.fetch_usdidr_history()["close"]) == [11.0]
    assert seen["symbol"] == "USDIDR=X"


def test_fetch_usdidr_history_tolerates_a_missing_adjusted_close(monkeypatch):
    monkeypatch.setattr(yahoo, "_download", lambda symbol, years: raw_frame().drop(columns="Adj Close"))
    assert list(yahoo.fetch_usdidr_history()["close"]) == [11.0]


def test_fetch_index_uses_the_ihsg_symbol(monkeypatch):
    seen = {}

    def capture(symbol, years):
        seen["symbol"] = symbol
        return raw_frame()

    monkeypatch.setattr(yahoo, "_download", capture)
    assert list(yahoo.fetch_index()["close"]) == [11.0]
    assert seen["symbol"] == "^JKSE"


def test_fetch_index_empty_when_yahoo_fails(monkeypatch):
    monkeypatch.setattr(yahoo, "_download", raise_error)
    assert yahoo.fetch_index().empty


def test_fetch_usdidr_none_when_yahoo_fails(monkeypatch):
    monkeypatch.setattr(yahoo, "_download_fx", raise_error)
    assert yahoo.fetch_usdidr() is None


def test_fetch_events_none_when_yahoo_fails(monkeypatch):
    monkeypatch.setattr(yahoo, "_earnings_dates", raise_error)
    monkeypatch.setattr(yahoo, "_actions", raise_error)
    assert yahoo.fetch_events("BBCA") is None


def test_fetch_events_keeps_dividends_and_splits_apart(monkeypatch):
    actions = pd.DataFrame(
        {"Dividends": [0.0, 210.0, 0.0], "Stock Splits": [0.0, 0.0, 5.0]},
        index=pd.DatetimeIndex(["2026-01-05", "2026-06-22", "2021-10-13"], tz="Asia/Jakarta"),
    )
    monkeypatch.setattr(yahoo, "_earnings_dates", lambda symbol: ["2027-01-26"])
    monkeypatch.setattr(yahoo, "_actions", lambda symbol: actions)
    found = yahoo.fetch_events("BBCA")
    assert found == {"earnings": ["2027-01-26"], "dividends": [["2026-06-22", 210.0]], "splits": [["2021-10-13", 5.0]]}


def test_earnings_dates_are_read_in_jakarta_time(monkeypatch):
    stamps = pd.DatetimeIndex(["2026-10-26 20:00"], tz="America/New_York")

    class Ticker:
        def __init__(self, symbol):
            pass

        def get_earnings_dates(self, limit):
            return pd.DataFrame({"EPS Estimate": [1.0]}, index=stamps)

    monkeypatch.setattr(yahoo.yf, "Ticker", Ticker)
    assert yahoo._earnings_dates("BBCA.JK") == ["2026-10-27"]
