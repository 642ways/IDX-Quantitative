from datetime import datetime, timedelta
import threading

from fastapi.testclient import TestClient
import pytest

from idxquant.api import create_app
from idxquant.config import CONFIG
from idxquant.factors import MIN_SECTOR_SIZE
from idxquant.pipeline import WIB
from idxquant.plays import SHORT_TREND_DAYS
from idxquant.store import Store


def snapshot(**overrides):
    now = datetime.now(WIB)
    base = {
        "run_date": "2026-10-30",
        "data_date": "2026-10-30",
        "ran_at": now.isoformat(),
        "picks": [],
        "stocks": {"BBCA": {"ticker": "BBCA", "plays": []}},
        "backtest": {"short": {"trades": 4}},
        "skipped": [],
        "warnings": [],
    }
    return base | overrides


@pytest.fixture
def store(tmp_path):
    return Store(tmp_path / "db.sqlite")


def client_for(store, runner=lambda s: snapshot()):
    return TestClient(create_app(store, runner, auto_refresh=False))


def test_today_without_snapshot_says_so(store):
    response = client_for(store).get("/api/today").json()
    assert response["picks"] == []
    assert response["data_date"] is None


def test_today_includes_the_market_regime(store):
    store.save_snapshot("2026-10-30", snapshot(regime={"label": "Stressed"}))
    assert client_for(store).get("/api/today").json()["regime"]["label"] == "Stressed"


def test_today_includes_the_market_type(store):
    store.save_snapshot("2026-10-30", snapshot(market_type={"label": "Panic"}))
    assert client_for(store).get("/api/today").json()["market_type"]["label"] == "Panic"


def test_results_include_the_market_type(store):
    store.save_snapshot("2026-10-30", snapshot(market_type={"label": "Panic"}))
    assert client_for(store).get("/api/results").json()["market_type"]["label"] == "Panic"


def test_today_returns_latest_snapshot(store):
    store.save_snapshot("2026-10-30", snapshot())
    assert client_for(store).get("/api/today").json()["data_date"] == "2026-10-30"


def test_stock_returns_its_page(store):
    store.save_snapshot("2026-10-30", snapshot())
    assert client_for(store).get("/api/stock/BBCA").json()["ticker"] == "BBCA"


def test_unknown_ticker_404(store):
    store.save_snapshot("2026-10-30", snapshot())
    assert client_for(store).get("/api/stock/NOPE").status_code == 404


def test_results_has_backtest_and_track_record(store):
    store.save_snapshot("2026-10-30", snapshot())
    body = client_for(store).get("/api/results").json()
    assert body["backtest"]["short"]["trades"] == 4
    assert body["track_record"] == []


def test_results_include_the_market_regime(store):
    store.save_snapshot("2026-10-30", snapshot(regime={"label": "Calm"}))
    assert client_for(store).get("/api/results").json()["regime"]["label"] == "Calm"


def test_second_refresh_ignored_while_running(store):
    release, calls = threading.Event(), []

    def slow(_):
        calls.append(1)
        release.wait(5)
        return snapshot()

    client = client_for(store, slow)
    assert client.post("/api/refresh").json()["started"] is True
    assert client.post("/api/refresh").json()["started"] is False
    release.set()
    assert len(calls) == 1


def wait_for_refresh(client):
    for _ in range(200):
        status = client.get("/api/refresh/status").json()
        if not status["running"]:
            return status
        threading.Event().wait(0.01)
    raise AssertionError("refresh never finished")


def test_failed_refresh_keeps_last_data_and_warns(store):
    store.save_snapshot("2026-10-30", snapshot())

    def broken(_):
        raise RuntimeError("boom")

    client = client_for(store, broken)
    client.post("/api/refresh")
    assert wait_for_refresh(client)["running"] is False
    body = client.get("/api/today").json()
    assert body["data_date"] == "2026-10-30"
    assert body["warnings"]


def test_warning_from_failed_run_is_shown_until_next_success(store):
    store.save_snapshot("2026-10-30", snapshot())
    client = client_for(store, lambda s: snapshot(warnings=["Refresh failed"]))
    client.post("/api/refresh")
    wait_for_refresh(client)
    assert client.get("/api/today").json()["warnings"] == ["Refresh failed"]


def test_methods_shows_the_live_settings(store):
    body = client_for(store).get("/api/methods").json()
    assert body["long_stop"] == CONFIG.long_stop
    assert body["mc_paths"] == CONFIG.mc_paths
    assert body["short_trend_days"] == SHORT_TREND_DAYS
    assert body["min_sector_size"] == MIN_SECTOR_SIZE


def test_methods_script_is_served(store):
    assert client_for(store).get("/static/methods.js").status_code == 200


def test_health_check(store):
    assert client_for(store).get("/health").json() == {"status": "ok"}


def test_server_limits_how_often_refresh_can_run(store):
    calls = []
    app = create_app(store, lambda s: calls.append(1) or snapshot(), auto_refresh=False, limit_refresh=True)
    client = TestClient(app)
    assert client.post("/api/refresh").json()["started"] is True
    wait_for_refresh(client)
    assert client.post("/api/refresh").json()["started"] is False
    assert calls == [1]


def test_local_refresh_is_not_limited(store):
    client = client_for(store)
    assert client.post("/api/refresh").json()["started"] is True
    wait_for_refresh(client)
    assert client.post("/api/refresh").json()["started"] is True


def test_scheduler_refreshes_when_data_is_due(store):
    calls = []
    done = threading.Event()

    def runner(_):
        calls.append(1)
        done.set()
        return snapshot()

    app = create_app(store, runner, auto_refresh=False, scheduled=True, schedule_seconds=0.01)
    assert done.wait(5)
    threading.Event().wait(0.1)
    app.state.stop_schedule.set()
    assert len(calls) == 1


def test_scheduler_leaves_fresh_data_alone(store):
    today = datetime.now(WIB).date().isoformat()
    store.save_snapshot(today, snapshot(data_date=today))
    calls = []
    app = create_app(
        store, lambda s: calls.append(1) or snapshot(), auto_refresh=False, scheduled=True, schedule_seconds=0.01
    )
    threading.Event().wait(0.2)
    app.state.stop_schedule.set()
    assert calls == []


def test_page_is_served(store):
    response = client_for(store).get("/")
    assert response.status_code == 200
    assert "Model output, not personal advice" in response.text


def test_auto_refresh_runs_when_data_is_old(store):
    old = (datetime.now(WIB) - timedelta(days=9)).isoformat()
    store.save_snapshot("2026-10-20", snapshot(ran_at=old))
    calls = []
    app = create_app(store, lambda s: calls.append(1) or snapshot(), auto_refresh=True)
    client = TestClient(app)
    client.get("/api/today")
    wait_for_refresh(client)
    assert calls == [1]
