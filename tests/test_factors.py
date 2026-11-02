from datetime import date

import numpy as np
import pandas as pd
import pytest

from idxquant.factors import earnings_stability, momentum_12_1, score, valuation, valuation_history

TODAY = date(2026, 11, 2)


def make_f(**overrides):
    base = {
        "as_of": "2025-12-31",
        "currency": "IDR",
        "eps": 500.0,
        "equity": 2e12,
        "net_income_history": [4e11, 5e11],
        "total_debt": 1e12,
        "shares": 1e9,
        "dividends_ttm": 100.0,
    }
    return base | overrides


def test_pe_pbv_basic():
    v = valuation(5000, make_f(), None, TODAY)
    assert v["pe"] == 10
    assert v["pbv"] == 2.5


def test_dividend_yield_and_market_cap():
    v = valuation(5000, make_f(), None, TODAY)
    assert v["dividend_yield"] == pytest.approx(0.02)
    assert v["market_cap"] == 5e12


def test_negative_earnings_gives_no_pe():
    assert valuation(5000, make_f(eps=-10.0), None, TODAY)["pe"] is None


def test_zero_earnings_gives_no_pe():
    assert valuation(5000, make_f(eps=0.0), None, TODAY)["pe"] is None


def test_negative_equity_gives_no_pbv():
    assert valuation(5000, make_f(equity=-1.0), None, TODAY)["pbv"] is None


def test_usd_reporter_is_converted():
    v = valuation(2500, make_f(eps=0.05, equity=1e9, currency="USD"), 16000, TODAY)
    assert v["pe"] == pytest.approx(2500 / (0.05 * 16000))
    assert v["pbv"] == pytest.approx(2.5e12 / (1e9 * 16000))


def test_usd_reporter_without_rate_is_missing():
    v = valuation(2500, make_f(eps=0.05, currency="USD"), None, TODAY)
    assert v["pe"] is None
    assert v["pbv"] is None


def test_dividends_are_not_converted_for_usd_reporter():
    v = valuation(2500, make_f(eps=0.05, currency="USD", dividends_ttm=100.0), 16000, TODAY)
    assert v["dividend_yield"] == pytest.approx(0.04)


def test_missing_fundamentals_all_null():
    v = valuation(5000, None, None, TODAY)
    assert v["pe"] is None
    assert v["pbv"] is None
    assert v["stale"] is True


def test_stale_when_older_than_18_months():
    assert valuation(5000, make_f(as_of="2024-12-31"), None, TODAY)["stale"] is True
    assert valuation(5000, make_f(as_of="2025-12-31"), None, TODAY)["stale"] is False


def year(as_of, **overrides):
    base = {
        "as_of": as_of,
        "revenue": 1000.0,
        "gross_profit": 400.0,
        "operating_income": 200.0,
        "ebitda": 300.0,
        "free_cash_flow": 50.0,
        "total_assets": 2000.0,
        "cash": 100.0,
        "current_assets": 600.0,
        "current_liabilities": 300.0,
        "interest_expense": 40.0,
        "total_debt": 500.0,
        "net_income": 100.0,
        "eps": 10.0,
        "equity": 1000.0,
        "shares": 10.0,
    }
    return base | overrides


def rich_f(**overrides):
    history = [
        year("2023-12-31", revenue=800.0, eps=5.0),
        year("2024-12-31", revenue=900.0, eps=8.0),
        year("2025-12-31"),
    ]
    return make_f(eps=10.0, equity=1000.0, shares=10.0, total_debt=500.0, dividends_ttm=5.0, history=history) | overrides


def details(sector="Coal", close=100.0, f=None, usdidr=None):
    return valuation(close, f or rich_f(), usdidr, TODAY, sector)


def test_price_multiples():
    v = details()
    assert v["ps"] == pytest.approx(1.0)
    assert v["ev_ebitda"] == pytest.approx((1000 + 500 - 100) / 300)
    assert v["fcf_yield"] == pytest.approx(0.05)
    assert v["earnings_yield"] == pytest.approx(0.10)


