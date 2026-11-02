import pandas as pd

from idxquant.check import check_yahoo, main


class Fetcher:
    def __init__(self, prices=True, fundamentals=True, index=True, rate=True):
        self.prices, self.fundamentals, self.index, self.rate = prices, fundamentals, index, rate

    def fetch_prices(self, ticker, years=10):
        return pd.DataFrame({"close": [1.0]}) if self.prices else pd.DataFrame()

    def fetch_fundamentals(self, ticker):
        return {"eps": 1.0} if self.fundamentals else None

    def fetch_index(self):
        return pd.DataFrame({"close": [1.0]}) if self.index else pd.DataFrame()

    def fetch_usdidr(self):
        return 16000.0 if self.rate else None


def test_everything_working():
    assert all(check_yahoo(Fetcher()).values())


def test_reports_each_part_separately():
    results = check_yahoo(Fetcher(fundamentals=False))
    assert results["prices"] is True
    assert results["fundamentals"] is False


def test_a_part_that_raises_counts_as_failed():
    class Broken(Fetcher):
        def fetch_prices(self, ticker, years=10):
            raise RuntimeError("blocked")

    assert check_yahoo(Broken())["prices"] is False


def test_main_exit_code_shows_failure(capsys):
    assert main(Fetcher()) == 0
    assert main(Fetcher(prices=False)) == 1
    assert "prices" in capsys.readouterr().out
