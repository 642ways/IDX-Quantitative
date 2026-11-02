"""Tests whether this machine can reach Yahoo. Run with: python -m idxquant.check"""
import sys

from idxquant import yahoo

SAMPLE_TICKER = "BBCA"


def check_yahoo(fetcher=yahoo) -> dict[str, bool]:
    parts = {
        "prices": lambda: not fetcher.fetch_prices(SAMPLE_TICKER, 1).empty,
        "fundamentals": lambda: bool(fetcher.fetch_fundamentals(SAMPLE_TICKER)),
        "index": lambda: not fetcher.fetch_index().empty,
        "usdidr": lambda: fetcher.fetch_usdidr() is not None,
    }
    results = {}
    for name, part in parts.items():
        try:
            results[name] = part()
        except Exception:
            results[name] = False
    return results


def main(fetcher=yahoo) -> int:
    results = check_yahoo(fetcher)
    for name, passed in results.items():
        print(f"{name}: {'ok' if passed else 'FAILED'}")
    return 0 if all(results.values()) else 1


if __name__ == "__main__":
    sys.exit(main())
