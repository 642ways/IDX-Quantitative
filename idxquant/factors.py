"""Valuation metrics and cross-sectional factor scores."""
from datetime import date
import math

import pandas as pd

from idxquant.config import CONFIG

VALUATION_FIELDS = (
    "pe",
    "pbv",
    "ps",
    "ev_ebitda",
    "earnings_yield",
    "fcf_yield",
    "dividend_yield",
    "graham_value",
    "roe",
    "roa",
    "gross_margin",
    "operating_margin",
    "net_margin",
    "revenue_growth",
    "eps_growth",
    "eps_cagr",
    "debt_to_equity",
    "net_debt_ebitda",
    "current_ratio",
    "interest_cover",
    "market_cap",
    "eps_idr",
    "book_value_per_share",
    "dividend_per_share",
    "payout_ratio",
    "as_of",
    "stale",
)
FINANCIAL_SECTORS = ("Banks", "Finance")
MIN_SECTOR_SIZE = 3
TRADING_DAYS_PER_YEAR = 252
TRADING_DAYS_PER_MONTH = 21


def _rate_to_idr(currency: str | None, usdidr: float | None) -> float | None:
    if currency == "IDR":
        return 1.0
    if currency == "USD":
        return usdidr
    return None


def _divide(top: float | None, bottom: float | None) -> float | None:
    return None if top is None or not bottom else top / bottom


def _positive(value: float | None) -> float | None:
    return value if value is not None and value > 0 else None


def _growth(new: float | None, old: float | None) -> float | None:
    return new / old - 1 if _positive(new) and _positive(old) else None


def _details(f: dict, rate: float | None, market_cap, eps_idr, bvps, pe, sector) -> dict:
    """Figures beyond the core multiples. They're shown for detail and aren't part of any score."""
    years = f.get("history") or []
    latest, previous = (years[-1] if years else {}), (years[-2] if len(years) > 1 else {})
    in_idr = lambda value: value * rate if value is not None and rate else None

    revenue, income = latest.get("revenue"), latest.get("net_income")
    debt, cash, ebitda = latest.get("total_debt"), latest.get("cash"), _positive(latest.get("ebitda"))
    net_debt = debt - cash if debt is not None and cash is not None else None
    per_share = rate is not None and _positive(eps_idr) and _positive(bvps)
    first_eps, last_eps = (years[0].get("eps"), years[-1].get("eps")) if len(years) >= 3 else (None, None)
    span = _growth(last_eps, first_eps)
    dividend = f.get("dividends_ttm")

    result = {
        "ps": _divide(market_cap, in_idr(_positive(revenue))),
        "earnings_yield": _divide(1, pe),
        "graham_value": math.sqrt(22.5 * eps_idr * bvps) if per_share else None,
        "gross_margin": _divide(latest.get("gross_profit"), _positive(revenue)),
        "operating_margin": _divide(latest.get("operating_income"), _positive(revenue)),
        "net_margin": _divide(income, _positive(revenue)),
        "roa": _divide(income, _positive(latest.get("total_assets"))),
        "revenue_growth": _growth(revenue, previous.get("revenue")),
        "eps_growth": _growth(latest.get("eps"), previous.get("eps")),
        "eps_cagr": (1 + span) ** (1 / (len(years) - 1)) - 1 if span is not None else None,
        "dividend_per_share": dividend,
        "payout_ratio": _divide(dividend, _positive(eps_idr)),
    }
    if sector not in FINANCIAL_SECTORS:
        enterprise = market_cap + in_idr(net_debt) if market_cap is not None and in_idr(net_debt) is not None else None
        interest = latest.get("interest_expense")
        result |= {
            "ev_ebitda": _divide(_positive(enterprise), in_idr(ebitda)),
            "fcf_yield": _divide(in_idr(latest.get("free_cash_flow")), market_cap),
            "net_debt_ebitda": _divide(net_debt, ebitda),
            "current_ratio": _divide(latest.get("current_assets"), latest.get("current_liabilities")),
            "interest_cover": _divide(latest.get("operating_income"), abs(interest) if interest else None),
        }
    return result