def test_margins_and_asset_returns():
    v = details()
    assert v["gross_margin"] == pytest.approx(0.4)
    assert v["operating_margin"] == pytest.approx(0.2)
    assert v["net_margin"] == pytest.approx(0.1)
    assert v["roa"] == pytest.approx(0.05)


def test_growth_uses_the_latest_two_years_and_the_full_span():
    v = details()
    assert v["revenue_growth"] == pytest.approx(1000 / 900 - 1)
    assert v["eps_growth"] == pytest.approx(0.25)
    assert v["eps_cagr"] == pytest.approx(2**0.5 - 1)


def test_growth_from_a_loss_is_missing():
    f = rich_f(history=[year("2024-12-31", eps=-1.0), year("2025-12-31")])
    v = details(f=f)
    assert v["eps_growth"] is None
    assert v["eps_cagr"] is None


def test_financial_health():
    v = details()
    assert v["net_debt_ebitda"] == pytest.approx(400 / 300)
    assert v["current_ratio"] == pytest.approx(2.0)
    assert v["interest_cover"] == pytest.approx(5.0)


def test_per_share_figures():
    v = details()
    assert v["dividend_per_share"] == 5.0
    assert v["payout_ratio"] == pytest.approx(0.5)
    assert v["graham_value"] == pytest.approx((22.5 * 10 * 100) ** 0.5)


def test_loss_makers_have_no_graham_value_or_payout():
    f = rich_f(eps=-5.0)
    v = details(f=f)
    assert v["graham_value"] is None
    assert v["payout_ratio"] is None


def test_debt_based_figures_do_not_apply_to_lenders():
    for sector in ("Banks", "Finance"):
        v = details(sector)
        assert v["ev_ebitda"] is None
        assert v["fcf_yield"] is None
        assert v["net_debt_ebitda"] is None
        assert v["current_ratio"] is None
        assert v["interest_cover"] is None
        assert v["net_margin"] == pytest.approx(0.1)


def test_new_figures_convert_us_dollar_reporters():
    usd = rich_f(currency="USD", eps=0.01, equity=1.0, total_debt=0.5, dividends_ttm=None)
    usd["history"] = [year("2025-12-31", revenue=1.0, ebitda=0.3, cash=0.1, total_debt=0.5, free_cash_flow=0.05)]
    v = details(close=100.0, f=usd, usdidr=1000.0)
    assert v["ps"] == pytest.approx(1.0)
    assert v["ev_ebitda"] == pytest.approx((1000 + 500 - 100) / 300)
    assert v["fcf_yield"] == pytest.approx(0.05)
    assert v["gross_margin"] == pytest.approx(400.0)


def test_negative_ebitda_gives_no_multiple():
    f = rich_f(history=[year("2025-12-31", ebitda=-10.0)])
    v = details(f=f)
    assert v["ev_ebitda"] is None
    assert v["net_debt_ebitda"] is None


def test_older_cached_fundamentals_still_work():
    v = valuation(5000, make_f(), None, TODAY, "Coal")
    assert v["pe"] == 10
    assert v["ps"] is None


def test_missing_fundamentals_have_every_key():
    assert set(valuation(5000, None, None, TODAY)) == set(details())


def test_yearly_history_values_each_year_at_its_own_price():
    prices = pd.Series(
        [50.0, 60.0, 80.0],
        index=pd.to_datetime(["2023-12-29", "2024-12-30", "2025-12-30"]),
    )
    years = valuation_history(prices, rich_f(), None)
    assert [row["year"] for row in years] == ["2023", "2024", "2025"]
    assert years[0]["price"] == 50.0
    assert years[0]["pe"] == pytest.approx(10.0)
    assert years[2]["pe"] == pytest.approx(8.0)
    assert years[2]["pbv"] == pytest.approx(0.8)
    assert years[2]["net_margin"] == pytest.approx(0.1)
    assert years[2]["revenue"] == 1000.0


def test_yearly_history_before_prices_start_has_no_multiples():
    prices = pd.Series([80.0], index=pd.to_datetime(["2025-06-30"]))
    years = valuation_history(prices, rich_f(), None)
    assert years[0]["price"] is None
    assert years[0]["pe"] is None
    assert years[-1]["price"] == 80.0


