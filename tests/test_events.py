from datetime import date

import pytest

from idxquant import events

TODAY = date(2026, 11, 8)


def raw(earnings=(), dividends=(), splits=()):
    return {"earnings": list(earnings), "dividends": [list(d) for d in dividends], "splits": [list(s) for s in splits]}


def test_nothing_from_yahoo_gives_nothing():
    assert events.summarise(None, TODAY, 1000) is None


def test_an_announced_earnings_date_is_shown_as_it_is():
    result = events.summarise(raw(earnings=["2026-01-27", "2026-10-26", "2027-01-26"]), TODAY, 1000)
    assert result["earnings"] == {"next": "2027-01-26", "estimated": False, "days": 79, "last": "2026-10-26"}


def test_without_an_announced_date_the_next_report_is_estimated_from_last_year():
    result = events.summarise(raw(earnings=["2025-10-20", "2026-01-27", "2026-04-23", "2026-07-28", "2026-10-26"]), TODAY, 1000)
    assert result["earnings"]["next"] == "2027-01-27"
    assert result["earnings"]["estimated"] is True
    assert result["earnings"]["last"] == "2026-10-26"


def test_a_report_due_within_two_weeks_is_flagged():
    result = events.summarise(raw(earnings=["2026-11-12"]), TODAY, 1000)
    assert result["soon"] == "Earnings report in 4 days"


def test_an_estimated_report_soon_is_flagged_as_expected():
    result = events.summarise(raw(earnings=["2025-11-15"]), TODAY, 1000)
    assert result["soon"] == "Earnings report expected in about 7 days"


def test_dividends_give_the_last_payment_the_yield_and_the_usual_month():
    paid = [("2024-06-20", 150.0), ("2025-06-23", 160.0), ("2026-06-22", 210.0)]
    result = events.summarise(raw(dividends=paid), TODAY, 2100)
    dividend = result["dividend"]
    assert dividend["last"] == {"date": "2026-06-22", "amount": 210.0}
    assert dividend["yield_12m"] == pytest.approx(0.10)
    assert dividend["years_paid"] == 3
    assert dividend["usual_months"] == ["June"]
    assert dividend["next_expected"] == "2027-06"


def test_a_stock_paying_twice_a_year_has_two_usual_months():
    paid = [(f"{year}-{month}", 100.0) for year in (2023, 2024, 2025, 2026) for month in ("03-20", "11-25")]
    paid = [p for p in paid if p[0] < "2026-11-08"]
    result = events.summarise(raw(dividends=paid), TODAY, 1000)
    assert result["dividend"]["usual_months"] == ["March", "November"]
    assert result["dividend"]["next_expected"] == "2026-11"


def test_irregular_dividends_have_no_expected_month():
    paid = [("2023-03-10", 50.0), ("2025-09-01", 20.0)]
    result = events.summarise(raw(dividends=paid), TODAY, 1000)
    assert result["dividend"]["usual_months"] == []
    assert result["dividend"]["next_expected"] is None


def test_recent_splits_are_listed_and_old_ones_left_out():
    result = events.summarise(raw(splits=[("2013-08-28", 5.0), ("2025-02-03", 2.0)]), TODAY, 1000)
    assert result["splits"] == [{"date": "2025-02-03", "ratio": 2.0}]
