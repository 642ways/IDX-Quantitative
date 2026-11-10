"""One refresh and a static export, for scheduled jobs. Run with: python -m idxquant.daily"""
import argparse
from datetime import datetime
import os
import sys
import warnings

from idxquant import pipeline, yahoo
from idxquant.export import export_site
from idxquant.pipeline import WIB
from idxquant.store import Store


def main(argv=None, fetcher=yahoo, now=None, stocks=None) -> int:
    parser = argparse.ArgumentParser(description="Refresh the data and write the static site.")
    parser.add_argument("--data", default=os.environ.get("DATA_PATH", "data/idxquant.sqlite"))
    parser.add_argument("--out", default="site")
    parser.add_argument(
        "--if-due",
        action="store_true",
        help="Skip the refresh when today's final data is already saved. For scheduled backup runs.",
    )
    args = parser.parse_args(argv)

    store = Store(args.data)
    latest = store.latest_snapshot()
    if args.if_due and not pipeline.needs_refresh(now or datetime.now(WIB), latest):
        export_site(store, args.out)
        print(f"Already up to date: data for {latest['data_date']}, refreshed at {latest['ran_at']}. Nothing to do.")
        return 0
    before = (latest or {}).get("ran_at")
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
