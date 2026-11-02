import pandas as pd

from idxquant.store import Store


def bars(dates, close=100.0):
    idx = pd.to_datetime(dates)
    return pd.DataFrame(
        {"open": close, "high": close, "low": close, "close": close, "adj_close": close, "volume": 1000.0},
        index=idx,
    )


def test_prices_round_trip(tmp_path):
    store = Store(tmp_path / "db.sqlite")
    store.save_prices("BBCA", bars(["2026-10-29", "2026-10-30"]))
    loaded = store.load_prices("BBCA")
    assert list(loaded.index.strftime("%Y-%m-%d")) == ["2026-10-29", "2026-10-30"]
    assert loaded["close"].iloc[-1] == 100.0


def test_saving_same_date_twice_keeps_one_row(tmp_path):
    store = Store(tmp_path / "db.sqlite")
    store.save_prices("BBCA", bars(["2026-10-30"], close=100.0))
    store.save_prices("BBCA", bars(["2026-10-30"], close=105.0))
    loaded = store.load_prices("BBCA")
    assert len(loaded) == 1
    assert loaded["close"].iloc[0] == 105.0


def test_unknown_ticker_loads_empty(tmp_path):
    assert Store(tmp_path / "db.sqlite").load_prices("NOPE").empty


def test_fundamentals_round_trip(tmp_path):
    store = Store(tmp_path / "db.sqlite")
    store.save_fundamentals("BBCA", {"eps": 467, "currency": "IDR"})
    assert store.load_fundamentals("BBCA")["eps"] == 467
    assert store.load_fundamentals("NOPE") is None


def test_latest_snapshot_is_newest_run_date(tmp_path):
    store = Store(tmp_path / "db.sqlite")
    store.save_snapshot("2026-10-30", {"run_date": "2026-10-30"})
    store.save_snapshot("2026-11-02", {"run_date": "2026-11-02"})
    store.save_snapshot("2026-10-29", {"run_date": "2026-10-29"})
    assert store.latest_snapshot()["run_date"] == "2026-11-02"
    assert len(store.all_snapshots()) == 3


def test_no_snapshot_is_none(tmp_path):
    assert Store(tmp_path / "db.sqlite").latest_snapshot() is None