def valuation(
    close: float, f: dict | None, usdidr: float | None, today: date | None = None, sector: str | None = None
) -> dict:
    empty = dict.fromkeys(VALUATION_FIELDS) | {"stale": True}
    if not f:
        return empty

    today = today or date.today()
    age = (today - date.fromisoformat(f["as_of"])).days
    rate = _rate_to_idr(f.get("currency"), usdidr)
    eps, equity, shares = f.get("eps"), f.get("equity"), f.get("shares")
    history = f.get("net_income_history") or []
    income = history[-1] if history else None
    has_equity = equity is not None and equity > 0

    eps_idr = eps * rate if eps is not None and rate else None
    bvps = equity * rate / shares if has_equity and rate and shares else None

    pe = close / eps_idr if eps_idr and eps_idr > 0 else None
    market_cap = close * shares if shares else None
    return empty | {
        "pe": pe,
        "pbv": close / bvps if bvps else None,
        "roe": income / equity if income is not None and has_equity else None,
        "dividend_yield": f["dividends_ttm"] / close if f.get("dividends_ttm") is not None else None,
        "market_cap": market_cap,
        "debt_to_equity": f["total_debt"] / equity if f.get("total_debt") is not None and has_equity else None,
        "eps_idr": eps_idr,
        "book_value_per_share": bvps,
        "as_of": f["as_of"],
        "stale": age > CONFIG.max_fundamental_age_days,
    } | _details(f, rate, market_cap, eps_idr, bvps, pe, sector)


def valuation_history(closes: pd.Series, f: dict | None, usdidr: float | None) -> list[dict]:
    """Each annual report valued at the price on its own date, oldest first."""
    years = (f or {}).get("history") or []
    rate = _rate_to_idr((f or {}).get("currency"), usdidr)
    in_idr = lambda value: value * rate if value is not None and rate else None
    rows = []
    for year in years:
        found = closes.asof(pd.Timestamp(year["as_of"])) if len(closes) else None
        price = None if found is None or pd.isna(found) else float(found)
        equity, shares, income = year.get("equity"), year.get("shares"), year.get("net_income")
        eps = in_idr(year.get("eps"))
        bvps = in_idr(equity) / shares if _positive(equity) and shares and rate else None
        rows.append(
            {
                "year": year["as_of"][:4],
                "price": price,
                "eps": eps,
                "pe": _divide(price, _positive(eps)),
                "pbv": _divide(price, bvps),
                "roe": _divide(income, _positive(equity)),
                "net_margin": _divide(income, _positive(year.get("revenue"))),
                "revenue": in_idr(year.get("revenue")),
                "net_income": in_idr(income),
            }
        )
    return rows


def earnings_stability(history: list[float]) -> float | None:
    """Average earnings relative to their swings. Higher means steadier."""
    if len(history) < 3:
        return None
    series = pd.Series(history, dtype=float)
    mean = series.mean()
    if mean <= 0:
        return None
    return float(mean / max(series.std(), 1e-9 * mean))


def momentum_12_1(adj_close: pd.Series) -> float | None:
    if len(adj_close) <= TRADING_DAYS_PER_YEAR:
        return None
    start = adj_close.iloc[-TRADING_DAYS_PER_YEAR - 1]
    end = adj_close.iloc[-TRADING_DAYS_PER_MONTH - 1]
    return float(end / start - 1)


def _percentile(values: pd.Series) -> pd.Series:
    return values.rank(pct=True) * 100


def _percentile_in_sector(values: pd.Series, sectors: pd.Series) -> pd.Series:
    within = values.groupby(sectors).transform(lambda group: group.rank(pct=True) * 100)
    sizes = sectors.map(sectors.value_counts())
    return within.where(sizes >= MIN_SECTOR_SIZE, _percentile(values))


def score(rows: pd.DataFrame) -> pd.DataFrame:
    frame = rows.copy()
    numeric = lambda name: pd.to_numeric(frame[name], errors="coerce")
    sectors = frame["sector"]

    value_parts = [
        _percentile_in_sector(1 / numeric("pe"), sectors),
        _percentile_in_sector(1 / numeric("pbv"), sectors),
        _percentile_in_sector(numeric("dividend_yield"), sectors),
    ]
    frame["value"] = pd.concat(value_parts, axis=1).mean(axis=1)

    debt = numeric("debt_to_equity").where(sectors != "Banks")
    quality_parts = [
        _percentile(numeric("roe")),
        _percentile(numeric("earnings_stability")),
        _percentile(-debt),
    ]
    frame["quality"] = pd.concat(quality_parts, axis=1).mean(axis=1)

    frame["momentum_score"] = _percentile(numeric("momentum"))
    frame["size"] = _percentile(numeric("market_cap"))
    frame["composite"] = frame[["value", "quality", "momentum_score"]].mean(axis=1, skipna=False)
    return frame
