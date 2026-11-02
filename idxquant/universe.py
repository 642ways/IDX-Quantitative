"""The stock list. Edit universe.csv by hand when the IDX80 rebalances."""
from pathlib import Path

import pandas as pd


def load(path: Path | None = None) -> pd.DataFrame:
    return pd.read_csv(path or Path(__file__).with_name("universe.csv"), comment="#")
