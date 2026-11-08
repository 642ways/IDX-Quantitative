"""Local SQLite cache of prices, fundamentals and daily snapshots."""
import json
import sqlite3
from pathlib import Path

import pandas as pd

PRICE_COLUMNS = ["open", "high", "low", "close", "adj_close", "volume"]

SCHEMA = """
CREATE TABLE IF NOT EXISTS prices (
    ticker TEXT, date TEXT, open REAL, high REAL, low REAL, close REAL, adj_close REAL, volume REAL,
    PRIMARY KEY (ticker, date)
);
CREATE TABLE IF NOT EXISTS fundamentals (ticker TEXT PRIMARY KEY, payload TEXT);
CREATE TABLE IF NOT EXISTS snapshots (run_date TEXT PRIMARY KEY, payload TEXT);
"""


class Store:
    def __init__(self, path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as db:
            db.executescript(SCHEMA)

    def _connect(self) -> sqlite3.Connection:
        return sqlite3.connect(self.path)

    def save_prices(self, ticker: str, frame: pd.DataFrame) -> None:
        rows = [
            (ticker, date.strftime("%Y-%m-%d"), *[None if pd.isna(row[c]) else float(row[c]) for c in PRICE_COLUMNS])
            for date, row in frame.iterrows()
        ]
        with self._connect() as db:
            db.executemany("INSERT OR REPLACE INTO prices VALUES (?, ?, ?, ?, ?, ?, ?, ?)", rows)

    def load_prices(self, ticker: str) -> pd.DataFrame:
        with self._connect() as db:
            rows = db.execute(
                "SELECT date, open, high, low, close, adj_close, volume FROM prices WHERE ticker = ? ORDER BY date",
                (ticker,),
            ).fetchall()
        frame = pd.DataFrame(rows, columns=["date", *PRICE_COLUMNS])
        frame.index = pd.to_datetime(frame.pop("date"))
        return frame

    def save_fundamentals(self, ticker: str, data: dict) -> None:
        with self._connect() as db:
            db.execute("INSERT OR REPLACE INTO fundamentals VALUES (?, ?)", (ticker, json.dumps(data)))

    def load_fundamentals(self, ticker: str) -> dict | None:
        with self._connect() as db:
            row = db.execute("SELECT payload FROM fundamentals WHERE ticker = ?", (ticker,)).fetchone()
        return json.loads(row[0]) if row else None

    def save_snapshot(self, run_date: str, payload: dict) -> None:
        with self._connect() as db:
            db.execute("INSERT OR REPLACE INTO snapshots VALUES (?, ?)", (run_date, json.dumps(payload, allow_nan=False)))

    def latest_snapshot(self) -> dict | None:
        with self._connect() as db:
            row = db.execute("SELECT payload FROM snapshots ORDER BY run_date DESC LIMIT 1").fetchone()
        return json.loads(row[0]) if row else None

    def news_history(self) -> list[dict]:
        """Each saved day's news tone per stock, in the shape of a snapshot but without the rest of it.

        SQLite reads the tones out of the saved JSON, so the full daily results never load into memory.
        """
        with self._connect() as db:
            rows = db.execute(
                """
                SELECT json_extract(s.payload, '$.data_date'), stock.key,
                       json_extract(stock.value, '$.news.tone'), json_extract(stock.value, '$.news.count')
                FROM snapshots AS s, json_each(s.payload, '$.stocks') AS stock
                WHERE json_extract(stock.value, '$.news') IS NOT NULL
                ORDER BY s.run_date
                """
            ).fetchall()
        days = {}
        for day, ticker, tone, count in rows:
            days.setdefault(day, {})[ticker] = {"news": {"tone": tone, "count": count}}
        return [{"data_date": day, "stocks": stocks} for day, stocks in days.items()]

    def all_snapshots(self) -> list[dict]:
        with self._connect() as db:
            rows = db.execute("SELECT payload FROM snapshots ORDER BY run_date").fetchall()
        return [json.loads(row[0]) for row in rows]