def test_yearly_history_empty_without_fundamentals():
    assert valuation_history(pd.Series(dtype=float), None, None) == []
    assert valuation_history(pd.Series(dtype=float), make_f(), None) == []


def rows(items):
    defaults = {
        "pe": 10.0,
        "pbv": 2.0,
        "dividend_yield": 0.03,
        "roe": 0.15,
        "debt_to_equity": 0.5,
        "earnings_stability": 3.0,
        "momentum": 0.1,
        "market_cap": 1e12,
    }
    return pd.DataFrame([defaults | item for item in items])


def test_value_ranks_within_sector():
    frame = score(
        rows(
            [
                {"ticker": "B1", "sector": "Banks", "pe": 8.0, "pbv": 1.0},
                {"ticker": "B2", "sector": "Banks", "pe": 12.0, "pbv": 2.0},
                {"ticker": "B3", "sector": "Banks", "pe": 16.0, "pbv": 3.0},
                {"ticker": "C1", "sector": "Coal", "pe": 2.0, "pbv": 0.4},
                {"ticker": "C2", "sector": "Coal", "pe": 3.0, "pbv": 0.5},
                {"ticker": "C3", "sector": "Coal", "pe": 8.0, "pbv": 1.0},
            ]
        )
    ).set_index("ticker")
    assert frame.loc["B1", "value"] > frame.loc["C3", "value"]


def test_lone_stock_in_sector_ranks_against_everyone():
    frame = score(
        rows(
            [
                {"ticker": "A", "sector": "Coal", "pe": 5.0, "pbv": 1.0},
                {"ticker": "B", "sector": "Coal", "pe": 6.0, "pbv": 1.1},
                {"ticker": "C", "sector": "Coal", "pe": 7.0, "pbv": 1.2},
                {"ticker": "D", "sector": "Transport", "pe": 50.0, "pbv": 9.0},
            ]
        )
    ).set_index("ticker")
    assert frame.loc["D", "value"] < 50


def test_scores_are_between_0_and_100():
    frame = score(rows([{"ticker": t, "sector": "Coal", "pe": float(i + 1)} for i, t in enumerate("ABCDE")]))
    assert frame[["value", "quality", "momentum_score", "size"]].stack().between(0, 100).all()


def test_size_not_in_composite():
    base = [{"ticker": t, "sector": "Coal", "market_cap": 1e12 * (i + 1)} for i, t in enumerate("ABC")]
    flipped = [item | {"market_cap": 1e12 * (3 - i)} for i, item in enumerate(base)]
    assert score(rows(base))["composite"].tolist() == score(rows(flipped))["composite"].tolist()


def test_composite_null_when_a_part_is_missing():
    frame = score(
        rows(
            [
                {"ticker": "A", "sector": "Coal", "momentum": None},
                {"ticker": "B", "sector": "Coal"},
                {"ticker": "C", "sector": "Coal"},
            ]
        )
    ).set_index("ticker")
    assert pd.isna(frame.loc["A", "composite"])
    assert not pd.isna(frame.loc["B", "composite"])


def test_banks_ignore_debt_in_quality():
    frame = score(
        rows(
            [
                {"ticker": "A", "sector": "Banks", "debt_to_equity": 9.0},
                {"ticker": "B", "sector": "Banks", "debt_to_equity": 0.1},
                {"ticker": "C", "sector": "Banks", "debt_to_equity": 5.0},
            ]
        )
    ).set_index("ticker")
    assert frame.loc["A", "quality"] == frame.loc["B", "quality"]


def test_momentum_skips_latest_month():
    prices = pd.Series(np.linspace(100, 150, 300))
    spiked = prices.copy()
    spiked.iloc[-10:] *= 3
    assert momentum_12_1(prices) == momentum_12_1(spiked)


def test_momentum_needs_a_year_of_data():
    assert momentum_12_1(pd.Series(np.linspace(100, 150, 200))) is None


def test_earnings_stability_higher_for_steadier_earnings():
    assert earnings_stability([100, 101, 102, 103]) > earnings_stability([50, 150, 60, 140])


def test_earnings_stability_null_for_short_or_losing_history():
    assert earnings_stability([100, 101]) is None
    assert earnings_stability([-10, -20, -30]) is None
