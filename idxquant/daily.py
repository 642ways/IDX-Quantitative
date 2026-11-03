"""One refresh and a static export, for scheduled jobs. Run with: python -m idxquant.daily"""
import argparse
import os
import sys
import warnings

from idxquant import pipeline, yahoo
from idxquant.export import export_site
from idxquant.store import Store


def main(argv=None, fetcher=yahoo, now=None, stocks=None) -> int:
    parser = argparse.ArgumentParser(description="Refresh the data and write the static site.")
    parser.add_argument("--data", default=os.environ.get("DATA_PATH", "data/idxquant.sqlite"))
    parser.add_argument("--out", default="site")
    args = parser.parse_args(argv)

    store = Store(args.data)
    before = (store.latest_snapshot() or {}).get("ran_at")
    result = pipeline.run(store, fetcher, now, stocks=stocks)
    export_site(store, args.out)

    for warning in result.get("warnings", []):
        print(f"warning: {warning}")
    after = (store.latest_snapshot() or {}).get("ran_at")
    if after is None or after == before:
        print("Refresh failed, so the site shows the last good result.")
        return 1
    print(f"Refreshed data for {result['data_date']} with {len(result['picks'])} picks.")
    return 0


if __name__ == "__main__":
    warnings.simplefilter("ignore")  # yfinance is noisy under pandas 3
    sys.exit(main())
