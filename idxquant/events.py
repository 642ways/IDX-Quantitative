"""Earnings reports, dividends and splits, so nobody buys the day before a surprise without knowing.

Yahoo announces the next earnings date for some IDX stocks only. When it hasn't, the next report is
estimated from the same report a year earlier, and always labelled as an estimate.
"""
from datetime import date, timedelta

from idxquant.config import CONFIG

MONTHS = ["January", "February", "March", "April", "May", "June", "July", "August", "September", "October", "November", "December"]
DIVIDEND_YEARS = 3  # Paid in the same month in each of these years counts as a habit
SPLIT_YEARS = 3


def _days(text: str) -> date:
    return date.fromisoformat(text[:10])


def _earnings(dates: list[str], today: date) -> dict | None:
    known = sorted({_days(text) for text in dates})
    if not known:
        return None
    past = [day for day in known if day < today]
    coming = [day for day in known if day >= today]
    if coming:
        upcoming, estimated = coming[0], False
    else:
        # Each report from the last 13 months, moved on a year; the first still ahead is the next one
        guesses = sorted(day + timedelta(days=365) for day in past if day >= today - timedelta(days=396))
        later = [day for day in guesses if day >= today]
        upcoming, estimated = (later[0], True) if later else (None, True)
    return {
        "next": upcoming.isoformat() if upcoming else None,
        "estimated": estimated,
        "days": (upcoming - today).days if upcoming else None,
        "last": past[-1].isoformat() if past else None,
    }


def _dividend(paid: list[list], today: date, close: float) -> dict | None:
    if not paid:
        return None
    payments = sorted((_days(day), float(amount)) for day, amount in paid)
    last_day, last_amount = payments[-1]
    year_ago = today - timedelta(days=365)
    # A month counts as usual when the stock paid in it during each of the last few years; some pay twice a year
    years = [
        {day.month for day, _ in payments if today - timedelta(days=365 * (k + 1)) <= day < today - timedelta(days=365 * k)}
        for k in range(DIVIDEND_YEARS)
    ]
    usual = sorted(set.intersection(*years)) if all(years) else []
    coming = []
    for month in usual:
        paid_this_month = any(day.year == today.year and day.month == month for day, _ in payments)
        year = today.year if month > today.month or (month == today.month and not paid_this_month) else today.year + 1
        coming.append(f"{year}-{month:02d}")
    return {
        "last": {"date": last_day.isoformat(), "amount": last_amount},
        "yield_12m": sum(amount for day, amount in payments if day >= year_ago) / close if close else None,
        "years_paid": len({day.year for day, _ in payments if day.year >= today.year - 5}),
        "usual_months": [MONTHS[month - 1] for month in usual],
        "next_expected": min(coming) if coming else None,
    }


def summarise(raw: dict | None, today: date, close: float, cfg=CONFIG) -> dict | None:
    if not raw:
        return None
    earnings = _earnings(raw.get("earnings") or [], today)
    splits = [
        {"date": _days(day).isoformat(), "ratio": float(ratio)}
        for day, ratio in raw.get("splits") or []
        if _days(day) >= today - timedelta(days=365 * SPLIT_YEARS)
    ]
    soon = None
    if earnings and earnings["days"] is not None and earnings["days"] <= cfg.event_warn_days:
        soon = (
            f"Earnings report expected in about {earnings['days']} days"
            if earnings["estimated"]
            else f"Earnings report in {earnings['days']} days"
        )
    return {
        "earnings": earnings,
        "dividend": _dividend(raw.get("dividends") or [], today, close),
        "splits": splits,
        "soon": soon,
    }
